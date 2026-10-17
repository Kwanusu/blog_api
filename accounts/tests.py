from datetime import date

from rest_framework.test import APITestCase

from blogs.models import Author, Blog

from .models import User


class RBACTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        mk = User.objects.create_user
        cls.admin = mk('admin1@x.com', 'pw-Strong-123', role=User.Role.ADMIN)
        cls.editor = mk('editor1@x.com', 'pw-Strong-123', role=User.Role.EDITOR)
        cls.author_user = mk('author1@x.com', 'pw-Strong-123', role=User.Role.AUTHOR)
        cls.other_user = mk('author2@x.com', 'pw-Strong-123', role=User.Role.AUTHOR)
        cls.reader = mk('reader1@x.com', 'pw-Strong-123')

        cls.author = Author.objects.create(
            first_name='A', last_name='One', email='a1@x.com', user=cls.author_user)
        cls.other_author = Author.objects.create(
            first_name='B', last_name='Two', email='b2@x.com', user=cls.other_user)
        cls.blog = Blog.objects.create(
            title='Mine', text='t', author=cls.author, published_date=date(2026, 1, 1))
        cls.other_blog = Blog.objects.create(
            title='Theirs', text='t', author=cls.other_author, published_date=date(2026, 1, 1))

    def payload(self, author):
        return {'title': 'New', 'text': 'body', 'author': author.id,
                'published_date': '2026-02-01'}

    def test_defaults_and_superuser_role(self):
        self.assertEqual(self.reader.role, User.Role.READER)
        su = User.objects.create_superuser('root@x.com', 'pw-Strong-123')
        self.assertEqual(su.role, User.Role.ADMIN)

    def test_anonymous_denied(self):
        self.assertEqual(self.client.get('/api/v1/blogs/').status_code, 401)

    def test_reader_read_only(self):
        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get('/api/v1/blogs/').status_code, 200)
        r = self.client.post('/api/v1/blogs/', self.payload(self.author))
        self.assertEqual(r.status_code, 403)

    def test_author_can_create_and_edit_own_only(self):
        self.client.force_authenticate(self.author_user)
        self.assertEqual(
            self.client.post('/api/v1/blogs/', self.payload(self.author)).status_code, 201)
        self.assertEqual(
            self.client.post('/api/v1/blogs/', self.payload(self.other_author)).status_code, 400)
        self.assertEqual(
            self.client.patch(f'/api/v1/blogs/{self.blog.id}/', {'title': 'x'}).status_code, 200)
        self.assertEqual(
            self.client.patch(f'/api/v1/blogs/{self.other_blog.id}/', {'title': 'x'}).status_code, 403)
        self.assertEqual(self.client.delete(f'/api/v1/blogs/{self.blog.id}/').status_code, 403)

    def test_editor_edits_any_but_cannot_delete(self):
        self.client.force_authenticate(self.editor)
        self.assertEqual(
            self.client.patch(f'/api/v1/blogs/{self.other_blog.id}/', {'title': 'x'}).status_code, 200)
        self.assertEqual(self.client.delete(f'/api/v1/blogs/{self.other_blog.id}/').status_code, 403)

    def test_admin_can_delete(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.delete(f'/api/v1/blogs/{self.blog.id}/').status_code, 204)

    def test_author_endpoint_write_needs_editor(self):
        data = {'first_name': 'N', 'last_name': 'M', 'email': 'nm@x.com'}
        self.client.force_authenticate(self.author_user)
        self.assertEqual(self.client.post('/api/v1/authors/', data).status_code, 403)
        self.client.force_authenticate(self.editor)
        self.assertEqual(self.client.post('/api/v1/authors/', data).status_code, 201)

    def test_register_ignores_role(self):
        r = self.client.post('/api/auth/register/', {
            'email': 's@x.com', 'password': 'pw-Strong-123',
            'role': 'admin'})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(User.objects.get(email='s@x.com').role, User.Role.READER)

    def test_only_admin_changes_roles(self):
        url = f'/api/v1/users/{self.reader.id}/'
        self.client.force_authenticate(self.editor)
        self.assertEqual(self.client.patch(url, {'role': 'editor'}).status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.patch(url, {'role': 'editor'}).status_code, 200)
        self.reader.refresh_from_db()
        self.assertEqual(self.reader.role, User.Role.EDITOR)

    def test_me_and_jwt_login(self):
        r = self.client.post('/api/token/', {'email': 'reader1@x.com', 'password': 'pw-Strong-123'})
        self.assertEqual(r.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        me = self.client.get('/api/auth/me/')
        self.assertEqual(me.data['role'], 'reader')


class PasswordFlowTests(APITestCase):
    OLD = 'old-Strong-123'
    NEW = 'new-Strong-456'

    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # throttle counters live in the cache
        self.user = User.objects.create_user('u@x.com', self.OLD, first_name='Una')

    def _request_link(self, email='u@x.com'):
        from django.core import mail
        r = self.client.post('/api/auth/password/forgot/', {'email': email})
        self.assertEqual(r.status_code, 200)
        return r, mail.outbox

    def _uid_token(self, message):
        from urllib.parse import parse_qs, urlparse
        link = next(l for l in message.body.split() if l.startswith('http'))
        q = parse_qs(urlparse(link).query)
        return q['uid'][0], q['token'][0]

    def test_forgot_sends_email_with_link(self):
        _, outbox = self._request_link()
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0].to, ['u@x.com'])
        uid, token = self._uid_token(outbox[0])
        self.assertTrue(uid and token)

    def test_forgot_is_uniform_for_unknown_email(self):
        known, _ = self._request_link()
        unknown, outbox = self._request_link('nobody@x.com')
        self.assertEqual(known.data, unknown.data)
        self.assertEqual(len(outbox), 1)  # only the known address got mail

    def test_inactive_user_gets_no_email(self):
        self.user.is_active = False
        self.user.save()
        _, outbox = self._request_link()
        self.assertEqual(len(outbox), 0)

    def test_reset_with_valid_token_then_token_is_single_use(self):
        _, outbox = self._request_link()
        uid, token = self._uid_token(outbox[0])
        r = self.client.post('/api/auth/password/reset/',
                             {'uid': uid, 'token': token, 'new_password': self.NEW})
        self.assertEqual(r.status_code, 200, r.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.NEW))
        again = self.client.post('/api/auth/password/reset/',
                                 {'uid': uid, 'token': token, 'new_password': 'third-Strong-789'})
        self.assertEqual(again.status_code, 400)
        login = self.client.post('/api/token/', {'email': 'u@x.com', 'password': self.NEW})
        self.assertEqual(login.status_code, 200)

    def test_reset_rejects_bad_token_and_weak_password(self):
        _, outbox = self._request_link()
        uid, token = self._uid_token(outbox[0])
        r = self.client.post('/api/auth/password/reset/',
                             {'uid': uid, 'token': 'bad-token', 'new_password': self.NEW})
        self.assertEqual(r.status_code, 400)
        r = self.client.post('/api/auth/password/reset/',
                             {'uid': uid, 'token': token, 'new_password': '123'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('new_password', r.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.OLD))

    def test_expired_token_rejected(self):
        from django.test import override_settings
        _, outbox = self._request_link()
        uid, token = self._uid_token(outbox[0])
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            r = self.client.post('/api/auth/password/reset/',
                                 {'uid': uid, 'token': token, 'new_password': self.NEW})
        self.assertEqual(r.status_code, 400)

    def test_forgot_is_rate_limited(self):
        for _ in range(5):
            self.assertEqual(
                self.client.post('/api/auth/password/forgot/', {'email': 'u@x.com'}).status_code, 200)
        self.assertEqual(
            self.client.post('/api/auth/password/forgot/', {'email': 'u@x.com'}).status_code, 429)

    def test_change_password(self):
        url = '/api/auth/password/change/'
        self.assertEqual(self.client.post(url, {}).status_code, 401)
        self.client.force_authenticate(self.user)
        bad = self.client.post(url, {'old_password': 'wrong', 'new_password': self.NEW})
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post(url, {'old_password': self.OLD, 'new_password': self.NEW})
        self.assertEqual(ok.status_code, 200, ok.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.NEW))


