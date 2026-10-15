import base64
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import User

from . import mpesa, services
from .models import Payment
from .signals import payment_finished

MPESA = dict(
    MPESA_ENV='sandbox',
    MPESA_CONSUMER_KEY='key-abcdef',
    MPESA_CONSUMER_SECRET='secret',
    MPESA_SHORTCODE='174379',
    MPESA_PASSKEY='passkey',
    MPESA_CALLBACK_SECRET='s3cret',
    MPESA_CALLBACK_BASE_URL='https://example.ngrok.app',
)
CALLBACK_URL = '/api/payments/mpesa/callback/s3cret/'
STK_OK = {'MerchantRequestID': 'mr-1', 'CheckoutRequestID': 'ws_CO_1', 'ResponseCode': '0'}


def fake_response(payload, status=200):
    res = mock.Mock(status_code=status)
    res.json.return_value = payload
    res.raise_for_status.return_value = None
    return res


def callback_body(checkout='ws_CO_1', code=0, amount=500, receipt='QGH12345AB'):
    cb = {'MerchantRequestID': 'mr-1', 'CheckoutRequestID': checkout, 'ResultCode': code,
          'ResultDesc': 'processed' if code == 0 else 'Cancelled'}
    if code == 0:
        cb['CallbackMetadata'] = {'Item': [
            {'Name': 'Amount', 'Value': amount},
            {'Name': 'MpesaReceiptNumber', 'Value': receipt},
            {'Name': 'TransactionDate', 'Value': 20260115123456},
            {'Name': 'PhoneNumber', 'Value': 254712345678},
        ]}
    return {'Body': {'stkCallback': cb}}


class PhoneTests(SimpleTestCase):
    def test_normalises_common_formats(self):
        for raw in ('0712345678', '+254712345678', '254712345678', '712345678', '0712 345 678', '0712-345-678'):
            self.assertEqual(mpesa.normalize_phone(raw), '254712345678', raw)
        self.assertEqual(mpesa.normalize_phone('0110123456'), '254110123456')

    def test_rejects_bad_numbers(self):
        for raw in ('', 'abc', '0612345678', '07123', '25571234567', '+1 555 123 4567'):
            with self.assertRaises(ValueError, msg=raw):
                mpesa.normalize_phone(raw)


