from django.dispatch import receiver

from payments.models import Payment
from payments.signals import payment_finished

from .models import Membership, Tip


def _pk_from_reference(payment, prefix):
    ref = payment.account_reference or ''
    return int(ref[len(prefix):]) if ref.startswith(prefix) and ref[len(prefix):].isdigit() else None


@receiver(payment_finished, dispatch_uid='blogs_membership_tip_payment')
def apply_paid_purchases(sender, payment, **kwargs):
    """
    A successful MEMBERSHIP payment starts the membership; a successful TIP payment marks the tip
    received. Objects are found from the payment's account reference ("MEM-<id>" / "TIP-<id>"), not
    from the payment link, because a fast callback can land before that link is saved.
    """
    if not payment.is_success:
        return

    if payment.purpose == Payment.Purpose.MEMBERSHIP:
        pk = _pk_from_reference(payment, 'MEM-')
        membership = Membership.objects.select_related('plan', 'user').filter(pk=pk).first() if pk else None
        if membership and membership.status != Membership.Status.ACTIVE:
            membership.payment = payment
            membership.activate()

    elif payment.purpose == Payment.Purpose.TIP:
        pk = _pk_from_reference(payment, 'TIP-')
        tip = Tip.objects.filter(pk=pk).first() if pk else None
        if tip and tip.status != Tip.Status.PAID:
            tip.payment = payment
            tip.status = Tip.Status.PAID
            tip.save(update_fields=['payment', 'status'])
