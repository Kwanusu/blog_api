from rest_framework.decorators import api_view
from rest_framework.response import Response
from .mpesa_utils import initiate_stk_push, get_mpesa_access_token
from django.http import Http404
from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework import status
from .models import *
from .serializers import *
from rest_framework.decorators import api_view
from rest_framework.response import Response
import requests
from blog_api.settings import GOOGLE_MAPS_API_KEY

@api_view(['POST'])
def pay_with_mpesa(request):
    phone_number = request.data.get('phone_number') # Format: 2547XXXXXXXX
    amount = request.data.get('amount')
    
    if not phone_number or not amount:
        return Response({"error": "Phone number and amount are required."}, status=400)

    # Initiate payment
    response = initiate_stk_push(
        phone_number=phone_number,
        amount=amount,
        account_reference="Django Shop",
        transaction_desc="Payment for Order #1234"
    )

    return Response(response)

@api_view(['POST'])
def mpesa_callback(request):
    # Safaricom sends the transaction results here asynchronously
    data = request.data
    
    # Examine the ResultCode
    result_code = data.get('Body', {}).get('stkCallback', {}).get('ResultCode')
    
    if result_code == 0:
        # Transaction was successful, parse the receipt and update DB
        print("Payment successful!")
        callback_metadata = data['Body']['stkCallback']['CallbackMetadata']['Item']
        for item in callback_metadata:
            if item['Name'] == 'MpesaReceiptNumber':
                receipt = item.get('Value')
                print(f"Receipt: {receipt}")
    else:
        print("Payment failed or cancelled by user.")

    # Always return a 200 response to Daraja so they stop retrying
    return Response({"ResultCode": 0, "ResultDesc": "Accepted"})



def fetch_address_details(address):
    base_url = 'https://maps.googleapis.com/maps/api/geocode/json'
    api_key = GOOGLE_MAPS_API_KEY 

    params = {
        'address': address,
        'key': api_key
    }

    try:
        response = requests.get(base_url, params=params)
        data = response.json()

        if data['status'] == 'OK':
            return data['results'][0]
        else:
            return None
    except requests.exceptions.RequestException as e:
        return None

def fetch_geocode_details(latitude, longitude):
    base_url = 'https://maps.googleapis.com/maps/api/geocode/json'
    api_key = GOOGLE_MAPS_API_KEY 

    params = {
        'latlng': f'{latitude},{longitude}',
        'key': api_key
    }

    try:
        response = requests.get(base_url, params=params)
        data = response.json()

        if data['status'] == 'OK':
            return data['results'][0]
        else:
            return None
    except requests.exceptions.RequestException as e:
        return None
 
