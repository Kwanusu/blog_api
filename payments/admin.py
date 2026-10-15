from django.contrib import admin, messages

from . import services
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'user', 'purpose', 'amount', 'phone', 'status', 'mpesa_receipt')
    list_filter = ('status', 'purpose', 'created_at')
    search_fields = ('user__email', 'phone', 'mpesa_receipt', 'checkout_request_id', 'account_reference')
    date_hierarchy = 'created_at'
    actions = ['recheck_with_safaricom']

    def get_readonly_fields(self, request, obj=None):
        # Payments are a financial record: nothing here is editable.
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='Re-check selected pending payments with Safaricom')
    def recheck_with_safaricom(self, request, queryset):
        settled = 0
        for payment in queryset.filter(status=Payment.Status.PENDING):
            if not services.reconcile(payment, force=True).is_pending:
                settled += 1
        self.message_user(request, f'{settled} payment(s) settled.', messages.SUCCESS)
