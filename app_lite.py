#!/usr/bin/env python3
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import requests
import json
import threading
import time
from datetime import datetime, timedelta
import os
from pathlib import Path

# .env Datei laden falls vorhanden
def load_env():
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

load_env()

app = Flask(__name__)
CORS(app)

# Konfiguration mit Umgebungsvariablen
HUE_BRIDGE_IP = os.getenv('HUE_BRIDGE_IP', '192.168.2.35')
HUE_USERNAME = os.getenv('HUE_USERNAME', '1trezWogQDPyNuC19bcyOHp8BsNCMZr6wKfXwe6w')

# Globale Variablen für Effects und Timer
running_effects = {}
active_timers = {}

def get_lights_raw():
    """Lichter direkt von Bridge abrufen"""
    try:
        response = requests.get(f"http://{HUE_BRIDGE_IP}/api/{HUE_USERNAME}/lights", timeout=5)
        return response.json()
    except:
        return {}

def hue_request(endpoint, method='GET', data=None):
    """Standard Hue API Request"""
    try:
        url = f"http://{HUE_BRIDGE_IP}/api/{HUE_USERNAME}/{endpoint}"
        if method == 'GET':
            response = requests.get(url, timeout=5)
        elif method == 'PUT':
            response = requests.put(url, json=data, timeout=5)
        elif method == 'POST':
            response = requests.post(url, json=data, timeout=5)
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# === BASIC ROUTES ===
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/lights', methods=['GET'])
def get_lights():
    return jsonify(hue_request('lights'))

@app.route('/api/lights/<light_id>/state', methods=['PUT'])
def set_light_state(light_id):
    data = request.get_json()
    return jsonify(hue_request(f'lights/{light_id}/state', 'PUT', data))

@app.route('/api/groups', methods=['GET'])
def get_groups():
    return jsonify(hue_request('groups'))

@app.route('/api/groups/<group_id>/action', methods=['PUT'])
def set_group_action(group_id):
    data = request.get_json()
    return jsonify(hue_request(f'groups/{group_id}/action', 'PUT', data))

# === SZENEN ===
@app.route('/api/scenes', methods=['GET'])
def get_scenes():
    return jsonify(hue_request('scenes'))

@app.route('/api/scenes/<scene_id>/recall', methods=['PUT'])
def recall_scene(scene_id):
    """Szene für Gruppe aktivieren"""
    group_id = request.json.get('group', '0')
    return jsonify(hue_request(f'groups/{group_id}/action', 'PUT', {'scene': scene_id}))

@app.route('/api/lights/<light_id>/scene', methods=['PUT'])
def set_light_scene(light_id):
    """Szene für einzelnes Licht"""
    scene_id = request.json.get('scene')
    scenes = hue_request('scenes')
    
    if scene_id in scenes:
        scene = scenes[scene_id]
        if light_id in scene.get('lightstates', {}):
            state = scene['lightstates'][light_id]
            return jsonify(hue_request(f'lights/{light_id}/state', 'PUT', state))
    
    return jsonify({"error": "Scene not found or light not in scene"})

# === SPECIAL EFFECTS ===
@app.route('/api/effects/strobe', methods=['POST'])
def start_strobe():
    """Strobo Effect starten"""
    data = request.get_json()
    target_type = data.get('type', 'light')  # 'light' oder 'group'
    target_id = data.get('id')
    duration = data.get('duration', 10)  # Sekunden
    interval = data.get('interval', 0.5)  # Sekunden zwischen Blinks
    
    effect_id = f"{target_type}_{target_id}_strobe"
    
    def strobe_effect():
        start_time = time.time()
        while time.time() - start_time < duration and effect_id in running_effects:
            # An
            endpoint = f"{target_type}s/{target_id}/{'action' if target_type == 'group' else 'state'}"
            hue_request(endpoint, 'PUT', {'on': True, 'bri': 254})
            time.sleep(interval / 2)
            
            # Aus
            hue_request(endpoint, 'PUT', {'on': False})
            time.sleep(interval / 2)
        
        # Cleanup
        if effect_id in running_effects:
            del running_effects[effect_id]
    
    if effect_id not in running_effects:
        running_effects[effect_id] = True
        threading.Thread(target=strobe_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id})
    
    return jsonify({"error": "Effect already running"})

@app.route('/api/effects/colorloop', methods=['POST'])
def start_colorloop():
    """Farbschleife Effect"""
    data = request.get_json()
    target_type = data.get('type', 'light')
    target_id = data.get('id')
    duration = data.get('duration', 30)
    
    effect_id = f"{target_type}_{target_id}_colorloop"
    
    def colorloop_effect():
        start_time = time.time()
        hue = 0
        
        while time.time() - start_time < duration and effect_id in running_effects:
            endpoint = f"{target_type}s/{target_id}/{'action' if target_type == 'group' else 'state'}"
            hue_request(endpoint, 'PUT', {'on': True, 'hue': hue, 'sat': 254, 'bri': 254})
            hue = (hue + 1000) % 65535
            time.sleep(0.1)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
    
    if effect_id not in running_effects:
        running_effects[effect_id] = True
        threading.Thread(target=colorloop_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id})
    
    return jsonify({"error": "Effect already running"})

@app.route('/api/effects/<effect_id>/stop', methods=['DELETE'])
def stop_effect(effect_id):
    """Effect stoppen"""
    if effect_id in running_effects:
        del running_effects[effect_id]
        return jsonify({"success": True})
    return jsonify({"error": "Effect not found"})

