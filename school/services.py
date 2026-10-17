"""School business rules: enrolling in a course and paying for it."""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.emails import send_teacher_setup_email
from accounts.models import User
from payments import services as payment_services
from payments.models import Payment

from .models import Course, Enrollment, Student


@transaction.atomic
def provision_teacher_account(teacher):
    """Create or attach a teacher login and send a one-time password setup link."""
    if teacher.user_id:
        return teacher.user

    user = User.objects.filter(email__iexact=teacher.email).first()
    if user:
        if user.role != User.Role.TEACHER:
            raise ValueError("This email address already belongs to a non-teacher account.")
        if hasattr(user, "teacher_profile"):
            raise ValueError("This account is already linked to another teacher.")
    else:
        user = User(
            email=teacher.email,
            first_name=teacher.first_name,
            last_name=teacher.last_name,
            role=User.Role.TEACHER,
        )
        user.set_unusable_password()
        user.save()

    teacher.user = user
    teacher.save(update_fields=["user"])
    transaction.on_commit(lambda user=user: send_teacher_setup_email(user))
    return user


class EnrollmentError(Exception):
    """A rule violation worth showing to the user as-is."""


# How long an unpaid M-Pesa prompt keeps a seat reserved. It mirrors payments.services.GIVE_UP_AFTER:
# after that the prompt is treated as timed out, so the seat goes back on sale.
SEAT_HOLD = timedelta(minutes=10)


def seats_in_use(course, *, excluding=None):
    """
    Seats that are unavailable to a new applicant (review fix B3): active enrollments plus
    enrollments whose M-Pesa prompt is still live. Counting the second group closes the gap where
    two people could both be told "pay now" for the last seat and both succeed.
    ``excluding`` lets the applicant's own pending enrollment not block themselves.
    """
    from payments.models import Payment

    held = course.enrollments.filter(
        status=Enrollment.Status.PENDING,
        payment__status=Payment.Status.PENDING,
        payment__created_at__gte=timezone.now() - SEAT_HOLD,
    )
    taken = course.enrollments.filter(status=Enrollment.Status.ACTIVE)
    if excluding is not None:
        held = held.exclude(pk=excluding.pk)
        taken = taken.exclude(pk=excluding.pk)
    return taken.count() + held.count()


def start_enrollment(user, course):
    """
    Get (or create) the user's enrollment in a course. Returns (enrollment, needs_payment).
    Free courses are activated immediately; paid ones wait, pending, for their M-Pesa payment.
    """
    student = Student.for_user(user)
    existing = Enrollment.objects.filter(student=student, course=course).first()
    if existing and existing.is_active:
        raise EnrollmentError('You are already enrolled in this course.')

    with transaction.atomic():
        # Review fix B3: lock the course row so concurrent applicants are checked one at a time.
        # (SQLite ignores row locks; PostgreSQL honours them, which is where this matters.)
        course = Course.objects.select_for_update().get(pk=course.pk)
        if course.capacity is not None and seats_in_use(course, excluding=existing) >= course.capacity:
            raise EnrollmentError('Sorry, this course is full.')

        try:
            enrollment, _ = Enrollment.objects.select_for_update().get_or_create(
                student=student, course=course, defaults={'status': Enrollment.Status.PENDING},
            )
        except IntegrityError:   # a double-submit created it a moment ago
            enrollment = Enrollment.objects.get(student=student, course=course)
        if enrollment.status == Enrollment.Status.CANCELLED:
            enrollment.status = Enrollment.Status.PENDING
            enrollment.save(update_fields=['status'])

        # Signing up for a course makes you a student, which unlocks the student-facing endpoints.
        if user.role == User.Role.READER:
            user.role = User.Role.STUDENT
            user.save(update_fields=['role'])

    if course.is_free:
        enrollment.activate()
        return enrollment, False
    return enrollment, True


def pay_for_enrollment(enrollment, phone):
    """Send the M-Pesa prompt for a pending paid enrollment. Raises PaymentError on failure."""
    if enrollment.is_active:
        raise EnrollmentError('You are already enrolled in this course.')
    payment = payment_services.initiate_stk(
        user=enrollment.student.user,
        phone=phone,
        amount=enrollment.course.fee,
        purpose=Payment.Purpose.ENROLLMENT,
        reference=f'ENR-{enrollment.pk}',
        description='Course fee',
    )
    enrollment.payment = payment
    enrollment.save(update_fields=['payment'])

    student = enrollment.student
    if not student.phone:   # remember the number for next time
        student.phone = payment.phone
        student.save(update_fields=['phone'])
    return payment


def cancel_enrollment(enrollment):
    """Only an enrollment that isn't paid for (and has no prompt in flight) can be cancelled."""
    if enrollment.is_active:
        raise EnrollmentError('Paid enrollments can’t be cancelled here — please contact us.')
    if enrollment.payment_id and enrollment.payment.is_pending:
        raise EnrollmentError('A payment is in progress. Finish or wait for it to expire first.')
    enrollment.status = Enrollment.Status.CANCELLED
    enrollment.save(update_fields=['status'])
