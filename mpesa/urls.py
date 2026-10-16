from django.urls import path
from .views import pay_with_mpesa, mpesa_callback, location_list_create_api_view, location_retrieve_update_delete_api_view

urlpatterns = [
    path('pay/', pay_with_mpesa, name='pay-mpesa'),
    path('pay/callback/', mpesa_callback, name='mpesa-callback'),
    path('locations/', location_list_create_api_view, name='location-list'),
    path('locations/<int:pk>', location_retrieve_update_delete_api_view, name='location-retrieve'),
]
