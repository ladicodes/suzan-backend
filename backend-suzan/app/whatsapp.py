import requests
from .config import settings

def send_whatsapp(to: str, text: str):
    # Sanitize phone number (remove + and spaces)
    clean_to = to.replace("+", "").replace(" ", "").strip()
    
    # 1. FIXED: Changed to 'WHATSAPP_PHONE_ID' to match your Config & .env
    # 2. FIXED: Changed version to 'v22.0' to match your working CURL
    url = f"https://graph.facebook.com/v22.0/{settings.WHATSAPP_PHONE_ID}/messages"
    
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_to,
        "type": "text",
        "text": {
            "preview_url": False, 
            "body": text
        }
    }
    
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code in [200, 201]:
            print(f"✅ SENT to {clean_to}")
        else:
            print(f"❌ SEND FAILED: {response.status_code} - {response.text}")
        return response.json()
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return {"error": str(e)}