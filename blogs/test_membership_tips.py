"""Premium posts, memberships, tips and author earnings."""
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import User
from payments.models import Payment

from .models import Author, Blog, Membership, MembershipPlan, Tip

PW = 'pw-Strong-123'
MPESA = dict(
    MPESA_ENV='sandbox', MPESA_CONSUMER_KEY='k', MPESA_CONSUMER_SECRET='s', MPESA_SHORTCODE='174379',
    MPESA_PASSKEY='p', MPESA_CALLBACK_SECRET='sec', MPESA_CALLBACK_BASE_URL='https://example.ngrok.app',
)
CALLBACK = '/api/payments/mpesa/callback/sec/'
LONG_TEXT = 'THE FULL SECRET TEXT. ' * 40


def stk_ok(checkout='ws_CO_B1'):
    return {'MerchantRequestID': 'mr', 'CheckoutRequestID': checkout, 'ResponseCode': '0'}


class Base(APITestCase):
    @classmethod
    def setUpTestData(cls):
        mk = User.objects.create_user
        cls.admin = mk('admin@x.com', PW, role='admin')
        cls.editor = mk('editor@x.com', PW, role='editor')
        cls.author_user = mk('author@x.com', PW, role='author', first_name='Alice')
        cls.other_author_user = mk('author2@x.com', PW, role='author')
        cls.reader = mk('reader@x.com', PW, role='reader', first_name='Rita')
        cls.profile = Author.objects.create(first_name='Alice', last_name='Kim', email='a@x.com', user=cls.author_user)
        cls.other_profile = Author.objects.create(first_name='Bob', last_name='Lee', email='b@x.com', user=cls.other_author_user)
        cls.plan = MembershipPlan.objects.create(name='Monthly', price=300, duration_days=30)
        cls.premium = Blog.objects.create(title='Secret', text=LONG_TEXT, author=cls.profile,
                                          published_date=date(2026, 1, 1), is_premium=True)
        cls.open = Blog.objects.create(title='Open', text='Free to read ' * 30, author=cls.profile,
                                       published_date=date(2026, 1, 2))

    def setUp(self):
        cache.clear()

    def as_(self, user):
        self.client.force_authenticate(user)

    def callback(self, code=0, amount=300, checkout='ws_CO_B1'):
        cb = {'MerchantRequestID': 'mr', 'CheckoutRequestID': checkout, 'ResultCode': code, 'ResultDesc': 'x'}
        if code == 0:
            cb['CallbackMetadata'] = {'Item': [{'Name': 'Amount', 'Value': amount}, {'Name': 'MpesaReceiptNumber', 'Value': 'REC1'}]}
        self.client.force_authenticate(None)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(CALLBACK, {'Body': {'stkCallback': cb}}, format='json')

    def member(self, user, days=5):
        return Membership.objects.create(user=user, plan=self.plan, status='active',
                                         starts_at=timezone.now(), ends_at=timezone.now() + timedelta(days=days))


