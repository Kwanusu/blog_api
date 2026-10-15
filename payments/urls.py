from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import MpesaCallbackView, PaymentViewSet

app_name = 'payments'

router = SimpleRouter()
router.register(r'', PaymentViewSet, basename='payment')

urlpatterns = [
    path('mpesa/callback/<str:secret>/', MpesaCallbackView.as_view(), name='mpesa_callback'),
    path('', include(router.urls)),
]
