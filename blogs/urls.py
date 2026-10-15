from django.urls import path, include
from .views import (
    AuthorViewSet,
    BlogViewSet,
    EarningsView,
    MembershipPlanViewSet,
    MembershipView,
)
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'blogs', BlogViewSet, basename='blog')
router.register(r'authors', AuthorViewSet, basename='author')
router.register(r'plans', MembershipPlanViewSet, basename='plan')

urlpatterns = [
    path('v1/membership/', MembershipView.as_view(), name='membership'),
    path('v1/earnings/', EarningsView.as_view(), name='earnings'),
    path('v1/', include(router.urls)),
]
