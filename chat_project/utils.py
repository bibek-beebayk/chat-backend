import requests
import os
from django.conf import settings

ZEPTOMAIL_URL = "https://api.zeptomail.com.au/v1.1/email"

def send_zeptomail(to_email, subject, html):
    payload = {
        "from": {
            "address": "noreply@hrlzone.com"
        },
        "to": [
            {
                "email_address": {
                    "address": to_email
                }
            }
        ],
        "subject": subject,
        "htmlbody": html
    }

    headers = {
        "Authorization": f"Zoho-enczapikey {settings.ZEPTOMAIL_API_KEY}",
        "Content-Type": "application/json"
    }

    response = requests.post(ZEPTOMAIL_URL, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()
