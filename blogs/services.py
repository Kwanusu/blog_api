"""Memberships and tips: the two things readers pay for with M-Pesa."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from payments import services as payment_services
from payments.models import Payment
from payments.services import PaymentError

from .models import Membership, Tip

MIN_TIP = 10
MAX_TIP = 70000   # comfortably under M-Pesa's per-transaction ceiling
DUPLICATE_WINDOW = timedelta(seconds=60)


class PurchaseError(Exception):
    """A rule violation worth showing to the user as-is."""


def _recent_pending(queryset):
    """A prompt sent moments ago and still unanswered: a double-click must not send another one."""
    return (
        queryset.filter(payment__status=Payment.Status.PENDING, created_at__gte=timezone.now() - DUPLICATE_WINDOW)
        .select_related('payment').first()
    )


def start_membership(user, plan, phone):
    """Create a pending membership and send the M-Pesa prompt. Returns the Payment."""
    if not plan.is_active:
        raise PurchaseError('That plan is no longer available.')
    recent = _recent_pending(Membership.objects.filter(user=user, plan=plan, status=Membership.Status.PENDING))
    if recent:
        return recent.payment

    with transaction.atomic():
        membership = Membership.objects.create(user=user, plan=plan)
    try:
        payment = payment_services.initiate_stk(
            user=user, phone=phone, amount=plan.price, purpose=Payment.Purpose.MEMBERSHIP,
            reference=f'MEM-{membership.pk}', description='Membership',
        )
    except PaymentError:
        membership.delete()   # nothing was prompted or charged, so leave no orphan row behind
        raise
    membership.payment = payment
    membership.save(update_fields=['payment'])
    return payment


def start_tip(user, blog, amount, phone, message=''):
    """Create a pending tip and send the M-Pesa prompt. Returns the Payment."""
    if blog.author.user_id == user.id:
        raise PurchaseError('You can’t tip yourself.')
    if not MIN_TIP <= amount <= MAX_TIP:
        raise PurchaseError(f'Tips must be between KES {MIN_TIP} and KES {MAX_TIP:,}.')
    recent = _recent_pending(
        Tip.objects.filter(tipper=user, blog=blog, amount=amount, status=Tip.Status.PENDING)
    )
    if recent:
        return recent.payment

    tip = Tip.objects.create(blog=blog, author=blog.author, tipper=user, amount=amount, message=message[:200])
    try:
        payment = payment_services.initiate_stk(
            user=user, phone=phone, amount=amount, purpose=Payment.Purpose.TIP,
            reference=f'TIP-{tip.pk}', description='Author tip',
        )
    except PaymentError:
        tip.delete()
        raise
    tip.payment = payment
    tip.save(update_fields=['payment'])
    return payment
