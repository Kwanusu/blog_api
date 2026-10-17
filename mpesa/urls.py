from django.urls import path

from .views import location_list_create_api_view, location_retrieve_update_delete_api_view

# The M-Pesa routes (/api/pay/ and /api/pay/callback/) were removed in the code review (item A4);
# use the `payments` app instead. Only the Location API remains in this app.
urlpatterns = [
    path('locations/', location_list_create_api_view, name='location-list'),
    path('locations/<int:pk>/', location_retrieve_update_delete_api_view, name='location-retrieve'),
    # The original route had no trailing slash. It is kept so existing clients keep working.
    path('locations/<int:pk>', location_retrieve_update_delete_api_view, name='location-retrieve-legacy'),
]
