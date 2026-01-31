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


def search_player(username):
    try:
        # Backend fetch
        url = f"{settings.PLAYER_DATA_API_BASE_URL}/player/search?username={username}"
        response = requests.get(url, headers={'x-secret-key': settings.PLAYER_DATA_API_KEY})
        
        # We can intercept/modify response here
        data = response.json()
        return data["exists"]
        
    except Exception as e:
        print(e)
        return None


def check_eligibility(game_id, event_id):
    try:
        from events.models import Event
        event = Event.objects.get(id=event_id)
        start_date = event.start_date.strftime("%Y-%m-%d")
        end_date = event.end_date.strftime("%Y-%m-%d")
        
        url = f"{settings.PLAYER_DATA_API_BASE_URL}/player/transactions?startDate={start_date}&endDate={end_date}&username={game_id}"
        response = requests.get(url, headers={'x-secret-key': settings.PLAYER_DATA_API_KEY})
        
        if response.status_code != 200:
            return False

        data = response.json()
        rows = data.get("rows", [])
        
        total_recharge = sum(
            row.get("transactionAmount", 0) 
            for row in rows 
            if row.get("transactionType") == "recharge"
        )
        
        return total_recharge >= 10
        
    except Exception as e:
        print(f"Error checking eligibility: {e}")
        return False
