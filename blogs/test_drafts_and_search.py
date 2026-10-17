"""
Regression tests for code-review items A2 (drafts) and A3 (search must not leak premium text),
plus the new filters and the default author ordering.
"""
from datetime import date

from django.core.cache import cache
from rest_framework.test import APITestCase

from accounts.models import User
from blogs.models import Author, Blog

PW = 'pw-Strong-123'


class DraftVisibilityTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        mk = User.objects.create_user
        cls.admin = mk('admin@x.com', PW, role='admin')
        cls.editor = mk('editor@x.com', PW, role='editor')
        cls.author_user = mk('author@x.com', PW, role='author')
        cls.other_author_user = mk('author2@x.com', PW, role='author')
        cls.reader = mk('reader@x.com', PW)
        cls.profile = Author.objects.create(first_name='A', last_name='One', email='a@x.com', user=cls.author_user)
        cls.other_profile = Author.objects.create(first_name='B', last_name='Two', email='b@x.com', user=cls.other_author_user)
        make = lambda title, author, published: Blog.objects.create(  # noqa: E731
            title=title, text='body ' * 20, author=author, published_date=date(2026, 1, 1), is_published=published)
        cls.live = make('Live', cls.profile, True)
        cls.my_draft = make('My draft', cls.profile, False)
        cls.their_draft = make('Their draft', cls.other_profile, False)

    def setUp(self):
        cache.clear()

    def titles(self, user):
        self.client.force_authenticate(user)
        return {b['title'] for b in self.client.get('/api/v1/blogs/').data['results']}

    def test_readers_see_only_published_posts(self):
        self.assertEqual(self.titles(self.reader), {'Live'})

    def test_authors_see_published_plus_their_own_drafts(self):
        self.assertEqual(self.titles(self.author_user), {'Live', 'My draft'})

    def test_editors_and_admins_see_every_draft(self):
        everything = {'Live', 'My draft', 'Their draft'}
        self.assertEqual(self.titles(self.editor), everything)
        self.assertEqual(self.titles(self.admin), everything)

    def test_a_hidden_draft_is_a_404_not_just_missing_from_the_list(self):
        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get(f'/api/v1/blogs/{self.my_draft.pk}/').status_code, 404)
        self.assertEqual(
            self.client.post(f'/api/v1/blogs/{self.my_draft.pk}/tip/', {'amount': 50, 'phone': '0712345678'}).status_code,
            404,
        )

    def test_an_author_cannot_open_another_authors_draft(self):
        self.client.force_authenticate(self.author_user)
        self.assertEqual(self.client.get(f'/api/v1/blogs/{self.their_draft.pk}/').status_code, 404)

    def test_is_published_is_exposed_and_writable_by_the_owner(self):
        self.client.force_authenticate(self.author_user)
        self.assertFalse(self.client.get(f'/api/v1/blogs/{self.my_draft.pk}/').data['is_published'])
        res = self.client.patch(f'/api/v1/blogs/{self.my_draft.pk}/', {'is_published': True})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.titles(self.reader), {'Live', 'My draft'})

    def test_a_new_post_is_published_by_default_and_a_draft_is_opt_in(self):
        self.client.force_authenticate(self.author_user)
        base = {'title': 'N', 'text': 't', 'author': self.profile.id, 'published_date': '2026-02-01'}
        self.assertTrue(self.client.post('/api/v1/blogs/', base).data['is_published'])
        self.assertFalse(self.client.post('/api/v1/blogs/', {**base, 'is_published': False}).data['is_published'])


class SearchAndFilterTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reader = User.objects.create_user('reader@x.com', PW)
        cls.profile = Author.objects.create(first_name='Wanjiru', last_name='Kamau', email='w@x.com')
        cls.premium = Blog.objects.create(
            title='Members only', text='the hidden word is zanzibar', author=cls.profile,
            published_date=date(2026, 1, 1), is_premium=True)
        cls.open = Blog.objects.create(
            title='Open post', text='nothing special', author=cls.profile, published_date=date(2026, 1, 2))

    def setUp(self):
        cache.clear()
        self.client.force_authenticate(self.reader)

    def count(self, query):
        return self.client.get(f'/api/v1/blogs/?{query}').data['count']

    def test_search_cannot_reveal_words_inside_premium_text(self):
        self.assertEqual(self.count('search=zanzibar'), 0)

    def test_search_still_matches_title_and_author_name(self):
        self.assertEqual(self.count('search=Members'), 1)
        self.assertEqual(self.count('search=Wanjiru'), 2)

    def test_filter_by_premium_flag(self):
        self.assertEqual(self.count('is_premium=true'), 1)
        self.assertEqual(self.count('is_premium=false'), 1)

    def test_authors_are_listed_in_a_stable_order(self):
        Author.objects.create(first_name='Amina', last_name='Abdi', email='a@x.com')
        names = [a['last_name'] for a in self.client.get('/api/v1/authors/').data['results']]
        self.assertEqual(names, sorted(names))
