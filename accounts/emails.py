import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

logger = logging.getLogger(__name__)


def send_password_reset_email(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = f"{settings.PASSWORD_RESET_URL}?{urlencode({'uid': uid, 'token': token})}"
    minutes = settings.PASSWORD_RESET_TIMEOUT // 60

    subject = f"Reset your {settings.SITE_NAME} password"
    body = (
        f"Hi {user.first_name or 'there'},\n\n"
        f"We received a request to reset the password for your {settings.SITE_NAME} account.\n"
        f"Use the link below to choose a new password. It expires in {minutes} minutes "
        f"and can only be used once.\n\n"
        f"{link}\n\n"
        f"If you didn't request this, you can safely ignore this email.\n"
    )
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email])
    except Exception:
        # Don't leak delivery problems to the caller (keeps responses uniform).
        logger.exception("Failed to send password reset email to user id=%s", user.pk)


def send_teacher_setup_email(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = f"{settings.TEACHER_SETUP_URL}?{urlencode({'uid': uid, 'token': token, 'mode': 'teacher-setup'})}"
    minutes = settings.PASSWORD_RESET_TIMEOUT // 60

    subject = f"Finish setting up your {settings.SITE_NAME} teacher account"
    body = (
        f"Hi {user.first_name or 'there'},\n\n"
        f"An administrator added you as a teacher on {settings.SITE_NAME}.\n"
        f"Finish your registration by choosing a password at the link below. "
        f"The link expires in {minutes} minutes and can only be used once.\n\n"
        f"{link}\n\n"
        "If you weren't expecting this invitation, you can ignore this email.\n"
    )
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email])
    except Exception:
        logger.exception("Failed to send teacher setup email to user id=%s", user.pk)
