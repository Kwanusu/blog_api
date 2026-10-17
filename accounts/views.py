from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, mixins, serializers, status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .emails import send_password_reset_email
from .google import GoogleAuthError, verify_google_id_token
from .models import User
from .permissions import IsAdminRole
from .serializers import (
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    GoogleLoginSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
    RoleUpdateSerializer,
    UserSerializer,
)


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class UserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Admin-only: list users and change their role (PATCH {"role": "editor"})."""

    queryset = User.objects.order_by('id')
    permission_classes = [IsAdminRole]
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_serializer_class(self):
        if self.action == 'partial_update':
            return RoleUpdateSerializer
        return UserSerializer


@extend_schema(request=ForgotPasswordSerializer, responses=OpenApiTypes.OBJECT)
class ForgotPasswordView(APIView):
    """Request a reset email. Always answers 200 so emails can't be enumerated."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset'

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(
            email__iexact=serializer.validated_data['email'], is_active=True
        ).first()
        if user:
            send_password_reset_email(user)
        return Response(
            {'detail': 'If an account exists for that email, a reset link has been sent.'}
        )


@extend_schema(request=ResetPasswordSerializer, responses=OpenApiTypes.OBJECT)
class ResetPasswordView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset'

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'detail': 'Password has been reset. You can now log in.'})


@extend_schema(request=ChangePasswordSerializer, responses=OpenApiTypes.OBJECT)
class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'detail': 'Password changed.'}, status=status.HTTP_200_OK)


@extend_schema(request=GoogleLoginSerializer, responses=OpenApiTypes.OBJECT)
class GoogleLoginView(APIView):
    """
    Sign in / sign up with Google.

    The client obtains a Google ID token (Google Identity Services) and posts it
    here. Existing accounts with the same verified email are logged in; new
    emails get a `reader` account. The role is never taken from the client.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'social_login'

    def post(self, request):
        serializer = GoogleLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            claims = verify_google_id_token(serializer.validated_data['id_token'])
        except GoogleAuthError as exc:
            code = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if 'not configured' in str(exc)
                else status.HTTP_400_BAD_REQUEST
            )
            return Response({'detail': str(exc)}, status=code)

        email = claims['email']
        user = User.objects.filter(email__iexact=email).first()
        created = user is None
        if created:
            user = User(
                email=email,
                first_name=claims.get('given_name', ''),
                last_name=claims.get('family_name', ''),
                role=User.Role.READER,
            )
            user.set_unusable_password()
            user.save()
        elif not user.is_active:
            return Response(
                {'detail': 'This account is disabled.'}, status=status.HTTP_403_FORBIDDEN
            )

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'user': UserSerializer(user).data,
                'created': created,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class LoginView(TokenObtainPairView):
    """Email + password -> JWT pair. Throttled per client to slow brute-forcing."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'


class RefreshView(TokenRefreshView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'


@extend_schema(request=inline_serializer('LogoutRequest', {'refresh': serializers.CharField()}),
               responses={204: None})
class LogoutView(APIView):
    """Blacklists the given refresh token so it can't be used again."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get('refresh')
        if not token:
            return Response({'detail': 'refresh token is required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            refresh = RefreshToken(token)
        except TokenError:
            return Response({'detail': 'Invalid or expired token.'},
                            status=status.HTTP_400_BAD_REQUEST)
        # Review fix (low): only the token's owner may revoke it. Without this check any signed-in
        # user who obtained someone else's refresh token could log that person out.
        if str(refresh.get(api_settings.USER_ID_CLAIM)) != str(request.user.pk):
            return Response({'detail': 'Invalid or expired token.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            refresh.blacklist()
        except TokenError:
            return Response({'detail': 'Invalid or expired token.'},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)
