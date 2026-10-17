"""
Payment lifecycle: start an STK push, apply Safaricom's result exactly once, reconcile
payments whose callback never arrived.
"""
import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from . import mpesa
from .models import Payment
from .signals import payment_finished

logger = logging.getLogger(__name__)

DUPLICATE_WINDOW = timedelta(seconds=60)   # a double-click returns the prompt already sent
REAL_QUERY_AFTER = timedelta(seconds=15)   # give the callback a head start before polling Daraja
GIVE_UP_AFTER = timedelta(minutes=10)      # a prompt that never resolves is treated as timed out


class PaymentError(Exception):
    """A problem worth showing to the customer as-is."""


def callback_url():
    secret = settings.MPESA_CALLBACK_SECRET
    simulated = mpesa.is_simulated()
    if not secret and not simulated:
        raise PaymentError('M-Pesa callbacks are not configured yet (MPESA_CALLBACK_SECRET).')
    base = (settings.MPESA_CALLBACK_BASE_URL or settings.SITE_URL).rstrip('/')
    if not simulated and not base.startswith('https://'):
        raise PaymentError('M-Pesa needs a public HTTPS callback URL (set MPESA_CALLBACK_BASE_URL).')
    path = reverse('payments:mpesa_callback', kwargs={'secret': secret or 'simulate'})
    return f'{base}{path}'


def _whole_shillings(amount):
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        raise PaymentError('Enter a valid amount.')
    if value < 1 or value != value.to_integral_value():
        raise PaymentError('M-Pesa payments must be a whole number of shillings, at least KES 1.')
    return value


def initiate_stk(*, user, phone, amount, purpose, reference, description):
    """
    Create a pending Payment and send the PIN prompt. Returns the Payment.
    Raises PaymentError with a customer-friendly message on any failure.
    """
    try:
        msisdn = mpesa.normalize_phone(phone)
    except ValueError as exc:
        raise PaymentError(str(exc))
    amount = _whole_shillings(amount)

    # Idempotency: don't spam the customer's phone if they click twice.
    recent = Payment.objects.filter(
        user=user, purpose=purpose, account_reference=reference,
        status=Payment.Status.PENDING, created_at__gte=timezone.now() - DUPLICATE_WINDOW,
    ).first()
    if recent:
        return recent

    callback = callback_url()
    payment = Payment.objects.create(
        user=user, phone=msisdn, amount=amount, purpose=purpose,
        account_reference=reference[:12], description=description[:13],
    )
    try:
        data = mpesa.stk_push(
            phone=msisdn, amount=amount, account_reference=payment.account_reference,
            description=payment.description or 'Payment', callback_url=callback,
        )
    except mpesa.MpesaError as exc:
        payment.status = Payment.Status.FAILED
        payment.result_desc = str(exc)[:255]
        payment.save(update_fields=['status', 'result_desc', 'updated_at'])
        raise PaymentError(str(exc)) from exc

    payment.merchant_request_id = data.get('MerchantRequestID', '')
    payment.checkout_request_id = data.get('CheckoutRequestID')
    payment.save(update_fields=['merchant_request_id', 'checkout_request_id', 'updated_at'])
    return payment


def _parse_paid_at(raw):
    try:
        naive = datetime.strptime(str(raw), '%Y%m%d%H%M%S')
        return timezone.make_aware(naive)
    except (ValueError, TypeError):
        return timezone.now()


def apply_result(checkout_request_id, *, result_code, result_desc='', receipt='',
                 amount=None, paid_at=None, payload=None):
    """
    Settle a pending payment. Safe to call repeatedly (Safaricom retries callbacks, and
    reconciliation may race them): only the first call changes anything.
    Returns the Payment, or None if the checkout id is unknown.
    """
    with transaction.atomic():
        try:
            payment = Payment.objects.select_for_update().get(checkout_request_id=checkout_request_id)
        except Payment.DoesNotExist:
            logger.warning('Result for unknown checkout id %s', checkout_request_id)
            return None

        if payment.status != Payment.Status.PENDING:
            # A late callback can still supply the receipt that a status query doesn't return.
            if payment.is_success and receipt and not payment.mpesa_receipt:
                payment.mpesa_receipt = receipt
                payment.callback_payload = payload or payment.callback_payload
                payment.save(update_fields=['mpesa_receipt', 'callback_payload', 'updated_at'])
            return payment

        payment.result_code = result_code
        payment.result_desc = (result_desc or '')[:255]
        payment.callback_payload = payload
        if result_code == mpesa.RESULT_SUCCESS:
            if amount is not None and Decimal(str(amount)) != payment.amount:
                logger.error('Amount mismatch on %s: expected %s got %s', payment.pk, payment.amount, amount)
                payment.status = Payment.Status.REVIEW
            else:
                payment.status = Payment.Status.SUCCESS
                payment.mpesa_receipt = receipt
                payment.paid_at = paid_at or timezone.now()
        elif result_code == mpesa.RESULT_CANCELLED:
            payment.status = Payment.Status.CANCELLED
        else:
            payment.status = Payment.Status.FAILED
        payment.save()
        transaction.on_commit(lambda: payment_finished.send(sender=Payment, payment=payment))
    return payment