class PaywallTests(Base):
    def text_of(self, user, blog=None):
        self.as_(user)
        blog = blog or self.premium
        return self.client.get(f'/api/v1/blogs/{blog.pk}/').json()

    def test_non_members_get_a_teaser_and_a_locked_flag(self):
        data = self.text_of(self.reader)
        self.assertTrue(data['locked'])
        self.assertNotIn('THE FULL SECRET TEXT. ' * 20, data['text'])
        self.assertLessEqual(len(data['text']), 301)
        self.assertTrue(data['text'].endswith('…'))

    def test_list_endpoint_is_also_paywalled(self):
        self.as_(self.reader)
        rows = {r['title']: r for r in self.client.get('/api/v1/blogs/').json()['results']}
        self.assertTrue(rows['Secret']['locked'])
        self.assertLessEqual(len(rows['Secret']['text']), 301)
        self.assertFalse(rows['Open']['locked'])
        self.assertGreater(len(rows['Open']['text']), 300)

    def test_member_reads_everything(self):
        self.member(self.reader)
        data = self.text_of(self.reader)
        self.assertFalse(data['locked'])
        self.assertEqual(data['text'], LONG_TEXT)

    def test_expired_and_pending_memberships_do_not_unlock(self):
        Membership.objects.create(user=self.reader, plan=self.plan, status='active',
                                  starts_at=timezone.now() - timedelta(days=40), ends_at=timezone.now() - timedelta(days=10))
        Membership.objects.create(user=self.reader, plan=self.plan)
        self.assertTrue(self.text_of(self.reader)['locked'])

    def test_author_editor_and_admin_always_read(self):
        for user in (self.author_user, self.editor, self.admin):
            self.assertFalse(self.text_of(user)['locked'], user.role)
        self.assertTrue(self.text_of(self.other_author_user)['locked'], "another author is just a reader here")

    def test_membership_is_looked_up_once_per_request_not_per_post(self):
        for i in range(10):
            Blog.objects.create(title=f'P{i}', text=LONG_TEXT, author=self.profile, published_date=date(2026, 2, 1), is_premium=True)
        self.member(self.reader)
        self.as_(self.reader)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get('/api/v1/blogs/')
        membership_queries = [q for q in ctx.captured_queries if 'blogs_membership' in q['sql']]
        self.assertEqual(len(membership_queries), 1, len(ctx))

    def test_only_editors_and_admins_can_change_the_premium_flag(self):
        self.as_(self.author_user)
        res = self.client.patch(f'/api/v1/blogs/{self.open.pk}/', {'is_premium': True}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('is_premium', res.json())
        self.open.refresh_from_db()
        self.assertFalse(self.open.is_premium)
        # sending the value it already has is fine (a full-form save shouldn't fail)
        ok = self.client.patch(f'/api/v1/blogs/{self.open.pk}/', {'title': 'Open!', 'is_premium': False}, format='json')
        self.assertEqual(ok.status_code, 200)
        self.as_(self.editor)
        res = self.client.patch(f'/api/v1/blogs/{self.open.pk}/', {'is_premium': True}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['is_premium'])

    def test_authors_cannot_create_a_premium_post(self):
        self.as_(self.author_user)
        res = self.client.post('/api/v1/blogs/', {'title': 'T', 'text': 'x', 'author': self.profile.pk,
                                                  'published_date': '2026-03-01', 'is_premium': True}, format='json')
        self.assertEqual(res.status_code, 400)


@override_settings(**MPESA)
class MembershipPurchaseTests(Base):
    def test_plans_are_visible_to_signed_in_users_only(self):
        self.assertEqual(self.client.get('/api/v1/plans/').status_code, 401)
        MembershipPlan.objects.create(name='Hidden', price=1, duration_days=1, is_active=False)
        self.as_(self.reader)
        plans = self.client.get('/api/v1/plans/').json()
        self.assertEqual([p['name'] for p in plans], ['Monthly'])
        self.assertEqual(plans[0]['price'], 300)

    @mock.patch('payments.services.mpesa.stk_push', return_value=stk_ok())
    def test_purchase_flow(self, push):
        self.as_(self.reader)
        res = self.client.post(f'/api/v1/plans/{self.plan.pk}/subscribe/', {'phone': '0712345678'}, format='json')
        self.assertEqual(res.status_code, 202, res.content)
        payment = res.json()['payment']
        self.assertEqual((payment['amount'], payment['purpose'], payment['status']), (300, 'membership', 'pending'))
        self.assertFalse(self.client.get('/api/v1/membership/').json()['active'])

        self.assertEqual(self.callback().status_code, 200)
        self.as_(self.reader)
        info = self.client.get('/api/v1/membership/').json()
        self.assertTrue(info['active'])
        self.assertEqual(info['current']['plan_name'], 'Monthly')
        membership = Membership.objects.get()
        self.assertEqual((membership.ends_at - membership.starts_at).days, 30)
        self.assertFalse(self.client.get(f'/api/v1/blogs/{self.premium.pk}/').json()['locked'])

    @mock.patch('payments.services.mpesa.stk_push', return_value=stk_ok())
    def test_a_cancelled_prompt_grants_nothing(self, push):
        self.as_(self.reader)
        self.client.post(f'/api/v1/plans/{self.plan.pk}/subscribe/', {'phone': '0712345678'}, format='json')
        self.callback(code=1032)
        self.as_(self.reader)
        self.assertFalse(self.client.get('/api/v1/membership/').json()['active'])
        self.assertEqual(Membership.objects.get().status, 'pending')

    def test_early_renewal_starts_when_the_current_period_ends(self):
        current = self.member(self.reader, days=25)
        renewal = Membership.objects.create(user=self.reader, plan=self.plan)
        renewal.activate()
        self.assertEqual(renewal.starts_at, current.ends_at)
        self.assertEqual(renewal.ends_at, current.ends_at + timedelta(days=30))

    def test_callback_before_the_link_is_saved_still_activates(self):
        membership = Membership.objects.create(user=self.reader, plan=self.plan)
        Payment.objects.create(user=self.reader, phone='254712345678', amount=300, purpose='membership',
                               account_reference=f'MEM-{membership.pk}', checkout_request_id='ws_CO_B1')
        self.callback()
        membership.refresh_from_db()
        self.assertEqual(membership.status, 'active')

    def test_validation_and_auth(self):
        url = f'/api/v1/plans/{self.plan.pk}/subscribe/'
        self.assertEqual(self.client.post(url, {'phone': '0712345678'}, format='json').status_code, 401)
        self.as_(self.reader)
        self.assertEqual(self.client.post(url, {}, format='json').status_code, 400)
        res = self.client.post(url, {'phone': '123'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('valid Safaricom number', res.json()['detail'])
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_inactive_plans_cannot_be_bought(self):
        self.plan.is_active = False
        self.plan.save()
        self.as_(self.reader)
        self.assertEqual(self.client.post(f'/api/v1/plans/{self.plan.pk}/subscribe/', {'phone': '0712345678'}, format='json').status_code, 404)


@override_settings(**MPESA)
class TipTests(Base):
    @mock.patch('payments.services.mpesa.stk_push', return_value=stk_ok())
    def test_tip_flow_updates_the_posts_totals(self, push):
        self.as_(self.reader)
        res = self.client.post(f'/api/v1/blogs/{self.open.pk}/tip/',
                               {'amount': 150, 'phone': '0712345678', 'message': 'Great read'}, format='json')
        self.assertEqual(res.status_code, 202, res.content)
        self.assertEqual(res.json()['payment']['purpose'], 'tip')
        tip = Tip.objects.get()
        self.assertEqual((tip.author, tip.tipper, tip.amount, tip.status), (self.profile, self.reader, 150, 'pending'))
        self.assertEqual(self.client.get(f'/api/v1/blogs/{self.open.pk}/').json()['tips_total'], 0)

        self.callback(amount=150)
        self.as_(self.reader)
        data = self.client.get(f'/api/v1/blogs/{self.open.pk}/').json()
        self.assertEqual((data['tips_total'], data['tips_count']), (150, 1))
        tip.refresh_from_db()
        self.assertEqual(tip.status, 'paid')

    @mock.patch('payments.services.mpesa.stk_push', return_value=stk_ok())
    def test_failed_tip_is_not_counted(self, push):
        self.as_(self.reader)
        self.client.post(f'/api/v1/blogs/{self.open.pk}/tip/', {'amount': 100, 'phone': '0712345678'}, format='json')
        self.callback(code=1032)
        self.as_(self.reader)
        self.assertEqual(self.client.get(f'/api/v1/blogs/{self.open.pk}/').json()['tips_total'], 0)
        self.assertEqual(Tip.objects.get().status, 'pending')

    def test_cannot_tip_yourself(self):
        self.as_(self.author_user)
        res = self.client.post(f'/api/v1/blogs/{self.open.pk}/tip/', {'amount': 100, 'phone': '0712345678'}, format='json')
        self.assertEqual(res.status_code, 409)
        self.assertIn('tip yourself', res.json()['detail'])
        self.assertEqual(Payment.objects.count(), 0)

    def test_amount_limits_phone_validation_and_auth(self):
        url = f'/api/v1/blogs/{self.open.pk}/tip/'
        self.assertEqual(self.client.post(url, {'amount': 100, 'phone': '0712345678'}, format='json').status_code, 401)
        self.as_(self.reader)
        for bad in ({'amount': 5, 'phone': '0712345678'}, {'amount': 999999, 'phone': '0712345678'},
                    {'amount': 'abc', 'phone': '0712345678'}, {'phone': '0712345678'}, {'amount': 100}):
            self.assertEqual(self.client.post(url, bad, format='json').status_code, 400, bad)
        res = self.client.post(url, {'amount': 100, 'phone': '123'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual((Payment.objects.count(), Tip.objects.count()), (0, 0))
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_tips_are_rate_limited(self):
        self.as_(self.author_user)   # tipping yourself fails fast (409) but still counts toward the limit
        url = f'/api/v1/blogs/{self.open.pk}/tip/'
        for _ in range(20):
            self.client.post(url, {'amount': 100, 'phone': '0712345678'}, format='json')
        self.assertEqual(self.client.post(url, {'amount': 100, 'phone': '0712345678'}, format='json').status_code, 429)


class EarningsTests(Base):
    def setUp(self):
        super().setUp()
        other_post = Blog.objects.create(title='Bob post', text='x' * 50, author=self.other_profile, published_date=date(2026, 1, 3))
        for blog, amount, who, msg in ((self.open, 100, self.reader, 'nice'), (self.open, 50, self.editor, ''),
                                       (other_post, 500, self.reader, 'for bob')):
            Tip.objects.create(blog=blog, author=blog.author, tipper=who, amount=amount, message=msg, status='paid')
        Tip.objects.create(blog=self.open, author=self.profile, tipper=self.reader, amount=999, status='pending')

    def test_author_sees_only_their_own_paid_tips(self):
        self.as_(self.author_user)
        data = self.client.get('/api/v1/earnings/').json()
        self.assertEqual((data['total'], data['count']), (150, 2))
        self.assertEqual(data['by_blog'][0], {'blog': self.open.pk, 'title': 'Open', 'total': 150, 'count': 2})
        self.assertEqual({r['message'] for r in data['recent']}, {'nice', ''})

    def test_editors_and_admins_see_everything(self):
        for user in (self.editor, self.admin):
            self.as_(user)
            self.assertEqual(self.client.get('/api/v1/earnings/').json()['total'], 650)

    def test_supporters_are_identified_by_first_name_only(self):
        self.as_(self.author_user)
        sources = {r['from'] for r in self.client.get('/api/v1/earnings/').json()['recent']}
        self.assertEqual(sources, {'Rita', 'A reader'})
        self.assertNotIn('reader@x.com', str(self.client.get('/api/v1/earnings/').content))

    def test_readers_and_anonymous_are_refused(self):
        self.assertEqual(self.client.get('/api/v1/earnings/').status_code, 401)
        self.as_(self.reader)
        self.assertEqual(self.client.get('/api/v1/earnings/').status_code, 403)


@override_settings(**MPESA)
class NoDuplicatesOrOrphansTests(Base):
    @mock.patch('payments.services.mpesa.stk_push', return_value=stk_ok())
    def test_double_clicking_a_tip_sends_one_prompt_and_makes_one_tip(self, push):
        self.as_(self.reader)
        url = f'/api/v1/blogs/{self.open.pk}/tip/'
        first = self.client.post(url, {'amount': 100, 'phone': '0712345678'}, format='json').json()['payment']['id']
        second = self.client.post(url, {'amount': 100, 'phone': '0712345678'}, format='json').json()['payment']['id']
        self.assertEqual(first, second)
        self.assertEqual((push.call_count, Tip.objects.count()), (1, 1))

    @mock.patch('payments.services.mpesa.stk_push', return_value=stk_ok())
    def test_a_different_amount_is_a_new_tip(self, push):
        self.as_(self.reader)
        url = f'/api/v1/blogs/{self.open.pk}/tip/'
        self.client.post(url, {'amount': 100, 'phone': '0712345678'}, format='json')
        with mock.patch('payments.services.mpesa.stk_push', return_value=stk_ok('ws_CO_B2')):
            res = self.client.post(url, {'amount': 200, 'phone': '0712345678'}, format='json')
        self.assertEqual(res.status_code, 202)
        self.assertEqual(Tip.objects.count(), 2)

    @mock.patch('payments.services.mpesa.stk_push', return_value=stk_ok())
    def test_double_clicking_subscribe_sends_one_prompt(self, push):
        self.as_(self.reader)
        url = f'/api/v1/plans/{self.plan.pk}/subscribe/'
        a = self.client.post(url, {'phone': '0712345678'}, format='json').json()['payment']['id']
        b = self.client.post(url, {'phone': '0712345678'}, format='json').json()['payment']['id']
        self.assertEqual(a, b)
        self.assertEqual((push.call_count, Membership.objects.count()), (1, 1))

    def test_invalid_phone_leaves_no_membership_behind(self):
        self.as_(self.reader)
        self.client.post(f'/api/v1/plans/{self.plan.pk}/subscribe/', {'phone': '123'}, format='json')
        self.assertEqual((Membership.objects.count(), Payment.objects.count()), (0, 0))

    @mock.patch('payments.services.mpesa.stk_push', side_effect=__import__('payments.mpesa', fromlist=['x']).MpesaError('down'))
    def test_daraja_outage_leaves_no_tip_behind_but_keeps_the_failed_payment_record(self, push):
        self.as_(self.reader)
        res = self.client.post(f'/api/v1/blogs/{self.open.pk}/tip/', {'amount': 100, 'phone': '0712345678'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Tip.objects.count(), 0)
        self.assertEqual(Payment.objects.get().status, 'failed')