@override_settings(**MPESA)
class DarajaClientTests(TestCase):
    def setUp(self):
        cache.clear()

    @mock.patch('payments.mpesa.requests.post')
    @mock.patch('payments.mpesa.requests.get')
    def test_stk_push_payload_and_token_cache(self, get, post):
        get.return_value = fake_response({'access_token': 'tok', 'expires_in': '3599'})
        post.return_value = fake_response(STK_OK)
        kwargs = dict(phone='254712345678', amount=Decimal('500'), account_reference='ENR-1',
                      description='Course fee', callback_url='https://x/cb/')
        mpesa.stk_push(**kwargs)
        mpesa.stk_push(**kwargs)
        self.assertEqual(get.call_count, 1, 'access token should be cached between pushes')
        sent = post.call_args.kwargs['json']
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer tok')
        self.assertEqual((sent['Amount'], sent['PartyA'], sent['PhoneNumber'], sent['PartyB']),
                         (500, '254712345678', '254712345678', '174379'))
        self.assertEqual(sent['CallBackURL'], 'https://x/cb/')
        self.assertEqual(base64.b64decode(sent['Password']).decode(), f"174379passkey{sent['Timestamp']}")

    @mock.patch('payments.mpesa.requests.post')
    @mock.patch('payments.mpesa.requests.get')
    def test_rejected_push_raises_with_daraja_message(self, get, post):
        get.return_value = fake_response({'access_token': 'tok', 'expires_in': '3599'})
        post.return_value = fake_response({'errorMessage': 'Bad Request - Invalid PhoneNumber'}, status=400)
        with self.assertRaisesMessage(mpesa.MpesaError, 'Invalid PhoneNumber'):
            mpesa.stk_push(phone='254712345678', amount=5, account_reference='A', description='B', callback_url='https://x/')

    @override_settings(MPESA_CONSUMER_KEY='')
    def test_missing_credentials_is_a_clear_error(self):
        with self.assertRaisesMessage(mpesa.MpesaError, 'not configured'):
            mpesa.access_token()

    @mock.patch('payments.mpesa.requests.post')
    @mock.patch('payments.mpesa.requests.get')
    def test_query_pending_and_result(self, get, post):
        get.return_value = fake_response({'access_token': 'tok', 'expires_in': '3599'})
        post.return_value = fake_response({'errorCode': '500.001.1001'}, status=500)
        self.assertIsNone(mpesa.stk_query('ws_CO_1'))
        post.return_value = fake_response({'ResponseCode': '0', 'ResultCode': '1032', 'ResultDesc': 'Cancelled'})
        self.assertEqual(mpesa.stk_query('ws_CO_1')['ResultCode'], 1032)

    @override_settings(MPESA_ENV='simulate', DEBUG=False)
    def test_simulate_refused_without_debug(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            mpesa.env()


@override_settings(**MPESA)
class InitiateTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('pay@x.com', 'pw-Strong-123')

    def start(self, **over):
        args = dict(user=self.user, phone='0712345678', amount=500, purpose=Payment.Purpose.ENROLLMENT,
                    reference='ENR-1', description='Course fee')
        args.update(over)
        return services.initiate_stk(**args)

    @mock.patch('payments.services.mpesa.stk_push', return_value=STK_OK)
    def test_creates_pending_payment_with_ids_and_callback_url(self, push):
        p = self.start()
        self.assertEqual((p.status, p.phone, p.amount, p.checkout_request_id),
                         (Payment.Status.PENDING, '254712345678', Decimal('500'), 'ws_CO_1'))
        url = push.call_args.kwargs['callback_url']
        self.assertEqual(url, 'https://example.ngrok.app/api/payments/mpesa/callback/s3cret/')

    @mock.patch('payments.services.mpesa.stk_push', return_value=STK_OK)
    def test_double_click_does_not_send_a_second_prompt(self, push):
        self.assertEqual(self.start().pk, self.start().pk)
        self.assertEqual(push.call_count, 1)

    @mock.patch('payments.services.mpesa.stk_push', side_effect=mpesa.MpesaError('M-Pesa is down'))
    def test_daraja_failure_marks_payment_failed(self, push):
        with self.assertRaisesMessage(services.PaymentError, 'M-Pesa is down'):
            self.start()
        self.assertEqual(Payment.objects.get().status, Payment.Status.FAILED)

    def test_validation(self):
        for bad in ({'phone': '12345'}, {'amount': 0}, {'amount': '12.50'}):
            with self.assertRaises(services.PaymentError):
                self.start(**bad)
        self.assertEqual(Payment.objects.count(), 0)

    @override_settings(MPESA_CALLBACK_BASE_URL='http://insecure.example', SITE_URL='http://localhost:8000')
    def test_callback_must_be_public_https(self):
        with self.assertRaisesMessage(services.PaymentError, 'HTTPS'):
            self.start()

    @override_settings(MPESA_CALLBACK_SECRET='')
    def test_callback_secret_required(self):
        with self.assertRaises(services.PaymentError):
            self.start()


@override_settings(**MPESA)
class CallbackApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('cb@x.com', 'pw-Strong-123')
        self.payment = Payment.objects.create(
            user=self.user, phone='254712345678', amount=500, purpose=Payment.Purpose.ENROLLMENT,
            checkout_request_id='ws_CO_1', merchant_request_id='mr-1',
        )
        self.finished = []
        self.addCleanup(payment_finished.disconnect, self._record)
        payment_finished.connect(self._record)

    def _record(self, sender, payment, **kw):
        self.finished.append(payment.pk)

    def post(self, body, url=CALLBACK_URL):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(url, body, format='json')

    def test_callback_needs_no_login_and_marks_paid(self):
        res = self.post(callback_body())       # anonymous client: Safaricom has no token
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {'ResultCode': 0, 'ResultDesc': 'Accepted'})
        self.payment.refresh_from_db()
        self.assertEqual((self.payment.status, self.payment.mpesa_receipt), (Payment.Status.SUCCESS, 'QGH12345AB'))
        self.assertIsNotNone(self.payment.paid_at)
        self.assertEqual(self.finished, [self.payment.pk])

    def test_retried_callback_is_idempotent(self):
        self.post(callback_body())
        self.post(callback_body())
        self.assertEqual(self.finished, [self.payment.pk], 'signal must fire exactly once')

    def test_user_cancelled_and_insufficient_funds(self):
        self.post(callback_body(code=1032))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.CANCELLED)
        other = Payment.objects.create(user=self.user, phone='254712345678', amount=5, purpose='tip',
                                       checkout_request_id='ws_CO_2')
        self.post(callback_body(checkout='ws_CO_2', code=1))
        other.refresh_from_db()
        self.assertEqual(other.status, Payment.Status.FAILED)

    def test_amount_mismatch_goes_to_review_not_success(self):
        self.post(callback_body(amount=1))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.REVIEW)

    def test_wrong_secret_is_404_and_changes_nothing(self):
        res = self.post(callback_body(), url='/api/payments/mpesa/callback/guess/')
        self.assertEqual(res.status_code, 404)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

    def test_malformed_body_is_400(self):
        self.assertEqual(self.post({'nope': 1}).status_code, 400)

    def test_unknown_checkout_id_is_accepted_quietly(self):
        self.assertEqual(self.post(callback_body(checkout='ws_CO_unknown')).status_code, 200)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(CALLBACK_URL).status_code, 405)

    def test_callback_is_never_rate_limited(self):
        """Safaricom's servers share one IP; the anonymous throttle must not block them."""
        for _ in range(80):
            self.assertEqual(self.client.post(CALLBACK_URL, callback_body(checkout='ws_CO_unknown'), format='json').status_code, 200)

    def test_late_callback_backfills_receipt_after_reconcile_settled_it(self):
        with self.captureOnCommitCallbacks(execute=True):
            services.apply_result('ws_CO_1', result_code=0, result_desc='ok')   # a status query has no receipt
        self.post(callback_body())
        self.payment.refresh_from_db()
        self.assertEqual((self.payment.status, self.payment.mpesa_receipt), (Payment.Status.SUCCESS, 'QGH12345AB'))
        self.assertEqual(self.finished, [self.payment.pk])


