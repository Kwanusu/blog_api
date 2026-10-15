from django.conf import settings
from django.db import models


class Payment(models.Model):
    class Purpose(models.TextChoices):
        ENROLLMENT = 'enrollment', 'Course enrollment'
        MEMBERSHIP = 'membership', 'Membership'
        TIP = 'tip', 'Author tip'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Waiting for payment'
        SUCCESS = 'success', 'Paid'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'
        REVIEW = 'review', 'Needs review'   # money moved but the amount didn't match

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='payments',
    )
    phone = models.CharField(max_length=15)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)

    account_reference = models.CharField(max_length=12, blank=True)
    description = models.CharField(max_length=13, blank=True)

    merchant_request_id = models.CharField(max_length=100, blank=True)
    checkout_request_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    mpesa_receipt = models.CharField(max_length=30, blank=True)
    result_code = models.IntegerField(null=True, blank=True)
    result_desc = models.CharField(max_length=255, blank=True)
    callback_payload = models.JSONField(null=True, blank=True)

    checked_at = models.DateTimeField(null=True, blank=True)   # last time we asked Daraja
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'purpose', 'status'])]

    def __str__(self):
        return f'{self.get_purpose_display()} · KES {self.amount_display} · {self.get_status_display()}'

    @property
    def amount_display(self):
        """500.00 -> '500', 12.50 -> '12.5' (no trailing zeros, never scientific notation)."""
        return format(self.amount.normalize(), 'f')

    @property
    def is_pending(self):
        return self.status == self.Status.PENDING

    @property
    def is_success(self):
        return self.status == self.Status.SUCCESS
