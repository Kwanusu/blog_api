from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token


class GoogleAuthError(Exception):
    pass


def verify_google_id_token(token):
    """Validate a Google ID token and return its claims (email, name, ...)."""
    if not settings.GOOGLE_CLIENT_ID:
        raise GoogleAuthError('Google sign-in is not configured.')
    try:
        claims = id_token.verify_oauth2_token(
            token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )
    except ValueError as exc:  # bad signature, expired, wrong audience/issuer
        raise GoogleAuthError('Invalid Google token.') from exc
    if not claims.get('email') or not claims.get('email_verified'):
        raise GoogleAuthError('Google account email is not verified.')
    return claims
