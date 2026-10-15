from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from accounts.permissions import BlogPermission, ReadOnlyOrEditor
from payments.serializers import PaymentSerializer
from payments.services import PaymentError

from . import services
from .models import Author, Blog, Membership, MembershipPlan, Tip
from .serializers import (
    AuthorSerializer,
    BlogSerializer,
    MembershipPlanSerializer,
    MembershipSerializer,
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
    permission_classes = [BlogPermission]
    throttle_classes = [UserRateThrottle, AnonRateThrottle]
    throttle_scope = None   # set per-action (@action(throttle_scope=...)); DRF needs the attribute to exist
    queryset = Blog.objects.select_related('author').annotate(
        tips_total=money_sum('tips__amount', filter=Q(tips__status=Tip.Status.PAID)),
        tips_count=Count('tips', filter=Q(tips__status=Tip.Status.PAID)),
    )
    serializer_class = BlogSerializer

        # 1. Enable specific filters for this viewset
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]

    # 2. Define which fields act as text searches
    search_fields = ['title', 'text', 'author__first_name', 'author__last_name']

    # 3. Define which fields clients are allowed to sort by
    ordering_fields = ['published_date', 'created_at', 'title']

    # 4. (Optional) Provide a default ordering
    ordering = ['-published_date']

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


class IsWriter(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role in ('admin', 'editor', 'author'))


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

# class BlogListCreateAPIView(APIView):
#     def get(self, request):
#         blogs = Blog.objects.select_related('author').all()
#         serializer = BlogSerializer(blogs, many=True)
#         return Response(serializer.data)

#     def post(self, request):
#         serializer = BlogSerializer(data=request.data)
#         if serializer.is_valid():
#             try:
#                 serializer.save()
#                 return Response(serializer.data, status=status.HTTP_201_CREATED)
#             except IntegrityError:
#                 return Response({"detail": "Invalid data."}, status=status.HTTP_409_CONFLICT)
#         return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# class BlogDetailAPIView(APIView):
#     def get_object(self, pk):
#         try:
#             return Blog.objects.get(pk=pk)
#         except Blog.DoesNotExist:
#             raise exceptions.NotFound(f"Blog with ID {pk} not found.")

#     def get(self, request, pk):
#         blog = self.get_object(pk)
#         serializer = BlogSerializer(blog)
#         return Response(serializer.data)

#     def put(self, request, pk):
#         blog = self.get_object(pk)
#         serializer = BlogSerializer(blog, data=request.data)
#         if serializer.is_valid():
#             try:
#                 serializer.save()
#                 return Response(serializer.data)
#             except IntegrityError:
#                 return Response({"detail": "Invalid data."}, status=status.HTTP_409_CONFLICT)
#         return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

#     def delete(self, request, pk):
#         blog = self.get_object(pk)
#         blog.delete()
#         return Response(status=status.HTTP_204_NO_CONTENT)

# class AuthorListAPIView(APIView):
#     def get(self, request):
#         authors = Author.objects.all()
#         serializer = AuthorSerializer(authors, many=True)
#         return Response(serializer.data)