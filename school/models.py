
from decimal import Decimal

from cloudinary.models import CloudinaryField
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from blog_api.location import LocationMixin


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Teacher(LocationMixin):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="teacher_profile",
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="teachers",
    )
    # Teachers appear on the map shown to signed-in users only if they opt in.
    show_on_map = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Student(LocationMixin):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_profile",
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    admission_number = models.CharField(max_length=20, unique=True)
    date_of_birth = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return f"{self.admission_number} - {self.first_name} {self.last_name}"

    @classmethod
    def for_user(cls, user):
        """The student profile for a login — created (or claimed from staff-entered data) on first use."""
        profile = cls.objects.filter(user=user).first()
        if profile:
            return profile
        profile = cls.objects.filter(email__iexact=user.email, user__isnull=True).first()
        if profile:
            profile.user = user
            profile.save(update_fields=['user'])
            return profile
        return cls.objects.create(
            user=user,
            email=user.email.lower(),
            first_name=user.first_name or user.email.split('@')[0],
            last_name=user.last_name,
            admission_number=f'WEB-{user.pk:06d}',
        )


class Course(LocationMixin):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, unique=True)
    thumbnail = CloudinaryField('image', folder='course_thumbnails', null=True, blank=True)
    description = models.TextField(blank=True)
    # Whole Kenya shillings (M-Pesa takes no cents). 0 means free.
    fee = models.DecimalField(max_digits=10, decimal_places=0, default=0, validators=[MinValueValidator(0)])
    capacity = models.PositiveIntegerField(null=True, blank=True, help_text='Empty means unlimited seats.')
    start_date = models.DateField(null=True, blank=True)
    venue_name = models.CharField(max_length=120, blank=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="courses",
    )
    teachers = models.ManyToManyField(
        Teacher,
        related_name="courses",
        blank=True,
    )

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def is_free(self):
        return self.fee == 0

    @property
    def taken_seats(self):
        return self.enrollments.filter(status=Enrollment.Status.ACTIVE).count()

    @property
    def seats_left(self):
        if self.capacity is None:
            return None
        return max(self.capacity - self.taken_seats, 0)

    @property
    def is_full(self):
        return self.capacity is not None and self.taken_seats >= self.capacity


class Enrollment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Awaiting payment'
        ACTIVE = 'active', 'Enrolled'
        CANCELLED = 'cancelled', 'Cancelled'

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    enrolled_on = models.DateField(auto_now_add=True)
    grade = models.CharField(max_length=2, blank=True)
    # Enrollments created by staff (and every row that existed before payments) are active; self-service
    # enrolment in a paid course starts as "pending" until its M-Pesa payment succeeds.
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    payment = models.ForeignKey(
        'payments.Payment', null=True, blank=True, on_delete=models.SET_NULL, related_name='enrollments',
    )
    amount_paid = models.DecimalField(max_digits=10, decimal_places=0, default=Decimal('0'))
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course"],
                name="unique_student_course_enrollment",
            )
        ]

    def __str__(self):
        return f"{self.student} - {self.course}"

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    def activate(self, payment=None):
        self.status = self.Status.ACTIVE
        if payment is not None:
            self.payment = payment
            self.amount_paid = payment.amount
            self.paid_at = payment.paid_at or timezone.now()
        self.save()

