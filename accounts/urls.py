from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import (
    ChangePasswordView,
    ForgotPasswordView,
    GoogleLoginView,
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
    RegisterView,
    ResetPasswordView,
    UserViewSet,
)

router = SimpleRouter()
router.register(r'users', UserViewSet, basename='user')

urlpatterns = [
    path('token/', LoginView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', RefreshView.as_view(), name='token_refresh'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/google/', GoogleLoginView.as_view(), name='google-login'),
    path('auth/me/', MeView.as_view(), name='me'),
    path('auth/password/forgot/', ForgotPasswordView.as_view(), name='password-forgot'),
    path('auth/password/reset/', ResetPasswordView.as_view(), name='password-reset'),
    path('auth/password/change/', ChangePasswordView.as_view(), name='password-change'),
    path('v1/', include(router.urls)),
]
