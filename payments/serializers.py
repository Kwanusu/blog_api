from rest_framework import serializers

from .models import Payment

FRIENDLY = {
    Payment.Status.PENDING: 'Check your phone and enter your M-Pesa PIN to complete the payment.',
    Payment.Status.SUCCESS: 'Payment received. Thank you!',
    Payment.Status.FAILED: 'The payment didn’t go through. You haven’t been charged.',
    Payment.Status.CANCELLED: 'The payment was cancelled on your phone. You haven’t been charged.',
    Payment.Status.REVIEW: 'We received your payment but need to verify it. We’ll be in touch shortly.',
}


class PaymentSerializer(serializers.ModelSerializer):
    purpose_display = serializers.CharField(source='get_purpose_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    amount = serializers.SerializerMethodField()
    pending = serializers.BooleanField(source='is_pending', read_only=True)
    success = serializers.BooleanField(source='is_success', read_only=True)
    message = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            'id', 'purpose', 'purpose_display', 'status', 'status_display', 'pending', 'success',
            'amount', 'phone', 'mpesa_receipt', 'message', 'created_at', 'paid_at',
        ]
        read_only_fields = fields

    def get_amount(self, obj):
        return int(obj.amount)

    def get_message(self, obj):
        return FRIENDLY.get(obj.status, '')
