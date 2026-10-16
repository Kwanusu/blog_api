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