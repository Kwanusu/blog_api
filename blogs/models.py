from datetime import timedelta
from django.utils.text import slugify
from cloudinary.models import CloudinaryField
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Author(models.Model):
    # Links an author profile to a login; used for "edit own blogs" permissions.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='author_profile',
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    
  

    class Meta:
        # Review fix C: a default ordering makes paginated author lists deterministic
        # (without it the database may return rows in any order and pages can overlap).
        ordering = ['last_name', 'first_name', 'id']

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

class Blog(models.Model):
    title = models.CharField(max_length=255)
    text = models.TextField()
    author = models.ForeignKey(settings.AUTH_USER_MODEL,
                               on_delete=models.CASCADE,
                               related_name='blogs')
    published_date = models.DateField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    is_published = models.BooleanField(
        default=True,
        help_text='Unpublished posts (drafts) are visible only to their author, editors and admins.',
    )
    slug = models.SlugField(blank=True)
    image = CloudinaryField('image', folder='blogs', null=True, blank=True)
    is_premium = models.BooleanField(default=False, help_text='Only members (and the author) can read the full text.')
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
            
        super().save(*args, **kwargs)  

    def __str__(self):
        return self.title


class MembershipPlan(models.Model):
    """A purchasable period of premium access, priced in whole Kenya shillings."""

    name = models.CharField(max_length=80)
    description = models.CharField(max_length=200, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=0, validators=[MinValueValidator(1)])
    duration_days = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'price']

    def __str__(self):
        return f'{self.name} (KES {self.price:,.0f} / {self.duration_days} days)'


class Membership(models.Model):
    """One purchase of a plan. Active once its M-Pesa payment succeeds."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Awaiting payment'
        ACTIVE = 'active', 'Active'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='memberships')
    plan = models.ForeignKey(MembershipPlan, on_delete=models.PROTECT, related_name='memberships')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    payment = models.OneToOneField(
        'payments.Payment', null=True, blank=True, on_delete=models.SET_NULL, related_name='membership',
    )
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} · {self.plan.name} · {self.get_status_display()}'

    @classmethod
    def current_for(cls, user):
        """The membership granting access right now (the one ending last), or None."""
        if not user.is_authenticated:
            return None
        return (
            cls.objects.filter(user=user, status=cls.Status.ACTIVE, ends_at__gt=timezone.now())
            .select_related('plan').order_by('-ends_at').first()
        )

    def activate(self):
        """Start now — or when the current period ends, so renewing early never wastes paid days."""
        now = timezone.now()
        latest = (
            Membership.objects.filter(user=self.user, status=self.Status.ACTIVE, ends_at__gt=now)
            .exclude(pk=self.pk).order_by('-ends_at').first()
        )
        self.starts_at = latest.ends_at if latest else now
        self.ends_at = self.starts_at + timedelta(days=self.plan.duration_days)
        self.status = self.Status.ACTIVE
        self.save()


class Tip(models.Model):
    """A one-off M-Pesa thank-you from a reader to a post's author."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Awaiting payment'
        PAID = 'paid', 'Received'

    blog = models.ForeignKey(Blog, null=True, on_delete=models.SET_NULL, related_name='tips')
    author = models.ForeignKey(Author, null=True, on_delete=models.SET_NULL, related_name='tips')
    tipper = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='tips_given')
    amount = models.DecimalField(max_digits=10, decimal_places=0, validators=[MinValueValidator(1)])
    message = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    payment = models.OneToOneField(
        'payments.Payment', null=True, blank=True, on_delete=models.SET_NULL, related_name='tip',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'KES {self.amount:,.0f} for {self.blog or "a deleted post"}'
