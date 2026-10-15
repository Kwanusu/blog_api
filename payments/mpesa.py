"""
Thin client for Safaricom's Daraja API (Lipa na M-Pesa Online / STK Push).

Nothing here touches the database — see services.py for the payment lifecycle.
"""
import base64
import logging
import re
import uuid

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

logger = logging.getLogger(__name__)

BASE_URLS = {
    'sandbox': 'https://sandbox.safaricom.co.ke',
    'production': 'https://api.safaricom.co.ke',
}
TIMEOUT = 20

# Daraja result codes we treat specially.
RESULT_SUCCESS = 0
RESULT_CANCELLED = 1032      # user dismissed the prompt
RESULT_TIMEOUT = 1037        # prompt expired unanswered
STILL_PROCESSING = '500.001.1001'


class MpesaError(Exception):
    """Raised when Daraja rejects a request or can't be reached."""


def env():
    value = getattr(settings, 'MPESA_ENV', 'sandbox')
    if value not in ('sandbox', 'production', 'simulate'):
        raise ImproperlyConfigured("MPESA_ENV must be 'sandbox', 'production' or 'simulate'.")
    if value == 'simulate' and not settings.DEBUG:
        raise ImproperlyConfigured("MPESA_ENV='simulate' is only allowed when DEBUG is on.")
    return value


def is_simulated():
    return env() == 'simulate'


def normalize_phone(raw):
    """Return a Safaricom MSISDN like 254712345678, or raise ValueError."""
    digits = re.sub(r'[\s\-().]', '', str(raw or ''))
    digits = digits.removeprefix('+')
    if len(digits) == 10 and digits.startswith('0'):
        digits = '254' + digits[1:]
    elif len(digits) == 9 and digits[0] in '17':
        digits = '254' + digits
    if not re.fullmatch(r'254[17]\d{8}', digits):
        raise ValueError('Enter a valid Safaricom number, e.g. 0712 345 678.')
    return digits


def _require_credentials():
    missing = [
        name for name in ('MPESA_CONSUMER_KEY', 'MPESA_CONSUMER_SECRET', 'MPESA_SHORTCODE', 'MPESA_PASSKEY')
        if not getattr(settings, name, '')
    ]
    if missing:
        raise MpesaError('M-Pesa is not configured yet (' + ', '.join(missing) + ' missing).')


def access_token():
    _require_credentials()
    key = settings.MPESA_CONSUMER_KEY
    cache_key = f'mpesa:token:{env()}:{key[-6:]}'
    token = cache.get(cache_key)
    if token:
        return token
    try:
        res = requests.get(
            f'{BASE_URLS[env()]}/oauth/v1/generate',
            params={'grant_type': 'client_credentials'},
            auth=(key, settings.MPESA_CONSUMER_SECRET),
            timeout=TIMEOUT,
        )
        res.raise_for_status()
        data = res.json()
        token = data['access_token']
    except (requests.RequestException, KeyError, ValueError) as exc:
        logger.warning('Daraja token request failed: %s', exc)
        raise MpesaError('Could not authenticate with M-Pesa. Please try again shortly.') from exc
    # Tokens last 1 hour; refresh a little early.
    cache.set(cache_key, token, int(data.get('expires_in', 3599)) - 120)
    return token


def _timestamp():
    return timezone.localtime().strftime('%Y%m%d%H%M%S')


def _password(timestamp):
    raw = f'{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}'
    return base64.b64encode(raw.encode()).decode()


def _post(path, payload):
    try:
        res = requests.post(
            f'{BASE_URLS[env()]}{path}',
            json=payload,
            headers={'Authorization': f'Bearer {access_token()}'},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning('Daraja request to %s failed: %s', path, exc)
        raise MpesaError('Could not reach M-Pesa. Please try again shortly.') from exc
    try:
        return res.status_code, res.json()
    except ValueError as exc:
        raise MpesaError('M-Pesa returned an unexpected response.') from exc


def stk_push(*, phone, amount, account_reference, description, callback_url):
    """Send the PIN prompt to the customer's phone. Returns Daraja's response dict."""
    if is_simulated():
        stamp = uuid.uuid4().hex[:12]
        return {
            'MerchantRequestID': f'SIM-{stamp}',
            'CheckoutRequestID': f'ws_CO_SIM_{stamp}',
            'ResponseCode': '0',
            'ResponseDescription': 'Success. Request accepted for processing',
            'CustomerMessage': 'Simulated: payment will complete automatically.',
        }

    timestamp = _timestamp()
    party_b = getattr(settings, 'MPESA_PARTY_B', '') or settings.MPESA_SHORTCODE
    payload = {
        'BusinessShortCode': settings.MPESA_SHORTCODE,
        'Password': _password(timestamp),
        'Timestamp': timestamp,
        'TransactionType': settings.MPESA_TRANSACTION_TYPE,
        'Amount': int(amount),
        'PartyA': phone,
        'PartyB': party_b,
        'PhoneNumber': phone,
        'CallBackURL': callback_url,
        'AccountReference': account_reference[:12],
        'TransactionDesc': description[:13],
    }
    status, data = _post('/mpesa/stkpush/v1/processrequest', payload)
    if status != 200 or str(data.get('ResponseCode')) != '0':
        logger.warning('STK push rejected (%s): %s', status, data)
        raise MpesaError(data.get('errorMessage') or data.get('ResponseDescription') or 'M-Pesa rejected the request.')
    return data


def stk_query(checkout_request_id):
    """
    Ask Daraja what happened to a prompt. Returns None while it is still processing,
    otherwise a dict with at least ResultCode (int) and ResultDesc.
    """
    timestamp = _timestamp()
    payload = {
        'BusinessShortCode': settings.MPESA_SHORTCODE,
        'Password': _password(timestamp),
        'Timestamp': timestamp,
        'CheckoutRequestID': checkout_request_id,
    }
    status, data = _post('/mpesa/stkpushquery/v1/query', payload)
    if data.get('errorCode') == STILL_PROCESSING:
        return None
    if 'ResultCode' not in data:
        raise MpesaError(data.get('errorMessage') or 'Could not check the payment status.')
    data['ResultCode'] = int(data['ResultCode'])
    return data
