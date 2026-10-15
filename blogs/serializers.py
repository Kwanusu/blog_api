from rest_framework import serializers
from blog_api.serializer_fields import CloudinaryImageField
from .models import Author, Blog, Membership, MembershipPlan

PUBLISHERS = ('admin', 'editor')
TEASER_CHARS = 300


class AuthorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Author
        fields = '__all__'


class BlogSerializer(serializers.ModelSerializer):
    author_name = serializers.StringRelatedField(source='author', read_only=True)
    image = CloudinaryImageField(required=False, allow_null=True)
    locked = serializers.SerializerMethodField()
    tips_total = serializers.SerializerMethodField()
    tips_count = serializers.SerializerMethodField()

    class Meta:
        model = Blog
        fields = [
            'id', 'title', 'text', 'author', 'author_name', 'published_date', 'created_at', 'image',
            'is_premium', 'locked', 'tips_total', 'tips_count',
        ]

    # ── paywall ──────────────────────────────────────────────────────────────
    def _viewer_is_member(self):
        """One membership lookup per request, however many posts are serialised."""
        if '_is_member' not in self.context:
            request = self.context.get('request')
            user = getattr(request, 'user', None)
            self.context['_is_member'] = bool(
                user and user.is_authenticated and Membership.current_for(user) is not None
            )
        return self.context['_is_member']

    def _is_locked(self, blog):
        if not blog.is_premium:
            return False
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated):
            return True
        if user.is_superuser or user.role in PUBLISHERS or blog.author.user_id == user.id:
            return False
        return not self._viewer_is_member()

    def get_locked(self, blog):
        return self._is_locked(blog)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if self._is_locked(instance):
            text = instance.text
            data['text'] = text[:TEASER_CHARS].rstrip() + ('…' if len(text) > TEASER_CHARS else '')
        return data

    # ── tips (annotated by the view; falls back to a query for single objects) ─────
    def get_tips_total(self, blog):
        total = getattr(blog, 'tips_total', None)
        if total is None:
            from django.db.models import Sum
            total = blog.tips.filter(status='paid').aggregate(t=Sum('amount'))['t'] or 0
        return int(total)

    def get_tips_count(self, blog):
        count = getattr(blog, 'tips_count', None)
        return blog.tips.filter(status='paid').count() if count is None else count

    # ── validation ───────────────────────────────────────────────────────────
    def validate_author(self, author):
        # Authors may only post/move blogs under their own author profile.
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user and user.is_authenticated and user.role == 'author':
            if author.user_id != user.id:
                raise serializers.ValidationError(
                    "You can only create or edit blogs under your own author profile."
                )
        return author

    def validate(self, attrs):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if 'is_premium' in attrs and user and user.is_authenticated:
            current = self.instance.is_premium if self.instance else False
            can_set = user.is_superuser or user.role in PUBLISHERS
            if attrs['is_premium'] != current and not can_set:
                raise serializers.ValidationError(
                    {'is_premium': 'Only editors and admins can change whether a post is premium.'}
                )
        return attrs


class MembershipPlanSerializer(serializers.ModelSerializer):
    price = serializers.SerializerMethodField()

    class Meta:
        model = MembershipPlan
        fields = ['id', 'name', 'description', 'price', 'duration_days']

    def get_price(self, plan):
        return int(plan.price)


class MembershipSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source='plan.name', read_only=True)

    class Meta:
        model = Membership
        fields = ['id', 'plan', 'plan_name', 'status', 'starts_at', 'ends_at']
        read_only_fields = fields


class PhoneRequestSerializer(serializers.Serializer):
    phone = serializers.CharField()


class TipRequestSerializer(serializers.Serializer):
    amount = serializers.IntegerField(min_value=10, max_value=70000)
    phone = serializers.CharField()
    message = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
