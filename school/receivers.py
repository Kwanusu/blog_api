from django.dispatch import receiver

from payments.models import Payment
from payments.signals import payment_finished

from .models import Enrollment


@receiver(payment_finished, dispatch_uid='school_enrollment_payment')
def activate_enrollment_on_payment(sender, payment, **kwargs):
    """
    A successful ENROLLMENT payment activates its enrollment. The enrollment is found from the payment's
    account reference ("ENR-<id>") rather than from Enrollment.payment, because a fast callback can land
    a moment before that link is saved.
    """
    if payment.purpose != Payment.Purpose.ENROLLMENT or not payment.is_success:
        return
    ref = payment.account_reference or ''
    if not ref.startswith('ENR-') or not ref[4:].isdigit():
        return
    enrollment = Enrollment.objects.filter(pk=int(ref[4:])).first()
    if enrollment and not enrollment.is_active:
        enrollment.activate(payment)
