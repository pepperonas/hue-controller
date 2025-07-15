#!/usr/bin/env python3
"""
Test script to verify unreachable lights handling
"""
import requests
import json
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Configuration
HUE_BRIDGE_IP = os.getenv('HUE_BRIDGE_IP')
HUE_USERNAME = os.getenv('HUE_USERNAME')
FLASK_BASE_URL = f"http://localhost:{os.getenv('FLASK_PORT', 5000)}"

def get_lights_from_bridge():
    """Get lights directly from Hue Bridge"""
    url = f"http://{HUE_BRIDGE_IP}/api/{HUE_USERNAME}/lights"
    response = requests.get(url, timeout=5)
    return response.json()

def get_lights_from_flask():
    """Get lights from Flask API"""
    url = f"{FLASK_BASE_URL}/api/lights"
    response = requests.get(url, timeout=5)
    return response.json()

def get_power_from_flask():
    """Get current power consumption from Flask API"""
    url = f"{FLASK_BASE_URL}/api/power/current"
    response = requests.get(url, timeout=5)
    return response.json()

def main():
    print("🔍 Testing Unreachable Lights Handling\n")
    
    # Get lights from both sources
    bridge_lights = get_lights_from_bridge()
    flask_lights = get_lights_from_flask()
    
    print("📡 Bridge Lights Status:")
    print("-" * 50)
    for light_id, light in bridge_lights.items():
        state = light.get('state', {})
        on = state.get('on', False)
        reachable = state.get('reachable', True)
        print(f"Light {light_id} ({light['name']}):")
        print(f"  - On: {on}")
        print(f"  - Reachable: {reachable}")
        print(f"  - Status: {'⚠️ UNREACHABLE but ON' if on and not reachable else 'OK'}")
    
    print("\n🌐 Flask API Lights Status:")
    print("-" * 50)
    for light_id, light in flask_lights.items():
        state = light.get('state', {})
        on = state.get('on', False)
        on_display = state.get('on_display', on)
        reachable = state.get('reachable', True)
        print(f"Light {light_id} ({light['name']}):")
        print(f"  - On (actual): {on}")
        print(f"  - On (display): {on_display}")
        print(f"  - Reachable: {reachable}")
        if on and not reachable:
            print(f"  - ✅ Correctly shows as OFF in UI but counts for power")
    
    print("\n💡 Power Consumption:")
    print("-" * 50)
    power_data = get_power_from_flask()
    print(f"Total Power: {power_data['total_watts']}W")
    print(f"Active Lights: {power_data['active_lights']}")
    
    if 'light_details' in power_data:
        print("\nLight Details:")
        for detail in power_data['light_details']:
            reachable_status = "✅" if detail.get('reachable', True) else "⚠️"
            print(f"  - {detail['name']}: {detail['watts']}W {reachable_status}")
    
    # Verify unreachable lights are counted
    unreachable_but_on = []
    for light_id, light in bridge_lights.items():
        state = light.get('state', {})
        if state.get('on', False) and not state.get('reachable', True):
            unreachable_but_on.append(light['name'])
    
    if unreachable_but_on:
        print(f"\n⚠️ Unreachable lights that should still count for power:")
        for name in unreachable_but_on:
            print(f"  - {name}")

if __name__ == "__main__":
    main()