@override_settings(**MPESA)
class PaymentApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user('own@x.com', 'pw-Strong-123')
        self.other = User.objects.create_user('other@x.com', 'pw-Strong-123')
        self.payment = Payment.objects.create(
            user=self.owner, phone='254712345678', amount=100, purpose=Payment.Purpose.TIP,
            checkout_request_id='ws_CO_9',
        )

    def test_requires_login(self):
        self.assertEqual(self.client.get('/api/payments/').status_code, 401)
        self.assertEqual(self.client.get(f'/api/payments/{self.payment.pk}/').status_code, 401)

    def test_owner_sees_state(self):
        self.client.force_authenticate(self.owner)
        data = self.client.get(f'/api/payments/{self.payment.pk}/').json()
        self.assertEqual((data['status'], data['pending'], data['amount']), ('pending', True, 100))
        self.assertIn('M-Pesa PIN', data['message'])

    def test_other_users_get_404_and_lists_are_private(self):
        Payment.objects.create(user=self.other, phone='254712345679', amount=7, purpose='tip')
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f'/api/payments/{self.payment.pk}/').status_code, 404)
        results = self.client.get('/api/payments/').json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['amount'], 7)

    def test_success_shows_receipt(self):
        services.apply_result('ws_CO_9', result_code=0, receipt='R1', amount=100)
        self.client.force_authenticate(self.owner)
        data = self.client.get(f'/api/payments/{self.payment.pk}/').json()
        self.assertEqual((data['success'], data['mpesa_receipt'], data['status']), (True, 'R1', 'success'))

    @mock.patch('payments.services.mpesa.stk_query', return_value={'ResultCode': 0, 'ResultDesc': 'ok'})
    def test_polling_reconciles_a_missing_callback(self, query):
        Payment.objects.filter(pk=self.payment.pk).update(created_at=timezone.now() - timedelta(minutes=2))
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get(f'/api/payments/{self.payment.pk}/').json()['status'], 'success')
        query.assert_called_once_with('ws_CO_9')

    @mock.patch('payments.services.mpesa.stk_query', return_value=None)
    def test_stuck_payment_times_out_after_ten_minutes(self, query):
        Payment.objects.filter(pk=self.payment.pk).update(created_at=timezone.now() - timedelta(minutes=11))
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get(f'/api/payments/{self.payment.pk}/').json()['status'], 'failed')

    @mock.patch('payments.services.mpesa.stk_query')
    def test_young_payments_are_not_polled_against_daraja(self, query):
        self.client.force_authenticate(self.owner)
        self.client.get(f'/api/payments/{self.payment.pk}/')
        query.assert_not_called()

    def test_payments_are_read_only_over_the_api(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post('/api/payments/', {'amount': 1}, format='json').status_code, 405)
        self.assertEqual(self.client.delete(f'/api/payments/{self.payment.pk}/').status_code, 405)
        self.assertEqual(self.client.patch(f'/api/payments/{self.payment.pk}/', {'status': 'success'}, format='json').status_code, 405)


@override_settings(MPESA_ENV='simulate', DEBUG=True, MPESA_SIMULATE_DELAY=0, MPESA_CALLBACK_SECRET='')
class SimulatorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('sim@x.com', 'pw-Strong-123')

    def pay(self, phone):
        return services.initiate_stk(user=self.user, phone=phone, amount=250, purpose=Payment.Purpose.TIP,
                                     reference='T-1', description='Tip')

    def test_simulated_payment_completes_without_network(self):
        with mock.patch('payments.mpesa.requests.post') as post, mock.patch('payments.mpesa.requests.get') as get:
            p = services.reconcile(self.pay('0712345678'))
        post.assert_not_called()
        get.assert_not_called()
        self.assertEqual(p.status, Payment.Status.SUCCESS)
        self.assertTrue(p.mpesa_receipt.startswith('SIM'))

    def test_phone_ending_999_simulates_a_cancelled_prompt(self):
        self.assertEqual(services.reconcile(self.pay('0712345999')).status, Payment.Status.CANCELLED)
