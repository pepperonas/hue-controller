import os

# HTTPS Proxy Support
IS_HTTPS = os.environ.get('HTTPS', '').lower() == 'true' or \
           os.environ.get('X-Forwarded-Proto', '') == 'https'

def get_hue_api_url():
    """Gibt die richtige Hue API URL zurück (direkt oder über Proxy)"""
    if IS_HTTPS:
        return "/api/hue-bridge"
    else:
        return f"http://{HUE_BRIDGE_IP}/api"

# Diese Funktion in deinen API-Calls verwenden:
# base_url = get_hue_api_url()
# response = requests.get(f"{base_url}/{username}/lights")
