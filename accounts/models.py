from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower


class UserManager(BaseUserManager):
    use_in_migrations = True

    def get_by_natural_key(self, email):
        """
        Look users up by email without regard to letter case.

        Review fix B2: emails are stored lower-cased, but people type them in any case
        (``Ann@Example.com``). Django's default lookup is an exact match, which would make
        such a login fail, so the authentication backend is pointed at a case-insensitive one.
        """
        return self.get(**{f'{self.model.USERNAME_FIELD}__iexact': email})

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError('An email address is required.')
        # normalize_email() only lower-cases the domain; the whole address is lower-cased so
        # "Ann@x.com" and "ann@x.com" can never become two different accounts (review fix B2).
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        if extra_fields['is_staff'] is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields['is_superuser'] is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        EDITOR = 'editor', 'Editor'
        AUTHOR = 'author', 'Author'
        TEACHER = 'teacher', 'Teacher'
        STUDENT = 'student', 'Student'
        READER = 'reader', 'Reader'

    username = None  # email is the login identifier
    email = models.EmailField('email address', unique=True)
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.READER,
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta(AbstractUser.Meta):
        # Review fix B2: database-level guarantee that two emails differing only by case cannot
        # coexist, even if a row is created without going through UserManager (admin, shell, loaddata).
        constraints = [
            models.UniqueConstraint(Lower('email'), name='accounts_user_email_ci_unique'),
        ]

    def save(self, *args, **kwargs):
        # Superusers (e.g. from createsuperuser) always get the admin role.
        if self.is_superuser:
            self.role = self.Role.ADMIN
        if self.email:
            self.email = self.email.lower()   # keep stored emails canonical (review fix B2)
        super().save(*args, **kwargs)

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN

    @property
    def is_editor_role(self):
        return self.role == self.Role.EDITOR

    @property
    def is_author_role(self):
        return self.role == self.Role.AUTHOR

    def __str__(self):
        return f"{self.email} ({self.role})"
