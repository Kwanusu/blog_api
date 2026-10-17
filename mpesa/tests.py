"""
Tests for the Location API (code-review items A4 and B7). Google is never called: ``requests.get`` is mocked.
"""
from unittest import mock

import requests
from django.core.cache import cache
from rest_framework.test import APITestCase

from accounts.models import User

from .models import Location

PW = 'pw-Strong-123'
GOOGLE = {
    'status': 'OK',
    'results': [{
        'formatted_address': 'Kenyatta Ave, Nairobi, Kenya',
        'geometry': {'location': {'lat': -1.2864, 'lng': 36.8172}},
        'address_components': [
            {'long_name': 'Nairobi', 'types': ['locality']},
            {'long_name': 'Nairobi County', 'types': ['administrative_area_level_1']},
            {'long_name': 'Kenya', 'types': ['country']},
        ],
    }],
}


def google_ok():
    response = mock.Mock()
    response.json.return_value = GOOGLE
    return response


class LocationBase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reader = User.objects.create_user('reader@x.com', PW)
        cls.editor = User.objects.create_user('editor@x.com', PW, role='editor')

    def setUp(self):
        cache.clear()


class LocationPermissionTests(LocationBase):
    def test_anonymous_users_are_refused(self):
        self.assertEqual(self.client.get('/api/locations/').status_code, 401)

    def test_readers_may_read_but_not_write(self):
        place = Location.objects.create(address='Somewhere')
        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get('/api/locations/').status_code, 200)
        self.assertEqual(self.client.get(f'/api/locations/{place.pk}/').status_code, 200)
        with mock.patch('mpesa.views.requests.get') as google:
            self.assertEqual(self.client.post('/api/locations/', {'address': 'x'}, format='json').status_code, 403)
            self.assertEqual(self.client.put(f'/api/locations/{place.pk}/', {'address': 'x'}, format='json').status_code, 403)
            self.assertEqual(self.client.delete(f'/api/locations/{place.pk}/').status_code, 403)
        google.assert_not_called()   # a forbidden request must never cost a Google call
        self.assertTrue(Location.objects.filter(pk=place.pk).exists())

    def test_the_removed_mpesa_routes_are_gone(self):
        self.client.force_authenticate(self.editor)
        self.assertEqual(self.client.post('/api/pay/', {}, format='json').status_code, 404)
        self.assertEqual(self.client.post('/api/pay/callback/', {}, format='json').status_code, 404)


class LocationBehaviourTests(LocationBase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.editor)

    @mock.patch('mpesa.views.requests.get')
    def test_create_from_an_address_geocodes_it_with_a_timeout(self, get):
        get.return_value = google_ok()
        res = self.client.post('/api/locations/', {'address': 'Kenyatta Avenue'}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.data['town'], res.data['county'], res.data['country']),
                         ('Nairobi', 'Nairobi County', 'Kenya'))
        self.assertEqual(get.call_args.kwargs['timeout'], 10)

    @mock.patch('mpesa.views.requests.get')
    def test_create_from_coordinates_fills_in_the_missing_details(self, get):
        get.return_value = google_ok()
        res = self.client.post('/api/locations/', {'latitude': -1.28, 'longitude': 36.81}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data['address'], 'Kenyatta Ave, Nairobi, Kenya')
        self.assertEqual(get.call_args.kwargs['params']['latlng'], '-1.28,36.81')

    @mock.patch('mpesa.views.requests.get')
    def test_a_caller_supplied_town_is_never_overwritten(self, get):
        get.return_value = google_ok()
        res = self.client.post('/api/locations/', {'latitude': 1, 'longitude': 2, 'town': 'Mine'}, format='json')
        self.assertEqual(res.data['town'], 'Mine')

    @mock.patch('mpesa.views.requests.get', side_effect=requests.Timeout('slow'))
    def test_a_google_outage_is_a_clean_400_not_a_crash(self, get):
        res = self.client.post('/api/locations/', {'address': 'Anywhere'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_validation_of_bad_input(self):
        post = lambda body: self.client.post('/api/locations/', body, format='json').status_code  # noqa: E731
        self.assertEqual(post({}), 400)
        self.assertEqual(post({'latitude': 'abc', 'longitude': 1, 'address': 'x', 'town': 't', 'county': 'c', 'country': 'k'}), 400)
        self.assertEqual(post({'latitude': 95, 'longitude': 1, 'address': 'x', 'town': 't', 'county': 'c', 'country': 'k'}), 400)

    @mock.patch('mpesa.views.requests.get')
    def test_zero_is_a_valid_coordinate(self, get):
        res = self.client.post('/api/locations/', {
            'latitude': 0, 'longitude': 0, 'address': 'Null Island', 'town': 'a', 'county': 'b', 'country': 'c',
        }, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        get.assert_not_called()   # nothing was missing, so Google is not asked

    @mock.patch('mpesa.views.requests.get')
    def test_reading_a_location_never_writes_or_calls_google(self, get):
        place = Location.objects.create(address='No pin yet')   # no coordinates
        res = self.client.get(f'/api/locations/{place.pk}/')
        self.assertEqual(res.status_code, 200)
        get.assert_not_called()
        place.refresh_from_db()
        self.assertIsNone(place.latitude)

    @mock.patch('mpesa.views.requests.get')
    def test_update_and_delete(self, get):
        get.return_value = google_ok()
        place = Location.objects.create(address='Old')
        res = self.client.put(f'/api/locations/{place.pk}/', {'address': 'Kenyatta Avenue'}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data['town'], 'Nairobi')
        self.assertEqual(self.client.delete(f'/api/locations/{place.pk}/').status_code, 204)
        self.assertEqual(self.client.get(f'/api/locations/{place.pk}/').status_code, 404)

    def test_the_old_url_without_a_trailing_slash_still_works(self):
        place = Location.objects.create(address='x')
        self.assertEqual(self.client.get(f'/api/locations/{place.pk}').status_code, 200)

    def test_the_list_is_paginated(self):
        Location.objects.bulk_create([Location(address=f'P{i}') for i in range(12)])
        res = self.client.get('/api/locations/').json()
        self.assertEqual(res['count'], 12)
        self.assertEqual(len(res['results']), 10)

    @mock.patch('mpesa.views.requests.get')
    def test_writes_are_rate_limited_but_reads_are_not(self, get):
        get.return_value = google_ok()
        with mock.patch.dict('rest_framework.throttling.UserRateThrottle.THROTTLE_RATES', {'geocoding': '2/hour'}):
            codes = [self.client.post('/api/locations/', {'address': f'a{i}'}, format='json').status_code for i in range(3)]
            self.assertEqual(codes, [201, 201, 429])
            self.assertEqual(self.client.get('/api/locations/').status_code, 200)