class GoogleLoginTests(APITestCase):
    URL = '/api/auth/google/'

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _post(self, claims=None, error=None, client_id='test-client-id'):
        from unittest import mock
        from django.test import override_settings
        patch = mock.patch(
            'accounts.google.id_token.verify_oauth2_token',
            side_effect=error, return_value=claims,
        )
        with override_settings(GOOGLE_CLIENT_ID=client_id), patch as m:
            r = self.client.post(self.URL, {'id_token': 'fake'})
        return r, m

    def claims(self, **kw):
        base = {'email': 'new@gmail.com', 'email_verified': True,
                'given_name': 'New', 'family_name': 'Person'}
        base.update(kw)
        return base

    def test_signup_creates_reader_and_returns_jwt(self):
        r, m = self._post(self.claims())
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['created'])
        self.assertEqual(m.call_args.args[2], 'test-client-id')  # audience enforced
        user = User.objects.get(email='new@gmail.com')
        self.assertEqual(user.role, User.Role.READER)
        self.assertFalse(user.has_usable_password())
        self.assertEqual((user.first_name, user.last_name), ('New', 'Person'))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        self.assertEqual(self.client.get('/api/auth/me/').data['email'], 'new@gmail.com')

    def test_existing_user_is_logged_in_keeping_role(self):
        User.objects.create_user('new@gmail.com', 'pw-Strong-123', role=User.Role.EDITOR)
        r, _ = self._post(self.claims(email='New@Gmail.com'))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['created'])
        self.assertEqual(r.data['user']['role'], 'editor')
        self.assertEqual(User.objects.count(), 1)

    def test_invalid_token_rejected(self):
        r, _ = self._post(error=ValueError('bad'))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_unverified_email_rejected(self):
        r, _ = self._post(self.claims(email_verified=False))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_inactive_user_blocked(self):
        u = User.objects.create_user('new@gmail.com', 'pw-Strong-123')
        u.is_active = False
        u.save()
        r, _ = self._post(self.claims())
        self.assertEqual(r.status_code, 403)

    def test_not_configured(self):
        r, _ = self._post(self.claims(), client_id='')
        self.assertEqual(r.status_code, 503)


