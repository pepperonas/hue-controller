#!/usr/bin/env python3
"""
Test script to verify power consumption calculation includes unreachable lights
"""
import requests
import json

# Configuration
HUE_BRIDGE_IP = '192.168.2.35'
HUE_USERNAME = '1trezWogQDPyNuC19bcyOHp8BsNCMZr6wKfXwe6w'
BASE_URL = f'http://{HUE_BRIDGE_IP}/api/{HUE_USERNAME}'

def get_lights():
    """Get all lights from Hue Bridge"""
    response = requests.get(f'{BASE_URL}/lights')
    return response.json()

def test_power_calculation():
    """Test power calculation with reachable status"""
    lights = get_lights()
    
    print("=== Light Status ===")
    for light_id, light in lights.items():
        state = light.get('state', {})
        is_on = state.get('on', False)
        is_reachable = state.get('reachable', True)
        brightness = state.get('bri', 254)
        
        if is_on:
            watts = (brightness / 254) * 9
            print(f"Light {light_id} - {light['name']}:")
            print(f"  On: {is_on}, Reachable: {is_reachable}")
            print(f"  Brightness: {brightness} ({round(brightness/254*100)}%)")
            print(f"  Power: {watts:.2f}W")
            print(f"  Status: {'⚠️ UNREACHABLE but still consuming power' if not is_reachable else '✓ OK'}")
            print()

def test_api_endpoint():
    """Test the Flask API endpoint"""
    try:
        response = requests.get('http://localhost:5000/api/power/current')
        data = response.json()
        
        print("\n=== API Response ===")
        print(f"Total Watts: {data['total_watts']}W")
        print(f"Active Lights: {data['active_lights']}")
        print(f"\nLight Details:")
        for light in data['light_details']:
            status = '⚠️ unreachable' if not light.get('reachable', True) else '✓'
            print(f"  {light['name']} - {light['watts']}W {status}")
            
    except Exception as e:
        print(f"Error calling API: {e}")
        print("Make sure the Flask app is running on port 5000")

if __name__ == "__main__":
    print("Testing power consumption calculation for unreachable lights\n")
    test_power_calculation()
    print("\n" + "="*50 + "\n")
    test_api_endpoint()