@api_view(['GET', 'POST'])
def location_list_create_api_view(request):
    if request.method == 'GET':
        locations = Location.objects.all()
        serializer = LocationSerializer(locations, many=True)
        return Response(serializer.data)

    address = request.data.get('address')
    latitude = request.data.get('latitude')
    longitude = request.data.get('longitude')

    # Accept supplied location details
    town = request.data.get('town', '')
    county = request.data.get('county', '')
    country = request.data.get('country', '')

    if not address and (latitude is None or longitude is None):
        return Response(
            {
                'error': 'Provide an address or both latitude and longitude.'
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # If coordinates are supplied, use them directly.
    # Geocode only when location details are missing.
    if latitude is not None and longitude is not None:
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            return Response(
                {'error': 'Latitude and longitude must be valid numbers.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return Response(
                {'error': 'Latitude or longitude is outside the valid range.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not all([town, county, country, address]):
            geocode_details = fetch_geocode_details(latitude, longitude)

            if not geocode_details:
                return Response(
                    {'error': 'Could not retrieve location details from Google Maps.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            address = address or geocode_details.get('formatted_address', '')

            for component in geocode_details.get('address_components', []):
                types = component.get('types', [])

                if 'locality' in types and not town:
                    town = component.get('long_name', '')
                elif 'administrative_area_level_1' in types and not county:
                    county = component.get('long_name', '')
                elif 'country' in types and not country:
                    country = component.get('long_name', '')

    else:
        # Address only: look up its coordinates and address components.
        address_details = fetch_address_details(address)

        if not address_details:
            return Response(
                {'error': 'Address not found or Google Maps API request failed.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        coordinates = address_details.get('geometry', {}).get('location', {})
        latitude = coordinates.get('lat')
        longitude = coordinates.get('lng')

        for component in address_details.get('address_components', []):
            types = component.get('types', [])

            if 'locality' in types and not town:
                town = component.get('long_name', '')
            elif 'administrative_area_level_1' in types and not county:
                county = component.get('long_name', '')
            elif 'country' in types and not country:
                country = component.get('long_name', '')

    # Validate and save through the serializer.
    serializer = LocationSerializer(
        data={
            'address': address,
            'latitude': latitude,
            'longitude': longitude,
            'town': town,
            'county': county,
            'country': country,
        },
        context={'request': request}
    )

    if serializer.is_valid():
        serializer.save()
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED
        )

    return Response(
        serializer.errors,
        status=status.HTTP_400_BAD_REQUEST
    )

@api_view(['GET', 'PUT', 'DELETE'])
def location_retrieve_update_delete_api_view(request, pk):
    try:
        location = Location.objects.get(pk=pk)
    except Location.DoesNotExist:
        return Response({'error': 'Location not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        if not location.latitude or not location.longitude:
            address_details = fetch_address_details(location.address)
            if address_details:
                location_data = address_details.get('geometry', {}).get('location', {})
                location.latitude = location_data.get('lat')
                location.longitude = location_data.get('lng')
                address_components = address_details.get('address_components', [])
                for component in address_components:
                    types = component.get('types', [])
                    if 'locality' in types:
                        location.town = component.get('long_name', "")
                    elif 'administrative_area_level_1' in types:
                        location.county = component.get('long_name', "")
                    elif 'country' in types:
                        location.country = component.get('long_name', "")
                location.save()

        serializer = LocationSerializer(location)
        return Response(serializer.data)

    if request.method == 'PUT':
        address = request.data.get('address', '')
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')

        if not address and not (latitude and longitude):
            return Response({'error': 'Address or Latitude and Longitude parameters are required.'}, status=status.HTTP_400_BAD_REQUEST)

        town = ""
        county = ""
        country = ""

        if address:
            address_details = fetch_address_details(address)

            if address_details:
                location_data = address_details.get('geometry', {}).get('location', {})
                latitude = location_data.get('lat')
                longitude = location_data.get('lng')
                address_components = address_details.get('address_components', [])
                for component in address_components:
                    types = component.get('types', [])
                    if 'locality' in types:
                        town = component.get('long_name', "")
                    elif 'administrative_area_level_1' in types:
                        county = component.get('long_name', "")
                    elif 'country' in types:
                        country = component.get('long_name', "")
            else:
                return Response({'error': 'Location not found or API request error.'}, status=status.HTTP_400_BAD_REQUEST)

        elif latitude and longitude:
            geocode_details = fetch_geocode_details(latitude, longitude)

            if geocode_details:
                address = geocode_details.get('formatted_address', "")
                address_components = geocode_details.get('address_components', [])
                for component in address_components:
                    types = component.get('types', [])
                    if 'locality' in types:
                        town = component.get('long_name', "")
                    elif 'administrative_area_level_1' in types:
                        county = component.get('long_name', "")
                    elif 'country' in types:
                        country = component.get('long_name', "")
                if not town:
                    return Response({'error': 'Location not found in geocode details.'}, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({'error': 'Location not found or API request error.'}, status=status.HTTP_400_BAD_REQUEST)

        location.address = address
        location.latitude = latitude
        location.longitude = longitude
        location.town = town
        location.county = county
        location.country = country
        location.save()

        serializer = LocationSerializer(location)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == 'DELETE':
        location.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)