class ApiProtectionTests(APITestCase):
    # Views that are intentionally reachable without a token.
    PUBLIC_VIEWS = {
        'RegisterView', 'ForgotPasswordView', 'ResetPasswordView',
        'GoogleLoginView', 'LoginView', 'RefreshView',
        'MpesaCallbackView',   # Safaricom has no token; the secret in its URL is the gate
        # API docs: open only while DEBUG is on; staff-only otherwise (SPECTACULAR_SETTINGS['SERVE_PERMISSIONS']).
        'SpectacularAPIView', 'SpectacularSwaggerView',
    }

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _api_views(self):
        from django.urls import get_resolver
        from rest_framework.views import APIView

        found = {}

        def walk(patterns):
            for p in patterns:
                if hasattr(p, 'url_patterns'):
                    walk(p.url_patterns)
                    continue
                cls = getattr(p.callback, 'cls', None) or getattr(p.callback, 'view_class', None)
                if cls and issubclass(cls, APIView):
                    found[cls.__name__] = cls

        walk(get_resolver().url_patterns)
        return found

    def test_deny_by_default(self):
        from django.conf import settings
        self.assertEqual(
            settings.REST_FRAMEWORK['DEFAULT_PERMISSION_CLASSES'],
            ['rest_framework.permissions.IsAuthenticated'],
        )

    def test_only_allowlisted_views_are_public(self):
        from rest_framework.permissions import AllowAny
        public = {
            name for name, cls in self._api_views().items()
            if not cls.permission_classes or AllowAny in cls.permission_classes
        }
        self.assertEqual(public - self.PUBLIC_VIEWS, set(),
                         'These views are public but not on the allowlist')

    def test_anonymous_cannot_read_protected_endpoints(self):
        for path in ('/api/', '/api/v1/', '/api/v1/blogs/', '/api/v1/authors/',
                     '/api/v1/users/', '/api/auth/me/', '/api/courses/',
                     '/api/students/', '/api/teachers/', '/api/enrollments/',
                     '/api/departments/'):
            self.assertEqual(self.client.get(path).status_code, 401, path)

    def test_logout_blacklists_refresh_token(self):
        User.objects.create_user('l@x.com', 'pw-Strong-123')
        tokens = self.client.post('/api/token/', {'email': 'l@x.com', 'password': 'pw-Strong-123'}).data
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(self.client.post('/api/auth/logout/', {'refresh': tokens['refresh']}).status_code, 204)
        self.client.credentials()
        r = self.client.post('/api/token/refresh/', {'refresh': tokens['refresh']})
        self.assertEqual(r.status_code, 401)

    def test_logout_requires_auth_and_valid_token(self):
        self.assertEqual(self.client.post('/api/auth/logout/', {'refresh': 'x'}).status_code, 401)
        user = User.objects.create_user('l2@x.com', 'pw-Strong-123')
        self.client.force_authenticate(user)
        self.assertEqual(self.client.post('/api/auth/logout/', {'refresh': 'garbage'}).status_code, 400)
        self.assertEqual(self.client.post('/api/auth/logout/', {}).status_code, 400)

    def test_refresh_rotates_and_old_token_is_dead(self):
        User.objects.create_user('r@x.com', 'pw-Strong-123')
        old = self.client.post('/api/token/', {'email': 'r@x.com', 'password': 'pw-Strong-123'}).data['refresh']
        new = self.client.post('/api/token/refresh/', {'refresh': old})
        self.assertEqual(new.status_code, 200)
        self.assertNotEqual(new.data['refresh'], old)
        self.assertEqual(self.client.post('/api/token/refresh/', {'refresh': old}).status_code, 401)

    def test_login_is_throttled(self):
        for _ in range(10):
            self.client.post('/api/token/', {'email': 'nobody@x.com', 'password': 'wrong'})
        r = self.client.post('/api/token/', {'email': 'nobody@x.com', 'password': 'wrong'})
        self.assertEqual(r.status_code, 429)

    def test_wrong_password_rejected(self):
        User.objects.create_user('w@x.com', 'pw-Strong-123')
        r = self.client.post('/api/token/', {'email': 'w@x.com', 'password': 'nope'})
        self.assertEqual(r.status_code, 401)
