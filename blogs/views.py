from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from accounts.permissions import BlogPermission, IsWriter, ReadOnlyOrEditor
from payments.serializers import PaymentSerializer
from payments.services import PaymentError

from . import services
from .models import Author, Blog, Membership, MembershipPlan, Tip
from .serializers import (
    AuthorSerializer,
    BlogSerializer,
    MembershipPlanSerializer,
    MembershipSerializer,
    PUBLISHERS,
    PhoneRequestSerializer,
    TipRequestSerializer,
)


def money_sum(field, **kwargs):
    """Sum of a whole-shilling column that is 0 (not NULL) when there is nothing to add up."""
    return Coalesce(Sum(field, **kwargs), Value(0), output_field=DecimalField(max_digits=12, decimal_places=0))


class AuthorViewSet(viewsets.ModelViewSet):
    """
    Any authenticated user can read authors; only editors/admins can modify them.
    """
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer
    permission_classes = [ReadOnlyOrEditor]


class BlogViewSet(viewsets.ModelViewSet):
    permission_classes = [ReadOnlyOrEditor]
    throttle_classes = [UserRateThrottle, AnonRateThrottle]
    throttle_scope = None   # set per-action (@action(throttle_scope=...)); DRF needs the attribute to exist
    queryset = Blog.objects.select_related('author').annotate(
        tips_total=money_sum('tips__amount', filter=Q(tips__status=Tip.Status.PAID)),
        tips_count=Count('tips', filter=Q(tips__status=Tip.Status.PAID)),
    )
    serializer_class = BlogSerializer

    # Query-string features: ?search=, ?ordering=, and exact-match filters such as ?is_premium=true.
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_premium', 'author']

    # Review fix A3: 'text' is deliberately NOT searchable. Searching the body would let a
    # non-member discover words inside premium posts (a post that matches the query is proof the
    # word is in the hidden text) even though the response only shows a teaser.
    search_fields = ['title', 'author__first_name', 'author__last_name']

    # Fields clients are allowed to sort by, and the default order (newest first).
    ordering_fields = ['published_date', 'created_at', 'title']
    ordering = ['-published_date']

    def get_queryset(self):
        """
        Limit what each role can see (review fix A2).

        * editors / admins ........ everything, including drafts
        * authors ................. published posts plus their own drafts
        * readers and everyone else  published posts only

        Filtering here (not in the serializer) matters because ``get_object()`` uses this queryset
        too: a draft that is hidden from the list is also a 404 on retrieve, update, delete and tip.
        """
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_superuser or user.role in PUBLISHERS:
            return queryset
        if user.role == 'author':
            return queryset.filter(Q(is_published=True) | Q(author__user=user))
        return queryset.filter(is_published=True)

    @action(
        detail=True, methods=['post'], permission_classes=[IsAuthenticated],
        throttle_classes=[ScopedRateThrottle], throttle_scope='payments',
    )
    def tip(self, request, pk=None):
        """Send the author a tip. Responds 202 with the payment; poll /api/payments/<id>/ until it settles."""
        blog = self.get_object()
        body = TipRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            payment = services.start_tip(
                request.user, blog, body.validated_data['amount'],
                body.validated_data['phone'], body.validated_data['message'],
            )
        except services.PurchaseError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        except PaymentError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'payment': PaymentSerializer(payment).data}, status=status.HTTP_202_ACCEPTED)


class MembershipPlanViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The plans on sale, and the endpoint that starts buying one."""

    queryset = MembershipPlan.objects.filter(is_active=True)
    serializer_class = MembershipPlanSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None
    throttle_scope = None   # set per-action

    @action(
        detail=True, methods=['post'], permission_classes=[IsAuthenticated],
        throttle_classes=[ScopedRateThrottle], throttle_scope='payments',
    )
    def subscribe(self, request, pk=None):
        """Buy (or renew) a plan. Responds 202 with the payment; poll /api/payments/<id>/ until it settles."""
        plan = self.get_object()
        body = PhoneRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            payment = services.start_membership(request.user, plan, body.validated_data['phone'])
        except services.PurchaseError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        except PaymentError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'payment': PaymentSerializer(payment).data}, status=status.HTTP_202_ACCEPTED)


@extend_schema(responses=OpenApiTypes.OBJECT)
class MembershipView(APIView):
    """Is the signed-in user a member right now, and for how long?"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        current = Membership.current_for(request.user)
        history = Membership.objects.filter(user=request.user, status=Membership.Status.ACTIVE).select_related('plan')[:5]
        return Response({
            'active': current is not None,
            'current': MembershipSerializer(current).data if current else None,
            'history': MembershipSerializer(history, many=True).data,
        })


@extend_schema(responses=OpenApiTypes.OBJECT)
class EarningsView(APIView):
    """Tips received. Authors see theirs; editors and admins see everyone's."""

    permission_classes = [IsWriter]

    def get(self, request):
        tips = Tip.objects.filter(status=Tip.Status.PAID).select_related('blog', 'tipper')
        if request.user.role == 'author':
            tips = tips.filter(author__user=request.user)

        totals = tips.aggregate(total=money_sum('amount'), count=Count('id'))
        by_blog = (
            tips.exclude(blog=None).values('blog_id', 'blog__title')
            .annotate(total=money_sum('amount'), count=Count('id')).order_by('-total')[:10]
        )
        return Response({
            'total': int(totals['total']),
            'count': totals['count'],
            'by_blog': [
                {'blog': row['blog_id'], 'title': row['blog__title'], 'total': int(row['total']), 'count': row['count']}
                for row in by_blog
            ],
            'recent': [
                {
                    'id': t.id,
                    'amount': int(t.amount),
                    'message': t.message,
                    'blog': t.blog_id,
                    'blog_title': t.blog.title if t.blog else None,
                    # first name only: enough to say thanks, not enough to expose the supporter
                    'from': (t.tipper.first_name or 'A reader') if t.tipper else 'A reader',
                    'created_at': t.created_at,
                }
                for t in tips[:10]
            ],
        })
