"""Regression tests for code-review items B2 (email case) and the logout ownership fix."""
from django.core.cache import cache
from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User

PW = 'pw-Strong-123'


class EmailCaseTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_emails_are_stored_lower_case(self):
        user = User.objects.create_user('Ann@Example.COM', PW)
        self.assertEqual(user.email, 'ann@example.com')

    def test_registering_the_same_address_in_another_case_is_rejected(self):
        ok = self.client.post('/api/auth/register/', {'email': 'Dup@x.com', 'password': PW})
        again = self.client.post('/api/auth/register/', {'email': 'dup@X.com', 'password': PW})
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(again.status_code, 400)
        self.assertIn('email', again.data)
        self.assertEqual(User.objects.filter(email__iexact='dup@x.com').count(), 1)

    def test_login_ignores_the_case_typed_by_the_user(self):
        User.objects.create_user('ann@x.com', PW)
        res = self.client.post('/api/token/', {'email': 'ANN@X.com', 'password': PW})
        self.assertEqual(res.status_code, 200)

    def test_the_database_itself_refuses_case_duplicates(self):
        User.objects.create_user('ann@x.com', PW)
        # Bypass the manager and serializer on purpose: the constraint is the last line of defence.
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(email='ANN@x.com')])

    def test_forgot_password_finds_the_account_in_any_case(self):
        from django.core import mail
        User.objects.create_user('ann@x.com', PW)
        self.client.post('/api/auth/password/forgot/', {'email': 'Ann@X.com'})
        self.assertEqual(len(mail.outbox), 1)


class LogoutOwnershipTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.alice = User.objects.create_user('alice@x.com', PW)
        self.bob = User.objects.create_user('bob@x.com', PW)

    def test_a_user_cannot_revoke_someone_elses_refresh_token(self):
        bobs_token = str(RefreshToken.for_user(self.bob))
        self.client.force_authenticate(self.alice)
        res = self.client.post('/api/auth/logout/', {'refresh': bobs_token})
        self.assertEqual(res.status_code, 400)
        # Bob's token is still usable.
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post('/api/token/refresh/', {'refresh': bobs_token}).status_code, 200)

    def test_a_user_can_still_log_out_with_their_own_token(self):
        own = str(RefreshToken.for_user(self.alice))
        self.client.force_authenticate(self.alice)
        self.assertEqual(self.client.post('/api/auth/logout/', {'refresh': own}).status_code, 204)