def handle_callback(data):
    """Apply a Daraja STK callback body. Raises ValueError if it is malformed."""
    try:
        cb = data['Body']['stkCallback']
        checkout_id = cb['CheckoutRequestID']
        code = int(cb['ResultCode'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Malformed callback') from exc
    items = (cb.get('CallbackMetadata') or {}).get('Item') or []
    meta = {i.get('Name'): i.get('Value') for i in items if isinstance(i, dict)}
    return apply_result(
        checkout_id,
        result_code=code,
        result_desc=str(cb.get('ResultDesc', '')),
        receipt=str(meta.get('MpesaReceiptNumber') or ''),
        amount=meta.get('Amount'),
        paid_at=_parse_paid_at(meta['TransactionDate']) if meta.get('TransactionDate') else None,
        payload=data,
    )


def reconcile(payment, *, force=False):
    """
    Ask Daraja (or the simulator) what happened to a pending payment whose callback hasn't
    arrived. Cheap to call repeatedly: it rate-limits itself.
    """
    if not payment.is_pending or not payment.checkout_request_id:
        return payment
    now = timezone.now()
    age = now - payment.created_at

    if mpesa.is_simulated():
        if age >= timedelta(seconds=settings.MPESA_SIMULATE_DELAY):
            declined = payment.phone.endswith('999')   # demo a cancelled prompt
            result = apply_result(
                payment.checkout_request_id,
                result_code=mpesa.RESULT_CANCELLED if declined else mpesa.RESULT_SUCCESS,
                result_desc='Simulated: request cancelled by user' if declined else 'Simulated success',
                receipt='' if declined else f'SIM{uuid.uuid4().hex[:7].upper()}',
                amount=payment.amount,
            )
            return result or payment
        return payment

    if not force:
        if age < REAL_QUERY_AFTER:
            return payment
        if payment.checked_at and now - payment.checked_at < timedelta(seconds=10):
            return payment

    Payment.objects.filter(pk=payment.pk).update(checked_at=now)
    try:
        result = mpesa.stk_query(payment.checkout_request_id)
    except mpesa.MpesaError as exc:
        logger.info('Status query failed for %s: %s', payment.pk, exc)
        result = None

    if result is None:
        if age >= GIVE_UP_AFTER:
            result = {'ResultCode': mpesa.RESULT_TIMEOUT, 'ResultDesc': 'No response from the customer.'}
        else:
            payment.refresh_from_db()
            return payment
    settled = apply_result(
        payment.checkout_request_id,
        result_code=result['ResultCode'],
        result_desc=result.get('ResultDesc', ''),
        payload=result,
    )
    return settled or payment


def expire_orphans():
    """
    Close pending payments that were never sent to Safaricom. Returns how many were closed.

    ``initiate_stk`` saves the Payment *before* calling Daraja, so a crash in between (server
    restart, killed worker) leaves a row with no ``checkout_request_id``. Reconciliation ignores
    such rows because there is nothing to ask Daraja about, which would leave them "pending" forever
    and, for course fees, keep a seat reserved. Nothing was charged, so they are marked failed.
    """
    return Payment.objects.filter(
        status=Payment.Status.PENDING,
        checkout_request_id__isnull=True,
        created_at__lt=timezone.now() - GIVE_UP_AFTER,
    ).update(
        status=Payment.Status.FAILED,
        result_desc='The payment request was never sent.',
        updated_at=timezone.now(),
    )