@app.route('/api/effects', methods=['GET'])
def get_active_effects():
    """Aktive Effects auflisten"""
    return jsonify({"active_effects": list(running_effects.keys())})

# === TIMER ===
@app.route('/api/timer', methods=['POST'])
def create_timer():
    """Timer erstellen"""
    data = request.get_json()
    target_type = data.get('type', 'light')
    target_id = data.get('id')
    delay = data.get('delay', 60)  # Sekunden
    action = data.get('action', {'on': False})
    
    timer_id = f"{target_type}_{target_id}_{int(time.time())}"
    
    def timer_action():
        time.sleep(delay)
        if timer_id in active_timers:
            endpoint = f"{target_type}s/{target_id}/{'action' if target_type == 'group' else 'state'}"
            hue_request(endpoint, 'PUT', action)
            del active_timers[timer_id]
    
    active_timers[timer_id] = {
        'target_type': target_type,
        'target_id': target_id,
        'action': action,
        'remaining': delay,
        'created': datetime.now()
    }
    
    threading.Thread(target=timer_action, daemon=True).start()
    return jsonify({"success": True, "timer_id": timer_id})

@app.route('/api/timer/<timer_id>', methods=['DELETE'])
def cancel_timer(timer_id):
    """Timer löschen"""
    if timer_id in active_timers:
        del active_timers[timer_id]
        return jsonify({"success": True})
    return jsonify({"error": "Timer not found"})

@app.route('/api/timers', methods=['GET'])
def get_active_timers():
    """Aktive Timer auflisten"""
    return jsonify({"active_timers": active_timers})

# === SENSOREN & SCHALTER ===
@app.route('/api/sensors', methods=['GET'])
def get_sensors():
    return jsonify(hue_request('sensors'))

@app.route('/api/sensors/<sensor_id>/config', methods=['PUT'])
def configure_sensor(sensor_id):
    data = request.get_json()
    return jsonify(hue_request(f'sensors/{sensor_id}/config', 'PUT', data))

# === GLOBALE STEUERUNG ===
@app.route('/api/global/all-lights', methods=['PUT'])
def control_all_lights():
    """Alle Lichter steuern"""
    data = request.get_json()
    
    lights = get_lights_raw()
    results = []
    
    for light_id in lights.keys():
        result = hue_request(f'lights/{light_id}/state', 'PUT', data)
        results.append({"light_id": light_id, "result": result})
    
    return jsonify({"results": results})

@app.route('/api/global/all-groups', methods=['PUT'])
def control_all_groups():
    """Alle Gruppen steuern"""
    data = request.get_json()
    
    groups = hue_request('groups')
    results = []
    
    for group_id in groups.keys():
        if group_id != '0':  # Gruppe 0 ist "Alle Lichter"
            result = hue_request(f'groups/{group_id}/action', 'PUT', data)
            results.append({"group_id": group_id, "result": result})
    
    return jsonify({"results": results})

@app.route('/api/global/emergency-off', methods=['POST'])
def emergency_off():
    """Notaus - alles sofort aus"""
    return jsonify(hue_request('groups/0/action', 'PUT', {'on': False}))

# === STROMVERBRAUCH (SIMULIERT) ===
@app.route('/api/power/current', methods=['GET'])
def get_current_power():
    """Aktuellen Stromverbrauch berechnen (ohne DB)"""
    lights = get_lights_raw()
    total_consumption = 0
    active_lights = 0
    light_details = []
    
    for light_id, light in lights.items():
        if light.get('state', {}).get('on', False):
            brightness = light.get('state', {}).get('bri', 254)
            estimated_watts = (brightness / 254) * 9  # Geschätzt: max 9W pro LED
            total_consumption += estimated_watts
            active_lights += 1
            
            light_details.append({
                'id': light_id,
                'name': light['name'],
                'watts': round(estimated_watts, 2),
                'brightness': brightness
            })
    
    return jsonify({
        'total_watts': round(total_consumption, 2),
        'active_lights': active_lights,
        'light_details': light_details,
        'estimated_monthly_kwh': round(total_consumption * 24 * 30 / 1000, 2),
        'estimated_monthly_cost_eur': round(total_consumption * 24 * 30 / 1000 * 0.30, 2),
        'note': 'Power data simulated - no database logging'
    })

@app.route('/api/power/history', methods=['GET'])
def get_power_history():
    """Stromverbrauch Historie (Platzhalter ohne DB)"""
    return jsonify({
        'message': 'Database not configured - install MariaDB for power logging',
        'daily_summary': [],
        'today_hourly': []
    })

# === STATUS ===
@app.route('/api/status', methods=['GET'])
def get_status():
    """API Status"""
    try:
        # Test Hue Connection
        lights = get_lights_raw()
        hue_connected = len(lights) > 0 and 'error' not in str(lights)
        
        return jsonify({
            'status': 'running',
            'hue_bridge_ip': HUE_BRIDGE_IP,
            'hue_connected': hue_connected,
            'lights_count': len(lights) if hue_connected else 0,
            'active_effects': len(running_effects),
            'active_timers': len(active_timers),
            'database': 'disabled (lite mode)',
            'features': {
                'basic_control': True,
                'scenes': True,
                'effects': True,
                'timers': True,
                'sensors': True,
                'global_control': True,
                'power_estimation': True,
                'power_logging': False
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

if __name__ == '__main__':
    print("🏠 Hue Controller Lite gestartet!")
    print(f"📡 Bridge: {HUE_BRIDGE_IP}")
    print("🗄️ Database: Disabled (Lite Mode)")
    print("🌐 Starting server...")
    
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
