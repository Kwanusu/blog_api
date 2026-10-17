import hmac
import logging

from django.conf import settings
from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.exceptions import ParseError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Payment
from .serializers import PaymentSerializer

logger = logging.getLogger(__name__)

ACCEPTED = {'ResultCode': 0, 'ResultDesc': 'Accepted'}


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
class MpesaCallbackView(APIView):
    """
    Safaricom posts the STK result here. Deliberately public (Safaricom has no token to send) —
    the shared secret in the URL is the gate, and results apply exactly once. Well-formed bodies
    always get a 200 so Safaricom stops retrying, even for an unknown payment id.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []   # Safaricom's servers must never be rate-limited

    def post(self, request, secret):
        expected = settings.MPESA_CALLBACK_SECRET or 'simulate'
        if not hmac.compare_digest(secret.encode(), expected.encode()):
            raise Http404
        try:
            services.handle_callback(request.data)
        except ValueError:
            raise ParseError('Malformed callback')
        return Response(ACCEPTED)


class PaymentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Your own payments. Retrieving a pending one also checks with Safaricom if the callback is late."""

    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):   # schema generation has no signed-in user
            return Payment.objects.none()
        return Payment.objects.filter(user=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        payment = self.get_object()
        payment = services.reconcile(payment)
        return Response(self.get_serializer(payment).data)
