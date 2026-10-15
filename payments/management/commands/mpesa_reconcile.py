from django.core.management.base import BaseCommand

from payments import services
from payments.models import Payment


class Command(BaseCommand):
    help = (
        'Ask Safaricom about pending M-Pesa payments whose callback never arrived. '
        'Run every few minutes (cron / Render cron job).'
    )

    def handle(self, *args, **options):
        pending = Payment.objects.filter(status=Payment.Status.PENDING).exclude(checkout_request_id=None)
        settled = 0
        for payment in pending:
            if not services.reconcile(payment, force=True).is_pending:
                settled += 1
        self.stdout.write(self.style.SUCCESS(f'Checked {pending.count()} pending payment(s); settled {settled}.'))
