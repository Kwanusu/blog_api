"""
Location API (create, list, read, update and delete places) with Google Geocoding.

Review history (items A4 and B7)
--------------------------------
* The first-lesson M-Pesa views (``/api/pay/`` and ``/api/pay/callback/``) were removed from this module.
  They could not work (the callback demanded a JWT, so Safaricom got ``401``) and are fully replaced by
  the ``payments`` app. The original code is kept for study in ``docs/lessons/mpesa_first_version.md``.
* Access is now restricted: anyone signed in may *read* locations, but only editors and admins may
  create, change or delete them (previously any signed-in reader could, and spend the Google quota).
* Calls to Google have a timeout, failures are logged (no ``print``), and settings are read from
  ``django.conf.settings`` instead of importing the settings module directly.
* ``GET`` no longer writes to the database; the old "heal missing coordinates on read" side effect was removed.
* Duplicate address-parsing code was collapsed into ``_components_from``.
"""
import logging

import requests
from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from accounts.permissions import ReadOnlyOrEditor

from .models import Location
from .serializers import LocationSerializer
from .throttles import GeocodingThrottle

logger = logging.getLogger(__name__)

GEOCODE_URL = 'https://maps.googleapis.com/maps/api/geocode/json'
GEOCODE_TIMEOUT = 10   # seconds; a slow Google must not tie up a worker indefinitely


def _geocode(**params):
    """
    Call Google's Geocoding API and return the first result, or ``None`` if nothing was found or
    Google could not be reached. Pass ``address=...`` (forward) or ``latlng=...`` (reverse).
    """
    try:
        response = requests.get(
            GEOCODE_URL,
            params={**params, 'key': settings.GOOGLE_MAPS_API_KEY},
            timeout=GEOCODE_TIMEOUT,
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning('Geocoding request failed: %s', exc)
        return None
    if data.get('status') == 'OK' and data.get('results'):
        return data['results'][0]
    return None


def fetch_address_details(address):
    """Forward geocoding: address text -> Google result (coordinates and components)."""
    return _geocode(address=address)


def fetch_geocode_details(latitude, longitude):
    """Reverse geocoding: coordinates -> Google result (formatted address and components)."""
    return _geocode(latlng=f'{latitude},{longitude}')


def _components_from(result, town='', county='', country=''):
    """
    Pull town, county and country out of a Google result. Values already supplied by the caller win,
    so a client that sends its own ``town`` is never overwritten.
    """
    for component in result.get('address_components', []):
        types = component.get('types', [])
        if 'locality' in types and not town:
            town = component.get('long_name', '')
        elif 'administrative_area_level_1' in types and not county:
            county = component.get('long_name', '')
        elif 'country' in types and not country:
            country = component.get('long_name', '')
    return town, county, country


def _bad_request(message):
    return Response({'error': message}, status=status.HTTP_400_BAD_REQUEST)


def _parse_coordinates(latitude, longitude):
    """Return ``(lat, lng, error_message)``; ``error_message`` is ``None`` when the pair is valid."""
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None, None, 'Latitude and longitude must be valid numbers.'
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None, None, 'Latitude or longitude is outside the valid range.'
    return latitude, longitude, None


# Explicit operation ids keep the generated API docs unambiguous (list vs. read-one both used to be "locations_retrieve").
@extend_schema(methods=['GET'], operation_id='locations_list', responses=LocationSerializer(many=True))
@extend_schema(methods=['POST'], operation_id='locations_create', request=LocationSerializer, responses=LocationSerializer)
@api_view(['GET', 'POST'])
@permission_classes([ReadOnlyOrEditor])
@throttle_classes([GeocodingThrottle])
def location_list_create_api_view(request):
    if request.method == 'GET':
        # Ordered and paginated like every other list in the API (review fix B7); the old version
        # returned every row in one response.
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(Location.objects.order_by('id'), request)
        return paginator.get_paginated_response(LocationSerializer(page, many=True).data)

    address = request.data.get('address')
    latitude = request.data.get('latitude')
    longitude = request.data.get('longitude')
    town = request.data.get('town', '')
    county = request.data.get('county', '')
    country = request.data.get('country', '')

    if not address and (latitude is None or longitude is None):
        return _bad_request('Provide an address or both latitude and longitude.')

    if latitude is not None and longitude is not None:
        # Coordinates supplied: validate them, and geocode only if some detail is still missing.
        latitude, longitude, error = _parse_coordinates(latitude, longitude)
        if error:
            return _bad_request(error)
        if not all([town, county, country, address]):
            details = fetch_geocode_details(latitude, longitude)
            if not details:
                return _bad_request('Could not retrieve location details from Google Maps.')
            address = address or details.get('formatted_address', '')
            town, county, country = _components_from(details, town, county, country)
    else:
        # Address only: look up its coordinates and components.
        details = fetch_address_details(address)
        if not details:
            return _bad_request('Address not found or Google Maps API request failed.')
        coordinates = details.get('geometry', {}).get('location', {})
        latitude, longitude = coordinates.get('lat'), coordinates.get('lng')
        town, county, country = _components_from(details, town, county, country)

    serializer = LocationSerializer(data={
        'address': address, 'latitude': latitude, 'longitude': longitude,
        'town': town, 'county': county, 'country': country,
    })
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(request=LocationSerializer, responses=LocationSerializer)
@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([ReadOnlyOrEditor])
@throttle_classes([GeocodingThrottle])
def location_retrieve_update_delete_api_view(request, pk):
    try:
        location = Location.objects.get(pk=pk)
    except Location.DoesNotExist:
        return Response({'error': 'Location not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(LocationSerializer(location).data)

    if request.method == 'DELETE':
        location.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # PUT: re-geocode from the new address, or from new coordinates.
    address = request.data.get('address', '')
    latitude = request.data.get('latitude')
    longitude = request.data.get('longitude')
    has_coordinates = latitude is not None and longitude is not None   # 0 is a valid coordinate

    if not address and not has_coordinates:
        return _bad_request('Address or Latitude and Longitude parameters are required.')

    if address:
        details = fetch_address_details(address)
        if not details:
            return _bad_request('Location not found or API request error.')
        coordinates = details.get('geometry', {}).get('location', {})
        latitude, longitude = coordinates.get('lat'), coordinates.get('lng')
    else:
        latitude, longitude, error = _parse_coordinates(latitude, longitude)
        if error:
            return _bad_request(error)
        details = fetch_geocode_details(latitude, longitude)
        if not details:
            return _bad_request('Location not found or API request error.')
        address = details.get('formatted_address', '')

    town, county, country = _components_from(details)
    if not address and not town:
        return _bad_request('Location not found in geocode details.')

    location.address = address
    location.latitude, location.longitude = latitude, longitude
    location.town, location.county, location.country = town, county, country
    location.save()
    return Response(LocationSerializer(location).data, status=status.HTTP_200_OK)
