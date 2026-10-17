"""
Settings used only by the automated tests (review fix B4).

Run the suite with:   python manage.py test --settings=blog_api.settings_test

Why: Django hashes passwords with PBKDF2 on purpose, because it is slow. That is right for production
but made the 143 tests take about 52 seconds; with a fast hasher the same tests take about a second.
Never use this module for a real server.
"""
from .settings import *  # noqa: F401,F403

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Tests intentionally trigger warnings/errors (401/403 responses, unknown checkout ids, rejected STK
# pushes). Silence logging so the test output shows only real results.
import logging  # noqa: E402

logging.disable(logging.CRITICAL)
