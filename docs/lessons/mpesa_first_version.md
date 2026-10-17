# Lesson reference: the first M-Pesa version (`mpesa/` app, lesson 1)

This code used to live in `mpesa/mpesa_utils.py` and `mpesa/views.py` and was exposed at `POST /api/pay/` and
`POST /api/pay/callback/`. It was **retired from the live API** (review item A4) because:

* the callback required a JWT, so Safaricom's anonymous request always received `401`;
* nothing was saved, validated or protected against duplicates;
* URLs were hard-coded to the sandbox, and `print()` was used instead of logging.

The production-quality replacement is the [`payments`](../../payments/README.md) app. Keep this page as a
**before/after study**: read it first, then read `payments/mpesa.py` and `payments/services.py`.

## The Daraja client (`mpesa_utils.py`)

```python
import base64
import requests
from requests.auth import HTTPBasicAuth
from decouple import config
import datetime

def get_mpesa_access_token():
    consumer_key = config('MPESA_CONSUMER_KEY')
    consumer_secret = config('MPESA_CONSUMER_SECRET')
    api_URL = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"

    try:
        r = requests.get(api_URL, auth=HTTPBasicAuth(consumer_key, consumer_secret))
        mpesa_access_token = r.json().get('access_token')
        return mpesa_access_token
    except Exception as e:
        print(f"Failed to fetch access token: {e}")
        return None
    
def generate_mpesa_password(shortcode, passkey, timestamp):
    data_to_encode = shortcode + passkey + timestamp
    encoded_string = base64.b64encode(data_to_encode.encode())
    return encoded_string.decode('utf-8')

def initiate_stk_push(phone_number, amount, account_reference, transaction_desc):
    access_token = get_mpesa_access_token()
    if not access_token:
        return {"error": "Failed to get access token"}

    api_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    shortcode = config('MPESA_SHORTCODE')
    passkey = config('MPESA_PASSKEY')
    password = generate_mpesa_password(shortcode, passkey, timestamp)
    
    # Needs to be a public URL that Daraja will send the success/failure result to
    callback_url = config('MPESA_CALLBACK_URL')

    # Safaricom expects format 2547XXXXXXXX
    formatted_phone = phone_number

    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": formatted_phone,
        "PartyB": shortcode,
        "PhoneNumber": formatted_phone,
        "CallBackURL": callback_url,
        "AccountReference": account_reference,
        "TransactionDesc": transaction_desc
    }

    response = requests.post(api_url, json=payload, headers=headers)
    return response.json()
```

## The two views (`views.py`)

```python
@api_view(['POST'])
def pay_with_mpesa(request):
    phone_number = request.data.get('phone_number') # Format: 2547XXXXXXXX
    amount = request.data.get('amount')
    
    if not phone_number or not amount:
        return Response({"error": "Phone number and amount are required."}, status=400)

    # Initiate payment
    response = initiate_stk_push(
        phone_number=phone_number,
        amount=amount,
        account_reference="Django Shop",
        transaction_desc="Payment for Order #1234"
    )

    return Response(response)

@api_view(['POST'])
def mpesa_callback(request):
    # Safaricom sends the transaction results here asynchronously
    data = request.data
    
    # Examine the ResultCode
    result_code = data.get('Body', {}).get('stkCallback', {}).get('ResultCode')
    
    if result_code == 0:
        # Transaction was successful, parse the receipt and update DB
        print("Payment successful!")
        callback_metadata = data['Body']['stkCallback']['CallbackMetadata']['Item']
        for item in callback_metadata:
            if item['Name'] == 'MpesaReceiptNumber':
                receipt = item.get('Value')
                print(f"Receipt: {receipt}")
    else:
        print("Payment failed or cancelled by user.")

    # Always return a 200 response to Daraja so they stop retrying
    return Response({"ResultCode": 0, "ResultDesc": "Accepted"})
```
