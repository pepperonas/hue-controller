#!/usr/bin/env python3
from flask import Flask, jsonify, request, render_template, send_from_directory
from flask_cors import CORS
import requests
import json
import threading
import time
import uuid
from datetime import datetime, timedelta
import os
from pathlib import Path
import mysql.connector
from mysql.connector import pooling
from dataclasses import asdict

# Smart Error Handling System
from error_handler import smart_error_handler, log_system_error, get_system_health, get_error_stats

# Effect Builder System
from effect_builder import EffectBuilder, init_effect_builder_db

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

app = Flask(__name__, template_folder='public')
CORS(app)

# Konfiguration mit Umgebungsvariablen
HUE_BRIDGE_IP = os.getenv('HUE_BRIDGE_IP', '192.168.2.35')
HUE_USERNAME = os.getenv('HUE_USERNAME', '1trezWogQDPyNuC19bcyOHp8BsNCMZr6wKfXwe6w')

# MySQL Konfiguration
MYSQL_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'hue_monitoring'),
    'pool_name': 'hue_pool',
    'pool_size': 5,
    'pool_reset_session': True
}

# Globale Variablen für Effects und Timer
running_effects = {}
active_timers = {}
db_pool = None
power_logging_thread = None
effect_builder = None

# Smart Caching System für Performance
cache_store = {}
cache_ttl = {}

def get_cache(key, ttl_seconds=30):
    """Smart Cache mit TTL"""
    if key in cache_store and key in cache_ttl:
        if time.time() - cache_ttl[key] < ttl_seconds:
            return cache_store[key]
    return None

def set_cache(key, value, ttl_seconds=30):
    """Cache-Wert setzen"""
    cache_store[key] = value
    cache_ttl[key] = time.time()

def invalidate_cache(pattern=None):
    """Cache invalidieren"""
    if pattern:
        keys_to_remove = [k for k in cache_store.keys() if pattern in k]
        for key in keys_to_remove:
            cache_store.pop(key, None)
            cache_ttl.pop(key, None)
    else:
        cache_store.clear()
        cache_ttl.clear()

# Debug-Logging System
debug_logs = []
debug_stats = {
    'total_requests': 0,
    'error_count': 0,
    'last_request': None,
    'bridge_status': 'unknown'
}
MAX_DEBUG_LOGS = 200

def get_lights_raw():
    """Lichter mit Smart Caching abrufen"""
    cache_key = "lights_data"
    cached = get_cache(cache_key, 15)  # 15s Cache für Lights
    
    if cached:
        return cached
    
    try:
        response = requests.get(f"http://{HUE_BRIDGE_IP}/api/{HUE_USERNAME}/lights", timeout=2)
        result = response.json()
        set_cache(cache_key, result, 15)
        return result
    except:
        return {}

def add_debug_log(log_type, message, endpoint=None, data=None):
    """Debug-Log-Eintrag hinzufügen"""
    global debug_logs, debug_stats
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = {
        'timestamp': timestamp,
        'type': log_type,
        'message': message,
        'endpoint': endpoint,
        'data': data
    }
    
    debug_logs.append(log_entry)
    
    # Logs begrenzen
    if len(debug_logs) > MAX_DEBUG_LOGS:
        debug_logs = debug_logs[-MAX_DEBUG_LOGS:]
    
    # Stats aktualisieren
    if log_type == 'error':
        debug_stats['error_count'] += 1
    
    debug_stats['last_request'] = timestamp

def hue_request(endpoint, method='GET', data=None):
    """Standard Hue API Request mit Debug-Logging"""
    global debug_stats
    
    try:
        url = f"http://{HUE_BRIDGE_IP}/api/{HUE_USERNAME}/{endpoint}"
        debug_stats['total_requests'] += 1
        
        # Debug-Log für ausgehende Anfrage
        data_str = f" | Data: {data}" if data else ""
        add_debug_log('info', f"{method} /{endpoint}{data_str}", endpoint, data)
        
        # Optimierte Timeouts für bessere Performance
        timeout = 1.5 if endpoint.startswith(('lights/', 'groups/')) else 3
        
        if method == 'GET':
            response = requests.get(url, timeout=timeout)
        elif method == 'PUT':
            response = requests.put(url, json=data, timeout=timeout)
        elif method == 'POST':
            response = requests.post(url, json=data, timeout=timeout)
        
        result = response.json()
        
        # Erfolgreiche Antwort loggen
        if response.status_code == 200:
            debug_stats['bridge_status'] = 'connected'
            add_debug_log('success', f"✅ {method} /{endpoint} → {response.status_code}")
            
            # Cache invalidieren bei State-Änderungen
            if method in ['PUT', 'POST'] and ('lights' in endpoint or 'groups' in endpoint):
                invalidate_cache('lights')
                invalidate_cache('groups')
                
        else:
            add_debug_log('warning', f"⚠️ {method} /{endpoint} → {response.status_code}")
            
        return result
        
    except Exception as e:
        debug_stats['bridge_status'] = 'error'
        add_debug_log('error', f"❌ {method} /{endpoint} → {str(e)}")
        return {"error": str(e)}

def batch_lights_control(state, target_type='all', target_id=None):
    """Batch-Steuerung für synchrone Lichtschaltung - ULTRA SCHNELL"""
    try:
        if target_type == 'all':
            # Alle Lichter über Gruppe 0 (Entertainment Group) - Schnellster Weg
            return hue_request('groups/0/action', 'PUT', state)
        elif target_type == 'group':
            # Spezifische Gruppe
            return hue_request(f'groups/{target_id}/action', 'PUT', state)
        else:
            # Einzelnes Licht
            return hue_request(f'lights/{target_id}/state', 'PUT', state)
    except Exception as e:
        add_debug_log('error', f"Batch control error: {str(e)}")
        return {"error": str(e)}

def ultra_fast_flash(lights_state, off_state, flash_duration=0.05):
    """Ultra-schneller Lichtblitz - Minimale Latenz"""
    # AN - Sofortiger Blitz
    batch_lights_control({**lights_state, 'transitiontime': 0}, 'all')
    time.sleep(flash_duration)
    
    # AUS - Sofortiges Ausschalten  
    batch_lights_control({**off_state, 'transitiontime': 0}, 'all')
    
def emergency_strobe_stop():
    """Notfall-Stopp für alle Strobo-Effekte"""
    global running_effects
    
    # Alle Strobo-Effekte stoppen
    strobo_effects = [eid for eid in running_effects.keys() if 'strobe' in eid]
    for effect_id in strobo_effects:
        if effect_id in running_effects:
            del running_effects[effect_id]
    
    # Alle Lichter sanft ausschalten
    batch_lights_control({'on': False, 'transitiontime': 10}, 'all')  # 1 Sekunde sanfter Übergang
    add_debug_log('warning', '🚨 Emergency strobo stop executed')

# === DATENBANK FUNKTIONEN ===
def init_db():
    """Initialisiere Datenbankverbindung und erstelle Tabellen"""
    global db_pool
    try:
        # Connection Pool erstellen
        db_pool = mysql.connector.pooling.MySQLConnectionPool(**MYSQL_CONFIG)
        
        # Tabellen erstellen falls nicht vorhanden
        conn = db_pool.get_connection()
        cursor = conn.cursor()
        
        # Power log Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS power_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                light_id VARCHAR(10) NOT NULL,
                light_name VARCHAR(100) NOT NULL,
                watts DECIMAL(5,2) NOT NULL,
                brightness INT NOT NULL,
                INDEX idx_timestamp (timestamp),
                INDEX idx_light_id (light_id)
            )
        """)
        
        # Total consumption Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS total_consumption (
                id INT AUTO_INCREMENT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                total_watts DECIMAL(7,2) NOT NULL,
                active_lights INT NOT NULL,
                INDEX idx_timestamp (timestamp)
            )
        """)
        
        # User Preferences Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id VARCHAR(50) NOT NULL DEFAULT 'default',
                preference_key VARCHAR(100) NOT NULL,
                preference_value TEXT NOT NULL,
                data_type VARCHAR(20) NOT NULL DEFAULT 'string',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY unique_user_pref (user_id, preference_key),
                INDEX idx_user_id (user_id)
            )
        """)
        
        # System Settings Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                setting_key VARCHAR(100) NOT NULL UNIQUE,
                setting_value TEXT NOT NULL,
                data_type VARCHAR(20) NOT NULL DEFAULT 'string',
                description TEXT,
                is_public BOOLEAN DEFAULT FALSE,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_setting_key (setting_key)
            )
        """)
        
        # Scene Usage Tracking Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scene_usage (
                id INT AUTO_INCREMENT PRIMARY KEY,
                scene_type VARCHAR(50) NOT NULL,
                scene_id VARCHAR(100) NOT NULL,
                scene_name VARCHAR(100) NOT NULL,
                user_id VARCHAR(50) NOT NULL DEFAULT 'default',
                activation_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                duration_seconds INT,
                device_info TEXT,
                INDEX idx_scene_type (scene_type),
                INDEX idx_scene_id (scene_id),
                INDEX idx_user_id (user_id),
                INDEX idx_activation_time (activation_time)
            )
        """)
        
        # Effect Usage Tracking Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS effect_usage (
                id INT AUTO_INCREMENT PRIMARY KEY,
                effect_type VARCHAR(50) NOT NULL,
                effect_id VARCHAR(100),
                effect_name VARCHAR(100) NOT NULL,
                user_id VARCHAR(50) NOT NULL DEFAULT 'default',
                start_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                end_time DATETIME,
                duration_seconds INT,
                target_type VARCHAR(20) NOT NULL,
                target_count INT,
                parameters_json TEXT,
                INDEX idx_effect_type (effect_type),
                INDEX idx_user_id (user_id),
                INDEX idx_start_time (start_time)
            )
        """)
        
        # System Error Log Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_error_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                error_category VARCHAR(50) NOT NULL,
                error_type VARCHAR(100) NOT NULL,
                error_message TEXT NOT NULL,
                context_info TEXT,
                stack_trace TEXT,
                user_id VARCHAR(50),
                ip_address VARCHAR(45),
                user_agent TEXT,
                resolved BOOLEAN DEFAULT FALSE,
                resolution_notes TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME,
                INDEX idx_error_category (error_category),
                INDEX idx_error_type (error_type),
                INDEX idx_created_at (created_at),
                INDEX idx_resolved (resolved)
            )
        """)
        
        # Audio Sync Sessions Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audio_sync_sessions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL UNIQUE,
                user_id VARCHAR(50) NOT NULL DEFAULT 'default',
                device_index INT,
                sync_mode VARCHAR(20) NOT NULL,
                sensitivity DECIMAL(3,2),
                start_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                end_time DATETIME,
                duration_seconds INT,
                beats_detected INT DEFAULT 0,
                avg_bpm DECIMAL(5,2),
                lights_affected TEXT,
                INDEX idx_session_id (session_id),
                INDEX idx_user_id (user_id),
                INDEX idx_start_time (start_time)
            )
        """)
        
        # System Health Log Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_health_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                check_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                overall_status VARCHAR(20) NOT NULL,
                hue_bridge_status VARCHAR(50),
                database_status VARCHAR(50),
                audio_system_status VARCHAR(50),
                active_effects_count INT DEFAULT 0,
                total_errors_count INT DEFAULT 0,
                memory_usage_mb DECIMAL(7,2),
                cpu_usage_percent DECIMAL(5,2),
                uptime_seconds INT,
                recommendations_json TEXT,
                INDEX idx_check_time (check_time),
                INDEX idx_overall_status (overall_status)
            )
        """)
        
        # Light State History Tabelle (für Advanced Analytics)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS light_state_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                light_id VARCHAR(10) NOT NULL,
                light_name VARCHAR(100) NOT NULL,
                is_on BOOLEAN NOT NULL,
                brightness INT,
                hue INT,
                saturation INT,
                color_temp INT,
                effect VARCHAR(50),
                changed_by VARCHAR(50),
                change_reason VARCHAR(100),
                INDEX idx_timestamp (timestamp),
                INDEX idx_light_id (light_id),
                INDEX idx_changed_by (changed_by)
            )
        """)
        
        # Popular Color Combinations Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS popular_colors (
                id INT AUTO_INCREMENT PRIMARY KEY,
                color_combo_id VARCHAR(36) NOT NULL UNIQUE,
                color_name VARCHAR(100),
                hex_colors_json TEXT NOT NULL,
                hue_values_json TEXT NOT NULL,
                usage_count INT DEFAULT 1,
                avg_rating DECIMAL(3,2),
                created_by VARCHAR(50) NOT NULL DEFAULT 'user',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_used DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_public BOOLEAN DEFAULT FALSE,
                INDEX idx_usage_count (usage_count),
                INDEX idx_created_by (created_by),
                INDEX idx_last_used (last_used)
            )
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("✅ Datenbank initialisiert")
        return True
        
    except mysql.connector.Error as e:
        print(f"❌ Datenbank-Fehler: {e}")
        print("   App läuft weiter ohne Datenbank-Logging")
        return False

def log_power_consumption():
    """Logge aktuellen Stromverbrauch in Datenbank"""
    if not db_pool:
        return
        
    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor()
        
        # Lichter abrufen
        lights = get_lights_raw()
        timestamp = datetime.now()
        total_watts = 0
        active_lights = 0
        
        # Einzelne Lichter loggen
        for light_id, light in lights.items():
            # Nur Lichter zählen die eingeschaltet sind (unabhängig von reachable-Status)
            # Hinweis: Unreachable Lichter verbrauchen auch Strom wenn sie "on" sind
            if light.get('state', {}).get('on', False):
                brightness = light.get('state', {}).get('bri', 254)
                watts = (brightness / 254) * 9  # Max 9W pro LED
                
                cursor.execute("""
                    INSERT INTO power_log (timestamp, light_id, light_name, watts, brightness)
                    VALUES (%s, %s, %s, %s, %s)
                """, (timestamp, light_id, light['name'], watts, brightness))
                
                total_watts += watts
                active_lights += 1
        
        # Gesamtverbrauch loggen
        cursor.execute("""
            INSERT INTO total_consumption (timestamp, total_watts, active_lights)
            VALUES (%s, %s, %s)
        """, (timestamp, total_watts, active_lights))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"📊 Power logged: {active_lights} lights, {total_watts:.2f}W")
        
    except Exception as e:
        print(f"❌ Fehler beim Power-Logging: {e}")

def power_logging_worker():
    """Background Thread für periodisches Power Logging - jede Minute"""
    while True:
        try:
            log_power_consumption()
            time.sleep(60)  # 1 Minute für detaillierte Erfassung
        except Exception as e:
            print(f"Power logging error: {e}")
            time.sleep(60)  # Bei Fehler auch 1 Minute warten

# === BASIC ROUTES ===
@app.route('/')
def index():
    # Check if onboarding is needed
    if not os.path.exists('.onboarding_completed'):
        return render_template('onboarding.html')
    return render_template('index.html')

@app.route('/onboarding')
def onboarding():
    return render_template('onboarding.html')

@app.route('/favicon.ico')
def favicon():
    return send_from_directory('public', 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/favicon-16x16.png')
def favicon_16():
    return send_from_directory('public', 'favicon-16x16.png', mimetype='image/png')

@app.route('/favicon-32x32.png')
def favicon_32():
    return send_from_directory('public', 'favicon-32x32.png', mimetype='image/png')

@app.route('/apple-touch-icon.png')
def apple_touch_icon():
    return send_from_directory('public', 'apple-touch-icon.png', mimetype='image/png')

@app.route('/android-chrome-192x192.png')
def android_chrome_192():
    return send_from_directory('public', 'android-chrome-192x192.png', mimetype='image/png')

@app.route('/android-chrome-512x512.png')
def android_chrome_512():
    return send_from_directory('public', 'android-chrome-512x512.png', mimetype='image/png')


@app.route('/site.webmanifest')
def site_webmanifest():
    manifest = {
        "name": "Hue by mrx3k1",
        "short_name": "HueController",
        "icons": [
            {
                "src": "/android-chrome-192x192.png",
                "sizes": "192x192",
                "type": "image/png"
            },
            {
                "src": "/android-chrome-512x512.png",
                "sizes": "512x512",
                "type": "image/png"
            }
        ],
        "theme_color": "#4ECDC4",
        "background_color": "#1a1a2e",
        "display": "standalone"
    }
    return jsonify(manifest)

@app.route('/api/lights', methods=['GET'])
@smart_error_handler('lights_list')
def get_lights():
    lights = hue_request('lights')
    
    # Unerreichbare Lichter als ausgeschaltet anzeigen (aber für Stromverbrauch weiter zählen)
    for light_id, light in lights.items():
        if not light.get('state', {}).get('reachable', True):
            # Für UI als ausgeschaltet markieren, aber Original-Status behalten für Power-Berechnung
            light['state']['on_display'] = False
        else:
            light['state']['on_display'] = light['state'].get('on', False)
    
    return jsonify(lights)

@app.route('/api/lights/<light_id>/state', methods=['PUT'])
@smart_error_handler('light_control')
def set_light_state(light_id):
    data = request.get_json()
    return jsonify(hue_request(f'lights/{light_id}/state', 'PUT', data))

@app.route('/api/groups', methods=['GET'])
@smart_error_handler('groups_list')
def get_groups():
    return jsonify(hue_request('groups'))

@app.route('/api/groups/<group_id>/action', methods=['PUT'])
@smart_error_handler('group_control')
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
@smart_error_handler('strobe_effect')
def start_strobe():
    """Legacy Strobo Effect (für Rückwärtskompatibilität)"""
    data = request.get_json()
    target_type = data.get('type', 'light')
    target_id = data.get('id')
    duration = data.get('duration', 10)
    interval = data.get('interval', 0.5)
    
    # Weiterleitung an neues System
    return start_advanced_strobe({
        'target_type': target_type,
        'target_id': target_id,
        'duration': duration,
        'frequency': 1.0 / interval,
        'hue': 0,
        'sat': 0,
        'bri': 254,
        'mode': 'single'
    })

@app.route('/api/effects/strobe/advanced', methods=['POST'])
@smart_error_handler('advanced_strobe_effect')
def start_advanced_strobe_endpoint():
    """Erweiterte Strobo Effect API"""
    data = request.get_json() or {}
    return start_advanced_strobe(data)

def start_advanced_strobe(config):
    """Erweiterte Strobo Effect Implementierung"""
    # Parameter validieren und Defaults setzen
    target_type = config.get('target_type', 'all')
    target_id = config.get('target_id', 'all')
    duration = config.get('duration', 0)  # 0 = unbegrenzt, sonst 1-300 Sekunden
    if duration > 0:
        duration = max(1, min(300, duration))
    frequency = max(0.1, min(10.0, config.get('frequency', 2.0)))  # 0.1-10 Hz
    
    # Farb-Parameter
    hue = config.get('hue', 0)  # 0-65535
    sat = config.get('sat', 254)  # 0-254
    bri = config.get('bri', 254)  # 1-254
    
    # Strobo-Modi
    mode = config.get('mode', 'single')  # 'single', 'multi', 'rainbow', 'beat'
    colors = config.get('colors', [])  # Für Multi-Color Mode
    
    effect_id = f"advanced_strobe_{target_type}_{target_id}_{int(frequency*10)}"
    
    def advanced_strobe_effect():
        start_time = time.time()
        cycle_time = 1.0 / frequency  # Zeit pro Zyklus
        on_time = cycle_time * 0.25   # 25% an, 75% aus für wilderes Strobo
        off_time = cycle_time * 0.75
        
        # Farbsequenz für verschiedene Modi
        color_sequence = []
        if mode == 'single':
            color_sequence = [{'hue': hue, 'sat': sat, 'bri': bri}]
        elif mode == 'multi' and colors:
            color_sequence = colors
        elif mode == 'rainbow':
            # Regenbogen-Sequenz
            color_sequence = [
                {'hue': 0, 'sat': 254, 'bri': bri},      # Rot
                {'hue': 10922, 'sat': 254, 'bri': bri},  # Grün
                {'hue': 46920, 'sat': 254, 'bri': bri},  # Blau
                {'hue': 21845, 'sat': 254, 'bri': bri},  # Gelb
                {'hue': 54613, 'sat': 254, 'bri': bri},  # Magenta
                {'hue': 32768, 'sat': 254, 'bri': bri},  # Cyan
            ]
        else:
            color_sequence = [{'hue': hue, 'sat': sat, 'bri': bri}]
        
        color_index = 0
        
        try:
            while (duration == 0 or time.time() - start_time < duration) and effect_id in running_effects:
                current_color = color_sequence[color_index % len(color_sequence)]
                
                # Lichter einschalten mit aktueller Farbe (maximum intensity)
                if target_type == 'all':
                    lights = get_lights_raw()
                    for light_id in lights.keys():
                        state = {'on': True, **current_color, 'bri': 254, 'transitiontime': 0}
                        hue_request(f'lights/{light_id}/state', 'PUT', state)
                else:
                    endpoint = f"{target_type}s/{target_id}/{'action' if target_type == 'group' else 'state'}"
                    state = {'on': True, **current_color, 'bri': 254, 'transitiontime': 0}
                    hue_request(endpoint, 'PUT', state)
                
                time.sleep(on_time)
                
                # Lichter ausschalten
                if target_type == 'all':
                    lights = get_lights_raw()
                    for light_id in lights.keys():
                        hue_request(f'lights/{light_id}/state', 'PUT', {'on': False, 'transitiontime': 0})
                else:
                    endpoint = f"{target_type}s/{target_id}/{'action' if target_type == 'group' else 'state'}"
                    hue_request(endpoint, 'PUT', {'on': False, 'transitiontime': 0})
                
                time.sleep(off_time)
                
                # Nächste Farbe bei Multi-Color Modi
                if mode in ['multi', 'rainbow']:
                    color_index += 1
                    
        except Exception as e:
            log_system_error(e, f"Strobo effect {effect_id}")
        finally:
            if effect_id in running_effects:
                del running_effects[effect_id]
                track_effect_usage('strobe', f'{mode}_strobe_{frequency}Hz', target_type, 
                                 effect_id=effect_id)
    
    if effect_id not in running_effects:
        running_effects[effect_id] = {
            'type': 'strobe',
            'mode': mode,
            'frequency': frequency,
            'start_time': time.time(),
            'config': config
        }
        threading.Thread(target=advanced_strobe_effect, daemon=True).start()
        return jsonify({
            "success": True, 
            "effect_id": effect_id,
            "message": f"{mode.title()}-Strobo gestartet ({frequency}Hz)",
            "config": config
        })
    
    return jsonify({"error": "Effect already running", "effect_id": effect_id})

@app.route('/api/effects/strobe/ultra', methods=['POST'])
@smart_error_handler('ultra_strobe_effect')
def start_ultra_strobe():
    """🔥 ULTRA-AGGRESSIVER BLITZ-STROBO - EPILEPSIE WARNUNG! 🔥"""
    data = request.get_json() or {}
    
    # Sicherheits-Validierung
    frequency = max(1, min(25, data.get('frequency', 10)))  # Max 25Hz für Sicherheit
    if frequency > 15:
        add_debug_log('warning', f'⚠️ EPILEPSIE WARNUNG: Strobo mit {frequency}Hz gestartet!')
    
    config = {
        'target_type': data.get('target_type', 'all'),
        'target_id': data.get('target_id', 'all'),
        'duration': min(60, data.get('duration', 10)),  # Max 60s für Ultra-Modi
        'frequency': frequency,
        'hue': data.get('hue', 0),
        'sat': data.get('sat', 254),
        'bri': data.get('bri', 254),
        'mode': data.get('mode', 'ultra'),
        'intensity': data.get('intensity', 1.0)
    }
    
    return start_ultra_strobe_effect(config)

def start_ultra_strobe_effect(config):
    """🚨 ULTRA-STROBO: Extrem aggressive Blitz-Effekte"""
    target_type = config['target_type']
    target_id = config.get('target_id', 'all')
    duration = config.get('duration', 0)  # 0 = unbegrenzt
    frequency = config['frequency']
    mode = config['mode']
    intensity = config.get('intensity', 1.0)
    
    # Basis-Farbparameter
    hue = config.get('hue', 0)
    sat = config.get('sat', 254)
    bri = int(config.get('bri', 254) * intensity)
    
    effect_id = f"ultra_strobe_{mode}_{target_type}_{target_id}_{int(frequency*10)}"
    
    def ultra_strobe_worker():
        start_time = time.time()
        add_debug_log('warning', f'🔥 ULTRA-STROBO gestartet: {mode} @ {frequency}Hz')
        
        try:
            if mode == 'ultra':
                # ULTRA-MODUS: Extremer Blitz
                flash_duration = 0.03  # 30ms Blitz
                pause_duration = max(0.01, (1.0 / frequency) - flash_duration)
                
                light_state = {'on': True, 'hue': hue, 'sat': sat, 'bri': bri}
                off_state = {'on': False}
                
                while (duration == 0 or time.time() - start_time < duration) and effect_id in running_effects:
                    ultra_fast_flash(light_state, off_state, flash_duration)
                    time.sleep(pause_duration)
                    
            elif mode == 'burst':
                # BURST-MODUS: 3-5 schnelle Blitze, dann Pause
                burst_count = 4
                burst_frequency = 15  # 15Hz für Burst
                pause_between_bursts = 0.5
                
                light_state = {'on': True, 'hue': hue, 'sat': sat, 'bri': bri}
                off_state = {'on': False}
                
                while (duration == 0 or time.time() - start_time < duration) and effect_id in running_effects:
                    # Burst-Sequenz
                    for _ in range(burst_count):
                        if effect_id not in running_effects:
                            break
                        ultra_fast_flash(light_state, off_state, 0.02)
                        time.sleep(1/burst_frequency - 0.02)
                    
                    time.sleep(pause_between_bursts)
                    
            elif mode == 'police':
                # POLIZEI-MODUS: Blau/Rot alternierend
                blue_state = {'on': True, 'hue': 46920, 'sat': 254, 'bri': bri}
                red_state = {'on': True, 'hue': 0, 'sat': 254, 'bri': bri}
                off_state = {'on': False}
                
                cycle_time = 1.0 / frequency
                is_blue = True
                
                while (duration == 0 or time.time() - start_time < duration) and effect_id in running_effects:
                    current_state = blue_state if is_blue else red_state
                    ultra_fast_flash(current_state, off_state, cycle_time * 0.3)
                    time.sleep(cycle_time * 0.1)
                    is_blue = not is_blue
                    
            elif mode == 'disco_flash':
                # DISCO-FLASH: Zufällige Farben, ultra-schnell
                import random
                colors = [
                    {'hue': 0, 'sat': 254, 'bri': bri},      # Rot
                    {'hue': 10922, 'sat': 254, 'bri': bri},  # Grün
                    {'hue': 46920, 'sat': 254, 'bri': bri},  # Blau
                    {'hue': 25500, 'sat': 254, 'bri': bri},  # Gelb
                    {'hue': 56100, 'sat': 254, 'bri': bri},  # Magenta
                    {'hue': 33000, 'sat': 254, 'bri': bri},  # Cyan
                ]
                off_state = {'on': False}
                
                flash_duration = 0.02
                pause_duration = max(0.01, (1.0 / frequency) - flash_duration)
                
                while (duration == 0 or time.time() - start_time < duration) and effect_id in running_effects:
                    color_state = random.choice(colors)
                    ultra_fast_flash(color_state, off_state, flash_duration)
                    time.sleep(pause_duration)
                    
        except Exception as e:
            log_system_error(e, f"Ultra strobo effect {effect_id}")
            add_debug_log('error', f'❌ Ultra-Strobo Fehler: {str(e)}')
        finally:
            # Sanfter Ausstieg
            if effect_id in running_effects:
                del running_effects[effect_id]
                batch_lights_control({'on': False, 'transitiontime': 10}, 'all')  # 1s sanfter Übergang
                add_debug_log('success', f'✅ Ultra-Strobo beendet: {mode}')
    
    if effect_id not in running_effects:
        running_effects[effect_id] = {
            'type': 'ultra_strobe',
            'mode': mode,
            'frequency': frequency,
            'start_time': time.time(),
            'config': config,
            'intensity': intensity
        }
        threading.Thread(target=ultra_strobe_worker, daemon=True).start()
        return jsonify({
            "success": True,
            "effect_id": effect_id,
            "message": f"🔥 ULTRA-STROBO {mode.upper()} gestartet ({frequency}Hz)",
            "warning": "⚠️ EPILEPSIE-WARNUNG bei hohen Frequenzen!",
            "config": config
        })
    
    return jsonify({"error": "Ultra-Strobo bereits aktiv", "effect_id": effect_id})

@app.route('/api/effects/strobe/emergency-stop', methods=['POST'])
def emergency_strobo_stop_endpoint():
    """🚨 NOTFALL-STOPP für alle Strobo-Effekte"""
    emergency_strobe_stop()
    return jsonify({
        "success": True,
        "message": "🚨 Alle Strobo-Effekte gestoppt - Notfall-Modus",
        "stopped_effects": "all"
    })

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
            if target_type == 'all':
                # Alle Lichter
                lights = get_lights_raw()
                for light_id in lights.keys():
                    hue_request(f'lights/{light_id}/state', 'PUT', {'on': True, 'hue': hue, 'sat': 254, 'bri': 254})
            else:
                # Einzelnes Licht oder Gruppe
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

# === ERWEITERTE LICHTEFFEKTE ===
@app.route('/api/effects/advanced/<effect_type>', methods=['POST'])
def start_advanced_effect(effect_type):
    """Erweiterte Lichteffekte starten"""
    data = request.get_json()
    target_type = data.get('type', 'all')
    duration = data.get('duration', 60)
    speed = data.get('speed', 1)
    
    effect_id = f"{effect_type}_{target_type}_advanced"
    
    # Erweiterte Parameter
    intensity = data.get('intensity', 1.0)  # 0.1 - 2.0
    color_palette = data.get('color_palette', 'full')  # 'warm', 'cool', 'neon', 'pastel', 'full'
    direction = data.get('direction', 'forward')  # 'forward', 'backward', 'ping_pong'
    
    config = {
        'target_type': target_type,
        'duration': duration,
        'speed': speed,
        'intensity': intensity,
        'color_palette': color_palette,
        'direction': direction
    }
    
    # Bestehende Effekte
    if effect_type == 'wave':
        return start_wave_effect(effect_id, config)
    elif effect_type == 'pulse':
        return start_pulse_effect(effect_id, config)
    elif effect_type == 'rainbow':
        return start_rainbow_effect(effect_id, config)
    elif effect_type == 'fire':
        return start_fire_effect(effect_id, config)
    elif effect_type == 'sunset':
        return start_sunset_effect(effect_id, config)
    elif effect_type == 'lightning':
        return start_lightning_effect(effect_id, config)
    
    # Neue erweiterte Effekte
    elif effect_type == 'plasma':
        return start_plasma_effect(effect_id, config)
    elif effect_type == 'matrix':
        return start_matrix_effect(effect_id, config)
    elif effect_type == 'breathe':
        return start_breathe_effect(effect_id, config)
    elif effect_type == 'tornado':
        return start_tornado_effect(effect_id, config)
    elif effect_type == 'explosion':
        return start_explosion_effect(effect_id, config)
    elif effect_type == 'kaleidoscope':
        return start_kaleidoscope_effect(effect_id, config)
    elif effect_type == 'lava':
        return start_lava_effect(effect_id, config)
    elif effect_type == 'twinkle':
        return start_twinkle_effect(effect_id, config)
    elif effect_type == 'disco':
        return start_disco_effect(effect_id, config)
    elif effect_type == 'aurora':
        return start_aurora_effect(effect_id, config)
    elif effect_type == 'sparkle':
        return start_sparkle_effect(effect_id, config)
    elif effect_type == 'comet':
        return start_comet_effect(effect_id, config)
    
    else:
        return jsonify({"error": "Unknown effect type", "available": [
            'wave', 'pulse', 'rainbow', 'fire', 'sunset', 'lightning',
            'plasma', 'matrix', 'breathe', 'tornado', 'explosion', 'kaleidoscope', 'lava',
            'twinkle', 'disco', 'aurora', 'sparkle', 'comet'
        ]})

def start_wave_effect(effect_id, target_type, duration, speed):
    """Raumwelle - Farben laufen durch alle Lichter"""
    import random
    
    def wave_effect():
        start_time = time.time()
        lights = get_lights_raw()
        light_ids = list(lights.keys())
        
        colors = [
            {"hue": 0, "sat": 254},      # Rot
            {"hue": 10922, "sat": 254},  # Grün  
            {"hue": 46920, "sat": 254},  # Blau
            {"hue": 25500, "sat": 254},  # Gelb
            {"hue": 56100, "sat": 254},  # Magenta
            {"hue": 33000, "sat": 254},  # Cyan
        ]
        
        while time.time() - start_time < duration and effect_id in running_effects:
            for i, light_id in enumerate(light_ids):
                if effect_id not in running_effects:
                    break
                    
                color = colors[i % len(colors)]
                hue_request(f'lights/{light_id}/state', 'PUT', {
                    'on': True,
                    'hue': color['hue'], 
                    'sat': color['sat'], 
                    'bri': 254,
                    'transitiontime': int(speed * 10)
                })
                time.sleep(speed / 2)
            
            # Farben rotieren
            colors = colors[1:] + [colors[0]]
            time.sleep(speed)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
    
    if effect_id not in running_effects:
        running_effects[effect_id] = True
        threading.Thread(target=wave_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id})
    
    return jsonify({"error": "Effect already running"})

def start_pulse_effect(effect_id, target_type, duration, speed):
    """Pulsieren - Rhythmisches Dimmen"""
    def pulse_effect():
        start_time = time.time()
        lights = get_lights_raw()
        
        while time.time() - start_time < duration and effect_id in running_effects:
            # Heller werden
            for light_id in lights.keys():
                hue_request(f'lights/{light_id}/state', 'PUT', {
                    'on': True,
                    'bri': 254,
                    'transitiontime': int(speed * 10)
                })
            time.sleep(speed)
            
            # Dunkler werden
            for light_id in lights.keys():
                hue_request(f'lights/{light_id}/state', 'PUT', {
                    'bri': 50,
                    'transitiontime': int(speed * 10)
                })
            time.sleep(speed)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
    
    if effect_id not in running_effects:
        running_effects[effect_id] = True
        threading.Thread(target=pulse_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id})
    
    return jsonify({"error": "Effect already running"})

def start_rainbow_effect(effect_id, target_type, duration, speed):
    """Regenbogen - Sanfte Farbübergänge"""
    def rainbow_effect():
        start_time = time.time()
        hue = 0
        lights = get_lights_raw()
        
        while time.time() - start_time < duration and effect_id in running_effects:
            for light_id in lights.keys():
                hue_request(f'lights/{light_id}/state', 'PUT', {
                    'on': True,
                    'hue': hue,
                    'sat': 254,
                    'bri': 200,
                    'transitiontime': int(speed * 30)
                })
            
            hue = (hue + 2000) % 65535
            time.sleep(speed * 2)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
    
    if effect_id not in running_effects:
        running_effects[effect_id] = True
        threading.Thread(target=rainbow_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id})
    
    return jsonify({"error": "Effect already running"})

def start_fire_effect(effect_id, target_type, duration, speed):
    """Feuereffekt - Warme, flackernde Farben"""
    import random
    
    def fire_effect():
        start_time = time.time()
        lights = get_lights_raw()
        
        fire_colors = [
            {"hue": 0, "sat": 254},      # Rot
            {"hue": 5000, "sat": 254},   # Orange-Rot
            {"hue": 8000, "sat": 254},   # Orange
            {"hue": 12000, "sat": 200},  # Gelb-Orange
        ]
        
        while time.time() - start_time < duration and effect_id in running_effects:
            for light_id in lights.keys():
                color = random.choice(fire_colors)
                brightness = random.randint(100, 254)
                
                hue_request(f'lights/{light_id}/state', 'PUT', {
                    'on': True,
                    'hue': color['hue'],
                    'sat': color['sat'],
                    'bri': brightness,
                    'transitiontime': random.randint(1, 5)
                })
            
            time.sleep(speed * 0.3)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
    
    if effect_id not in running_effects:
        running_effects[effect_id] = True
        threading.Thread(target=fire_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id})
    
    return jsonify({"error": "Effect already running"})

def start_sunset_effect(effect_id, target_type, duration, speed):
    """Sonnenuntergang - Automatische Farbtemperatur über Zeit"""
    def sunset_effect():
        start_time = time.time()
        lights = get_lights_raw()
        
        # Sonnenuntergang Farben (von Tageslicht zu warmweiß zu rot)
        sunset_phases = [
            {"hue": 0, "sat": 0, "bri": 254},      # Tageslicht
            {"hue": 5000, "sat": 100, "bri": 200}, # Warmes Weiß
            {"hue": 8000, "sat": 180, "bri": 150}, # Orange
            {"hue": 0, "sat": 254, "bri": 100},    # Rot
            {"hue": 0, "sat": 254, "bri": 50},     # Dunkles Rot
        ]
        
        phase_duration = duration / len(sunset_phases)
        
        for phase in sunset_phases:
            if effect_id not in running_effects:
                break
                
            for light_id in lights.keys():
                hue_request(f'lights/{light_id}/state', 'PUT', {
                    'on': True,
                    'hue': phase['hue'],
                    'sat': phase['sat'],
                    'bri': phase['bri'],
                    'transitiontime': int(phase_duration * 10)
                })
            
            time.sleep(phase_duration)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
    
    if effect_id not in running_effects:
        running_effects[effect_id] = True
        threading.Thread(target=sunset_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id})
    
    return jsonify({"error": "Effect already running"})

def start_lightning_effect(effect_id, target_type, duration, speed):
    """Blitzeffekt - Zufällige Blitze"""
    import random
    
    def lightning_effect():
        start_time = time.time()
        lights = get_lights_raw()
        light_ids = list(lights.keys())
        
        while time.time() - start_time < duration and effect_id in running_effects:
            # Zufälliges Licht auswählen
            light_id = random.choice(light_ids)
            
            # Blitz
            hue_request(f'lights/{light_id}/state', 'PUT', {
                'on': True,
                'hue': 0,
                'sat': 0,
                'bri': 254,
                'transitiontime': 0
            })
            
            time.sleep(0.1)
            
            # Zurück zu dunkel
            hue_request(f'lights/{light_id}/state', 'PUT', {
                'bri': 30,
                'transitiontime': 2
            })
            
            # Zufällige Pause zwischen Blitzen
            time.sleep(random.uniform(1, speed * 3))
        
        if effect_id in running_effects:
            del running_effects[effect_id]
    
    if effect_id not in running_effects:
        running_effects[effect_id] = True
        threading.Thread(target=lightning_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id})
    
    return jsonify({"error": "Effect already running"})

# === HILFSFUNKTIONEN FÜR EFFEKTE ===

def get_color_palette(palette_name, base_brightness=200):
    """Definierte Farbpaletten für Effekte"""
    palettes = {
        'warm': [
            {'hue': 5000, 'sat': 254, 'bri': base_brightness},   # Warm Orange
            {'hue': 8000, 'sat': 254, 'bri': base_brightness},   # Rötlich Orange  
            {'hue': 12000, 'sat': 200, 'bri': base_brightness},  # Warm Gelb
            {'hue': 0, 'sat': 200, 'bri': base_brightness},      # Warm Rot
        ],
        'cool': [
            {'hue': 43000, 'sat': 254, 'bri': base_brightness},  # Blau
            {'hue': 50000, 'sat': 254, 'bri': base_brightness},  # Indigo
            {'hue': 46920, 'sat': 254, 'bri': base_brightness},  # Cyan
            {'hue': 35000, 'sat': 200, 'bri': base_brightness},  # Türkis
        ],
        'neon': [
            {'hue': 65000, 'sat': 254, 'bri': 254},              # Neon Pink
            {'hue': 25500, 'sat': 254, 'bri': 254},              # Neon Grün
            {'hue': 46920, 'sat': 254, 'bri': 254},              # Neon Blau
            {'hue': 21845, 'sat': 254, 'bri': 254},              # Neon Gelb
        ],
        'pastel': [
            {'hue': 65000, 'sat': 100, 'bri': 180},              # Pastell Pink
            {'hue': 25500, 'sat': 100, 'bri': 180},              # Pastell Grün  
            {'hue': 46920, 'sat': 100, 'bri': 180},              # Pastell Blau
            {'hue': 21845, 'sat': 100, 'bri': 180},              # Pastell Gelb
        ],
        'full': [
            {'hue': 0, 'sat': 254, 'bri': base_brightness},      # Rot
            {'hue': 10922, 'sat': 254, 'bri': base_brightness},  # Grün
            {'hue': 46920, 'sat': 254, 'bri': base_brightness},  # Blau
            {'hue': 21845, 'sat': 254, 'bri': base_brightness},  # Gelb
            {'hue': 54613, 'sat': 254, 'bri': base_brightness},  # Magenta
            {'hue': 32768, 'sat': 254, 'bri': base_brightness},  # Cyan
        ]
    }
    return palettes.get(palette_name, palettes['full'])

def apply_effect_to_lights(target_type, target_id, state, transition_time=0):
    """Hilfsfunktion um Effekte auf Lichter anzuwenden"""
    try:
        if target_type == 'all':
            lights = get_lights_raw()
            for light_id in lights.keys():
                state_with_transition = {**state, 'transitiontime': transition_time}
                hue_request(f'lights/{light_id}/state', 'PUT', state_with_transition)
        else:
            endpoint = f"{target_type}s/{target_id}/{'action' if target_type == 'group' else 'state'}"
            state_with_transition = {**state, 'transitiontime': transition_time}
            hue_request(endpoint, 'PUT', state_with_transition)
    except Exception as e:
        print(f"Error applying effect: {e}")

# === NEUE ERWEITERTE EFFEKTE ===

def start_plasma_effect(effect_id, config):
    """Plasma-Effekt - Sanfte Farbwellen"""
    import math
    
    def plasma_effect():
        start_time = time.time()
        target_type = config['target_type']
        target_id = config.get('target_id', 'all')
        duration = config['duration']
        speed = config['speed']
        intensity = config['intensity']
        
        colors = get_color_palette(config['color_palette'])
        
        frame = 0
        while time.time() - start_time < duration and effect_id in running_effects:
            # Plasma-Algorithmus mit Sinus-Wellen
            plasma_time = (time.time() - start_time) * speed
            
            lights = get_lights_raw() if target_type == 'all' else []
            light_ids = list(lights.keys()) if lights else [target_id]
            
            for i, light_id in enumerate(light_ids):
                if effect_id not in running_effects:
                    break
                
                # Plasma-Berechnung
                plasma_val = (
                    math.sin(plasma_time + i * 0.5) +
                    math.sin(plasma_time * 1.5 + i * 0.3) +
                    math.sin(plasma_time * 0.8 + i * 0.8)
                ) / 3
                
                # Farbe basierend auf Plasma-Wert
                color_idx = int((plasma_val + 1) * len(colors) / 2) % len(colors)
                color = colors[color_idx]
                
                brightness = int(color['bri'] * intensity)
                
                apply_effect_to_lights('light', light_id, {
                    'on': True,
                    'hue': color['hue'],
                    'sat': color['sat'],
                    'bri': max(10, min(254, brightness))
                }, transition_time=int(10 / speed))
            
            time.sleep(0.1 / speed)
            frame += 1
        
        if effect_id in running_effects:
            del running_effects[effect_id]
            track_effect_usage('plasma', 'plasma_effect', target_type, effect_id=effect_id)
    
    if effect_id not in running_effects:
        running_effects[effect_id] = {
            'type': 'plasma',
            'start_time': time.time(),
            'config': config
        }
        threading.Thread(target=plasma_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id, "message": "Plasma-Effekt gestartet"})
    
    return jsonify({"error": "Effect already running"})

def start_matrix_effect(effect_id, config):
    """Matrix-Effekt - Digitaler Rain"""
    import random
    
    def matrix_effect():
        start_time = time.time()
        target_type = config['target_type']
        target_id = config.get('target_id', 'all')
        duration = config['duration']
        speed = config['speed']
        
        # Matrix-Farben (grün dominiert)
        matrix_colors = [
            {'hue': 25500, 'sat': 254, 'bri': 254},  # Helles Grün
            {'hue': 25500, 'sat': 254, 'bri': 180},  # Mittel Grün
            {'hue': 25500, 'sat': 254, 'bri': 100},  # Dunkles Grün
            {'hue': 0, 'sat': 0, 'bri': 50},         # Fast schwarz
        ]
        
        lights = get_lights_raw() if target_type == 'all' else []
        light_ids = list(lights.keys()) if lights else [target_id]
        
        # Matrix-Kaskaden für jedes Licht
        cascades = {light_id: {'active': False, 'step': 0} for light_id in light_ids}
        
        while time.time() - start_time < duration and effect_id in running_effects:
            # Neue Kaskaden starten
            if random.random() < 0.3 * speed:
                inactive_lights = [lid for lid, data in cascades.items() if not data['active']]
                if inactive_lights:
                    light_id = random.choice(inactive_lights)
                    cascades[light_id] = {'active': True, 'step': 0}
            
            # Kaskaden-Updates
            for light_id, cascade in cascades.items():
                if effect_id not in running_effects:
                    break
                    
                if cascade['active']:
                    step = cascade['step']
                    color_idx = min(step, len(matrix_colors) - 1)
                    color = matrix_colors[color_idx]
                    
                    apply_effect_to_lights('light', light_id, {
                        'on': True if color['bri'] > 50 else False,
                        'hue': color['hue'],
                        'sat': color['sat'],
                        'bri': color['bri']
                    })
                    
                    cascade['step'] += 1
                    if cascade['step'] >= len(matrix_colors):
                        cascade['active'] = False
                        cascade['step'] = 0
            
            time.sleep(0.2 / speed)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
            track_effect_usage('matrix', 'matrix_effect', target_type, effect_id=effect_id)
    
    if effect_id not in running_effects:
        running_effects[effect_id] = {
            'type': 'matrix',
            'start_time': time.time(),
            'config': config
        }
        threading.Thread(target=matrix_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id, "message": "Matrix-Effekt gestartet"})
    
    return jsonify({"error": "Effect already running"})

def start_breathe_effect(effect_id, config):
    """Breathe-Effekt - Rhythmisches Pulsieren"""
    import math
    
    def breathe_effect():
        start_time = time.time()
        target_type = config['target_type']
        target_id = config.get('target_id', 'all')
        duration = config['duration']
        speed = config['speed']
        intensity = config['intensity']
        
        colors = get_color_palette(config['color_palette'])
        base_color = colors[0]  # Hauptfarbe für Breathe
        
        while time.time() - start_time < duration and effect_id in running_effects:
            # Sinus-Welle für Breathe-Effekt
            breathe_time = (time.time() - start_time) * speed
            breathe_val = (math.sin(breathe_time) + 1) / 2  # 0-1
            
            # Helligkeit basierend auf Breathe-Wert
            min_brightness = 30
            max_brightness = int(base_color['bri'] * intensity)
            brightness = int(min_brightness + (max_brightness - min_brightness) * breathe_val)
            
            apply_effect_to_lights(target_type, target_id, {
                'on': True,
                'hue': base_color['hue'],
                'sat': base_color['sat'],
                'bri': brightness
            }, transition_time=int(15 / speed))
            
            time.sleep(0.1)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
            track_effect_usage('breathe', 'breathe_effect', target_type, effect_id=effect_id)
    
    if effect_id not in running_effects:
        running_effects[effect_id] = {
            'type': 'breathe',
            'start_time': time.time(),
            'config': config
        }
        threading.Thread(target=breathe_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id, "message": "Breathe-Effekt gestartet"})
    
    return jsonify({"error": "Effect already running"})

def start_tornado_effect(effect_id, config):
    """Tornado-Effekt - Spiralförmige Farbrotation"""
    import math
    
    def tornado_effect():
        start_time = time.time()
        target_type = config['target_type']
        target_id = config.get('target_id', 'all')
        duration = config['duration']
        speed = config['speed']
        
        colors = get_color_palette(config['color_palette'])
        
        lights = get_lights_raw() if target_type == 'all' else []
        light_ids = list(lights.keys()) if lights else [target_id]
        
        while time.time() - start_time < duration and effect_id in running_effects:
            tornado_time = (time.time() - start_time) * speed
            
            for i, light_id in enumerate(light_ids):
                if effect_id not in running_effects:
                    break
                
                # Spirale basierend auf Position und Zeit
                spiral_offset = tornado_time + (i * 2 * math.pi / len(light_ids))
                color_phase = (math.sin(spiral_offset) + 1) / 2
                
                color_idx = int(color_phase * len(colors)) % len(colors)
                color = colors[color_idx]
                
                # Helligkeit basierend auf Spirale
                brightness_factor = (math.cos(spiral_offset * 2) + 1) / 2
                brightness = int(color['bri'] * (0.3 + 0.7 * brightness_factor))
                
                apply_effect_to_lights('light', light_id, {
                    'on': True,
                    'hue': color['hue'],
                    'sat': color['sat'],
                    'bri': max(30, brightness)
                })
            
            time.sleep(0.15 / speed)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
            track_effect_usage('tornado', 'tornado_effect', target_type, effect_id=effect_id)
    
    if effect_id not in running_effects:
        running_effects[effect_id] = {
            'type': 'tornado',
            'start_time': time.time(),
            'config': config
        }
        threading.Thread(target=tornado_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id, "message": "Tornado-Effekt gestartet"})
    
    return jsonify({"error": "Effect already running"})

def start_explosion_effect(effect_id, config):
    """Explosion-Effekt - Vom Zentrum ausbreitende Wellen"""
    import math
    
    def explosion_effect():
        start_time = time.time()
        target_type = config['target_type']
        target_id = config.get('target_id', 'all')
        duration = config['duration']
        speed = config['speed']
        intensity = config['intensity']
        
        colors = get_color_palette(config['color_palette'])
        
        lights = get_lights_raw() if target_type == 'all' else []
        light_ids = list(lights.keys()) if lights else [target_id]
        
        explosion_cycles = 0
        cycle_duration = 3.0 / speed  # Dauer einer Explosion
        
        while time.time() - start_time < duration and effect_id in running_effects:
            cycle_time = time.time() - start_time - (explosion_cycles * cycle_duration)
            
            if cycle_time >= cycle_duration:
                explosion_cycles += 1
                cycle_time = 0
            
            # Explosion-Welle
            wave_progress = cycle_time / cycle_duration
            
            for i, light_id in enumerate(light_ids):
                if effect_id not in running_effects:
                    break
                
                # Distanz vom "Zentrum" (erstes Licht)
                distance_factor = i / max(1, len(light_ids) - 1)
                
                # Welle erreicht dieses Licht
                if wave_progress >= distance_factor:
                    wave_intensity = 1.0 - ((wave_progress - distance_factor) * 2)
                    wave_intensity = max(0, wave_intensity)
                    
                    color = colors[explosion_cycles % len(colors)]
                    brightness = int(color['bri'] * wave_intensity * intensity)
                    
                    apply_effect_to_lights('light', light_id, {
                        'on': True if brightness > 30 else False,
                        'hue': color['hue'],
                        'sat': color['sat'],
                        'bri': max(10, brightness)
                    })
                else:
                    # Noch nicht erreicht - dunkel
                    apply_effect_to_lights('light', light_id, {'on': False})
            
            time.sleep(0.1)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
            track_effect_usage('explosion', 'explosion_effect', target_type, effect_id=effect_id)
    
    if effect_id not in running_effects:
        running_effects[effect_id] = {
            'type': 'explosion',
            'start_time': time.time(),
            'config': config
        }
        threading.Thread(target=explosion_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id, "message": "Explosion-Effekt gestartet"})
    
    return jsonify({"error": "Effect already running"})

def start_kaleidoscope_effect(effect_id, config):
    """Kaleidoskop-Effekt - Symmetrische Farbmuster"""
    import math
    
    def kaleidoscope_effect():
        start_time = time.time()
        target_type = config['target_type']
        target_id = config.get('target_id', 'all')
        duration = config['duration']
        speed = config['speed']
        
        colors = get_color_palette(config['color_palette'])
        
        lights = get_lights_raw() if target_type == 'all' else []
        light_ids = list(lights.keys()) if lights else [target_id]
        
        while time.time() - start_time < duration and effect_id in running_effects:
            kaleidoscope_time = (time.time() - start_time) * speed
            
            for i, light_id in enumerate(light_ids):
                if effect_id not in running_effects:
                    break
                
                # Kaleidoskop-Muster basierend auf Position
                pattern_val = math.sin(kaleidoscope_time + i * 0.5) * math.cos(kaleidoscope_time * 0.7 + i * 0.3)
                
                # Symmetrie durch Spiegelung
                mirrored_i = len(light_ids) - 1 - i
                mirror_pattern = math.sin(kaleidoscope_time + mirrored_i * 0.5)
                
                combined_pattern = (pattern_val + mirror_pattern) / 2
                
                # Farbe basierend auf Muster
                color_phase = (combined_pattern + 1) / 2
                color_idx = int(color_phase * len(colors)) % len(colors)
                color = colors[color_idx]
                
                # Helligkeit basierend auf Muster-Intensität
                brightness = int(color['bri'] * (0.4 + 0.6 * abs(combined_pattern)))
                
                apply_effect_to_lights('light', light_id, {
                    'on': True,
                    'hue': color['hue'],
                    'sat': color['sat'],
                    'bri': max(40, brightness)
                })
            
            time.sleep(0.12 / speed)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
            track_effect_usage('kaleidoscope', 'kaleidoscope_effect', target_type, effect_id=effect_id)
    
    if effect_id not in running_effects:
        running_effects[effect_id] = {
            'type': 'kaleidoscope',
            'start_time': time.time(),
            'config': config
        }
        threading.Thread(target=kaleidoscope_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id, "message": "Kaleidoskop-Effekt gestartet"})
    
    return jsonify({"error": "Effect already running"})

def start_lava_effect(effect_id, config):
    """Lava-Lampe-Effekt - Langsame, organische Übergänge"""
    import random
    import math
    
    def lava_effect():
        start_time = time.time()
        target_type = config['target_type']
        target_id = config.get('target_id', 'all')
        duration = config['duration']
        speed = config['speed']
        
        # Lava-Farben (warm dominiert)
        lava_colors = [
            {'hue': 5000, 'sat': 254, 'bri': 200},   # Orange
            {'hue': 0, 'sat': 254, 'bri': 180},      # Rot
            {'hue': 8000, 'sat': 220, 'bri': 160},   # Dunkelorange
            {'hue': 12000, 'sat': 200, 'bri': 140},  # Dunkelgelb
        ]
        
        lights = get_lights_raw() if target_type == 'all' else []
        light_ids = list(lights.keys()) if lights else [target_id]
        
        # Lava-Blasen für jedes Licht
        lava_states = {}
        for light_id in light_ids:
            lava_states[light_id] = {
                'target_color': random.choice(lava_colors),
                'current_phase': random.uniform(0, 2 * math.pi),
                'change_time': random.uniform(5, 15) / speed
            }
        
        while time.time() - start_time < duration and effect_id in running_effects:
            current_time = time.time() - start_time
            
            for light_id in light_ids:
                if effect_id not in running_effects:
                    break
                
                state = lava_states[light_id]
                
                # Langsame Phasen-Änderung
                state['current_phase'] += 0.02 * speed
                
                # Gelegentlich neue Zielfarbe
                if random.random() < 0.01 * speed:
                    state['target_color'] = random.choice(lava_colors)
                
                # Organische Helligkeit basierend auf Sinus-Welle
                brightness_factor = (math.sin(state['current_phase']) + 1) / 2
                brightness_factor = 0.3 + 0.7 * brightness_factor  # 30-100%
                
                brightness = int(state['target_color']['bri'] * brightness_factor)
                
                apply_effect_to_lights('light', light_id, {
                    'on': True,
                    'hue': state['target_color']['hue'],
                    'sat': state['target_color']['sat'],
                    'bri': max(30, brightness)
                }, transition_time=20)  # Langsame Übergänge
            
            time.sleep(0.5)  # Sehr langsam für Lava-Effekt
        
        if effect_id in running_effects:
            del running_effects[effect_id]
            track_effect_usage('lava', 'lava_effect', target_type, effect_id=effect_id)
    
    if effect_id not in running_effects:
        running_effects[effect_id] = {
            'type': 'lava',
            'start_time': time.time(),
            'config': config
        }
        threading.Thread(target=lava_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id, "message": "Lava-Lampe-Effekt gestartet"})
    
    return jsonify({"error": "Effect already running"})

def start_twinkle_effect(effect_id, config):
    """Twinkle-Effekt - Zufällige Lichter blinken wie Sterne"""
    import random
    
    def twinkle_effect():
        start_time = time.time()
        target_type = config['target_type']
        target_id = config.get('target_id', 'all')
        duration = config['duration']
        speed = config['speed']
        intensity = config['intensity']
        
        colors = get_color_palette(config['color_palette'])
        
        # Alle Lichter verfügbar machen
        lights = get_lights_raw()
        light_ids = list(lights.keys())
        
        # Basis-Zustand: Alle Lichter dimm
        base_brightness = 30
        
        while time.time() - start_time < duration and effect_id in running_effects:
            # Zufällige Lichter zum Funkeln auswählen
            num_twinkles = max(1, int(len(light_ids) * 0.3))  # 30% der Lichter
            twinkle_lights = random.sample(light_ids, num_twinkles)
            
            # Alle Lichter auf Basis-Helligkeit
            for light_id in light_ids:
                if light_id in twinkle_lights:
                    # Funkelnde Lichter
                    color = random.choice(colors)
                    brightness = random.randint(150, 254)
                    
                    hue_request(f'lights/{light_id}/state', 'PUT', {
                        'on': True,
                        'hue': color['hue'],
                        'sat': color['sat'],
                        'bri': int(brightness * intensity),
                        'transitiontime': 1
                    })
                else:
                    # Basis-Lichter
                    base_color = colors[0]
                    hue_request(f'lights/{light_id}/state', 'PUT', {
                        'on': True,
                        'hue': base_color['hue'],
                        'sat': int(base_color['sat'] * 0.5),
                        'bri': base_brightness,
                        'transitiontime': 20
                    })
            
            time.sleep(0.5 / speed)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
            track_effect_usage('twinkle', 'twinkle_effect', target_type, effect_id=effect_id)
    
    if effect_id not in running_effects:
        running_effects[effect_id] = {
            'type': 'twinkle',
            'start_time': time.time(),
            'config': config
        }
        threading.Thread(target=twinkle_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id, "message": "Twinkle-Effekt gestartet"})
    
    return jsonify({"error": "Effect already running"})

def start_disco_effect(effect_id, config):
    """Disco-Effekt - Schnelle, bunte Farbwechsel"""
    import random
    
    def disco_effect():
        start_time = time.time()
        target_type = config['target_type']
        target_id = config.get('target_id', 'all')
        duration = config['duration']
        speed = config['speed']
        intensity = config['intensity']
        
        # Disco-Farbpalette - knallige Farben
        disco_colors = [
            {'hue': 0, 'sat': 254, 'bri': 254},      # Rot
            {'hue': 10922, 'sat': 254, 'bri': 254},  # Grün
            {'hue': 46920, 'sat': 254, 'bri': 254},  # Blau
            {'hue': 25500, 'sat': 254, 'bri': 254},  # Gelb
            {'hue': 56100, 'sat': 254, 'bri': 254},  # Magenta
            {'hue': 33000, 'sat': 254, 'bri': 254},  # Cyan
            {'hue': 65000, 'sat': 254, 'bri': 254},  # Rosa
            {'hue': 12750, 'sat': 254, 'bri': 254},  # Orange
        ]
        
        lights = get_lights_raw()
        light_ids = list(lights.keys())
        
        while time.time() - start_time < duration and effect_id in running_effects:
            # Jedes Licht bekommt eine zufällige Farbe
            for light_id in light_ids:
                color = random.choice(disco_colors)
                brightness = random.randint(200, 254) if random.random() > 0.1 else 0
                
                hue_request(f'lights/{light_id}/state', 'PUT', {
                    'on': brightness > 0,
                    'hue': color['hue'],
                    'sat': color['sat'],
                    'bri': int(brightness * intensity),
                    'transitiontime': 0  # Schnelle Wechsel
                })
            
            time.sleep(0.1 / speed)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
            track_effect_usage('disco', 'disco_effect', target_type, effect_id=effect_id)
    
    if effect_id not in running_effects:
        running_effects[effect_id] = {
            'type': 'disco',
            'start_time': time.time(),
            'config': config
        }
        threading.Thread(target=disco_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id, "message": "Disco-Effekt gestartet"})
    
    return jsonify({"error": "Effect already running"})

def start_aurora_effect(effect_id, config):
    """Aurora-Effekt - Nordlicht-ähnliche sanfte Farbwellen"""
    import math
    
    def aurora_effect():
        start_time = time.time()
        target_type = config['target_type']
        target_id = config.get('target_id', 'all')
        duration = config['duration']
        speed = config['speed']
        intensity = config['intensity']
        
        # Aurora-Farbpalette - kühle, sanfte Farben
        aurora_colors = [
            {'hue': 46920, 'sat': 200, 'bri': 180},  # Blau
            {'hue': 33000, 'sat': 200, 'bri': 180},  # Cyan
            {'hue': 10922, 'sat': 180, 'bri': 160},  # Grün
            {'hue': 25500, 'sat': 150, 'bri': 140},  # Gelb-Grün
            {'hue': 56100, 'sat': 180, 'bri': 160},  # Magenta
        ]
        
        lights = get_lights_raw()
        light_ids = list(lights.keys())
        
        while time.time() - start_time < duration and effect_id in running_effects:
            current_time = time.time() - start_time
            
            for i, light_id in enumerate(light_ids):
                # Verschiedene Phasen für verschiedene Lichter
                phase = (current_time * speed + i * 0.5) % (2 * math.pi)
                
                # Sanfte Wellen für Aurora-Effekt
                wave1 = (math.sin(phase) + 1) / 2
                wave2 = (math.sin(phase * 1.3 + 1) + 1) / 2
                wave3 = (math.sin(phase * 0.7 + 2) + 1) / 2
                
                # Farbmischung basierend auf Wellen
                color_index = int((wave1 + wave2) * len(aurora_colors) / 2) % len(aurora_colors)
                color = aurora_colors[color_index]
                
                # Helligkeit basierend auf Wellen
                brightness = int((wave1 * 0.4 + wave2 * 0.3 + wave3 * 0.3) * color['bri'] * intensity)
                brightness = max(30, min(254, brightness))
                
                hue_request(f'lights/{light_id}/state', 'PUT', {
                    'on': True,
                    'hue': color['hue'],
                    'sat': color['sat'],
                    'bri': brightness,
                    'transitiontime': 30  # Sanfte Übergänge
                })
            
            time.sleep(0.2)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
            track_effect_usage('aurora', 'aurora_effect', target_type, effect_id=effect_id)
    
    if effect_id not in running_effects:
        running_effects[effect_id] = {
            'type': 'aurora',
            'start_time': time.time(),
            'config': config
        }
        threading.Thread(target=aurora_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id, "message": "Aurora-Effekt gestartet"})
    
    return jsonify({"error": "Effect already running"})

def start_sparkle_effect(effect_id, config):
    """Sparkle-Effekt - Kurze, intensive Lichtblitze"""
    import random
    
    def sparkle_effect():
        start_time = time.time()
        target_type = config['target_type']
        target_id = config.get('target_id', 'all')
        duration = config['duration']
        speed = config['speed']
        intensity = config['intensity']
        
        colors = get_color_palette(config['color_palette'])
        lights = get_lights_raw()
        light_ids = list(lights.keys())
        
        # Basis-Zustand: Alle Lichter aus oder sehr dimm
        base_brightness = 20
        
        while time.time() - start_time < duration and effect_id in running_effects:
            # Zufällige Lichter für Sparkle
            num_sparkles = max(1, int(len(light_ids) * 0.2))  # 20% der Lichter
            sparkle_lights = random.sample(light_ids, num_sparkles)
            
            # Sparkle-Phase
            for light_id in sparkle_lights:
                color = random.choice(colors)
                hue_request(f'lights/{light_id}/state', 'PUT', {
                    'on': True,
                    'hue': color['hue'],
                    'sat': color['sat'],
                    'bri': int(254 * intensity),
                    'transitiontime': 0
                })
            
            time.sleep(0.1 / speed)
            
            # Zurück zu Basis-Helligkeit
            for light_id in sparkle_lights:
                hue_request(f'lights/{light_id}/state', 'PUT', {
                    'on': True,
                    'bri': base_brightness,
                    'transitiontime': 5
                })
            
            time.sleep(0.3 / speed)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
            track_effect_usage('sparkle', 'sparkle_effect', target_type, effect_id=effect_id)
    
    if effect_id not in running_effects:
        running_effects[effect_id] = {
            'type': 'sparkle',
            'start_time': time.time(),
            'config': config
        }
        threading.Thread(target=sparkle_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id, "message": "Sparkle-Effekt gestartet"})
    
    return jsonify({"error": "Effect already running"})

def start_comet_effect(effect_id, config):
    """Comet-Effekt - Lichtschweif der durch die Lichter wandert"""
    def comet_effect():
        start_time = time.time()
        target_type = config['target_type']
        target_id = config.get('target_id', 'all')
        duration = config['duration']
        speed = config['speed']
        intensity = config['intensity']
        
        colors = get_color_palette(config['color_palette'])
        main_color = colors[0]
        
        lights = get_lights_raw()
        light_ids = list(lights.keys())
        
        if len(light_ids) < 2:
            return
        
        comet_length = min(5, len(light_ids))  # Schweif-Länge
        current_position = 0
        direction = 1 if config['direction'] == 'forward' else -1
        
        while time.time() - start_time < duration and effect_id in running_effects:
            # Alle Lichter ausschalten
            for light_id in light_ids:
                hue_request(f'lights/{light_id}/state', 'PUT', {
                    'on': False,
                    'transitiontime': 0
                })
            
            # Comet-Schweif erstellen
            for i in range(comet_length):
                pos = (current_position - i * direction) % len(light_ids)
                if pos >= 0 and pos < len(light_ids):
                    light_id = light_ids[pos]
                    
                    # Helligkeit nimmt zum Schweif hin ab
                    brightness_factor = (comet_length - i) / comet_length
                    brightness = int(main_color['bri'] * brightness_factor * intensity)
                    
                    hue_request(f'lights/{light_id}/state', 'PUT', {
                        'on': True,
                        'hue': main_color['hue'],
                        'sat': main_color['sat'],
                        'bri': max(10, brightness),
                        'transitiontime': 0
                    })
            
            # Position bewegen
            current_position = (current_position + direction) % len(light_ids)
            
            # Richtung wechseln bei ping_pong
            if config['direction'] == 'ping_pong':
                if current_position == 0 or current_position == len(light_ids) - 1:
                    direction *= -1
            
            time.sleep(0.3 / speed)
        
        if effect_id in running_effects:
            del running_effects[effect_id]
            track_effect_usage('comet', 'comet_effect', target_type, effect_id=effect_id)
    
    if effect_id not in running_effects:
        running_effects[effect_id] = {
            'type': 'comet',
            'start_time': time.time(),
            'config': config
        }
        threading.Thread(target=comet_effect, daemon=True).start()
        return jsonify({"success": True, "effect_id": effect_id, "message": "Comet-Effekt gestartet"})
    
    return jsonify({"error": "Effect already running"})

# === DEBUG API ===
@app.route('/api/debug/logs', methods=['GET'])
def get_debug_logs():
    """Debug-Logs abrufen"""
    global debug_logs, debug_stats
    return jsonify({
        "logs": debug_logs[-100:],  # Letzte 100 Logs
        "stats": debug_stats
    })

@app.route('/api/debug/clear', methods=['POST'])
def clear_debug_logs():
    """Debug-Logs löschen"""
    global debug_logs, debug_stats
    debug_logs.clear()
    debug_stats['total_requests'] = 0
    debug_stats['error_count'] = 0
    add_debug_log('info', 'Debug-Logs gelöscht')
    return jsonify({"success": True})

@app.route('/api/debug/test/connection', methods=['POST'])
def debug_test_hue_connection():
    """Hue Bridge Verbindung testen"""
    add_debug_log('info', '🔍 Bridge-Verbindung wird getestet...')
    try:
        result = hue_request('config')
        if 'error' in result:
            add_debug_log('error', f'Bridge-Test fehlgeschlagen: {result["error"]}')
            return jsonify({"success": False, "error": result["error"]})
        else:
            bridge_name = result.get('name', 'Unknown')
            add_debug_log('success', f'✅ Bridge-Test erfolgreich: {bridge_name}')
            return jsonify({"success": True, "bridge_name": bridge_name})
    except Exception as e:
        add_debug_log('error', f'Bridge-Test Exception: {str(e)}')
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/debug/test/light', methods=['POST'])
def debug_test_light_command():
    """Test-Lichtbefehl senden"""
    add_debug_log('info', '💡 Licht-Test wird gesendet...')
    try:
        # Erstes verfügbares Licht finden
        lights = hue_request('lights')
        if lights and not 'error' in lights:
            first_light = list(lights.keys())[0]
            # Kurz blinken lassen
            hue_request(f'lights/{first_light}/state', 'PUT', {'alert': 'select'})
            add_debug_log('success', f'✅ Licht {first_light} Test-Blink gesendet')
            return jsonify({"success": True, "light_id": first_light})
        else:
            add_debug_log('error', 'Keine Lichter gefunden')
            return jsonify({"success": False, "error": "Keine Lichter gefunden"})
    except Exception as e:
        add_debug_log('error', f'Licht-Test Exception: {str(e)}')
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/debug/test/group', methods=['POST'])
def debug_test_group_command():
    """Test-Gruppenbefehl senden"""
    add_debug_log('info', '🏠 Gruppen-Test wird gesendet...')
    try:
        # Gruppe 0 (alle Lichter) kurz blinken lassen
        result = hue_request('groups/0/action', 'PUT', {'alert': 'select'})
        if 'error' in str(result):
            add_debug_log('error', f'Gruppen-Test fehlgeschlagen: {result}')
            return jsonify({"success": False, "error": str(result)})
        else:
            add_debug_log('success', '✅ Alle Lichter Test-Blink gesendet')
            return jsonify({"success": True})
    except Exception as e:
        add_debug_log('error', f'Gruppen-Test Exception: {str(e)}')
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/debug/test/strobe', methods=['POST'])
def debug_test_strobe_effect():
    """Test-Strobo für 3 Sekunden"""
    add_debug_log('info', '⚡ Test-Strobo wird gestartet (3s)...')
    try:
        config = {
            'target_type': 'all',
            'duration': 3,
            'frequency': 5.0,
            'hue': 0,
            'sat': 254,
            'bri': 254,
            'mode': 'single'
        }
        result = start_advanced_strobe(config)
        add_debug_log('success', '✅ Test-Strobo gestartet')
        return result
    except Exception as e:
        add_debug_log('error', f'Test-Strobo Exception: {str(e)}')
        return jsonify({"success": False, "error": str(e)})

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

# === ERWEITERTE STIMMUNGSSZENEN ===
@app.route('/api/mood-scenes/<scene_type>', methods=['POST'])
def activate_mood_scene(scene_type):
    """Aktiviere erweiterte Stimmungsszenen"""
    
    # 20 Stimmungsszenen mit detaillierten Parametern
    mood_scenes = {
        # Natürliche Szenen
        'sunrise': {
            'name': 'Sonnenaufgang',
            'description': 'Warmer Gradient von Orange zu Gelb',
            'sequence': [
                {'hue': 7000, 'sat': 255, 'bri': 50, 'duration': 30},
                {'hue': 12000, 'sat': 220, 'bri': 120, 'duration': 60},
                {'hue': 15000, 'sat': 180, 'bri': 200, 'duration': 90},
                {'hue': 8000, 'sat': 100, 'bri': 254, 'duration': 120}
            ]
        },
        'sunset': {
            'name': 'Sonnenuntergang',
            'description': 'Tiefe Rot-Orange Töne',
            'sequence': [
                {'hue': 15000, 'sat': 100, 'bri': 254, 'duration': 60},
                {'hue': 8000, 'sat': 180, 'bri': 200, 'duration': 90},
                {'hue': 5000, 'sat': 220, 'bri': 120, 'duration': 120},
                {'hue': 0, 'sat': 255, 'bri': 80, 'duration': 180}
            ]
        },
        'aurora': {
            'name': 'Nordlicht',
            'description': 'Grün-Blau schimmernde Wellen',
            'sequence': [
                {'hue': 25000, 'sat': 255, 'bri': 150, 'duration': 45},
                {'hue': 46920, 'sat': 255, 'bri': 200, 'duration': 45},
                {'hue': 35000, 'sat': 255, 'bri': 120, 'duration': 45}
            ]
        },
        'thunder': {
            'name': 'Gewitter',
            'description': 'Dramatische Blitze mit Donnergrollen-Simulation',
            'sequence': [
                {'hue': 0, 'sat': 0, 'bri': 10, 'duration': 5},
                {'hue': 0, 'sat': 0, 'bri': 255, 'duration': 0.2},
                {'hue': 0, 'sat': 0, 'bri': 10, 'duration': 3},
                {'hue': 47000, 'sat': 255, 'bri': 100, 'duration': 30}
            ]
        },
        'ocean': {
            'name': 'Ozean',
            'description': 'Blaue Wellen-Bewegungen',
            'sequence': [
                {'hue': 46920, 'sat': 255, 'bri': 80, 'duration': 60},
                {'hue': 45000, 'sat': 200, 'bri': 150, 'duration': 60},
                {'hue': 48000, 'sat': 255, 'bri': 100, 'duration': 60}
            ]
        },
        'forest': {
            'name': 'Regenwald',
            'description': 'Grüne Schatten mit zufälligen Lichtpunkten',
            'sequence': [
                {'hue': 25500, 'sat': 255, 'bri': 120, 'duration': 90},
                {'hue': 22000, 'sat': 200, 'bri': 80, 'duration': 90},
                {'hue': 28000, 'sat': 255, 'bri': 160, 'duration': 90}
            ]
        },
        'desert': {
            'name': 'Wüste',
            'description': 'Warme Sand-Töne mit langsamen Übergängen',
            'sequence': [
                {'hue': 8000, 'sat': 180, 'bri': 200, 'duration': 120},
                {'hue': 12000, 'sat': 150, 'bri': 180, 'duration': 120},
                {'hue': 15000, 'sat': 120, 'bri': 220, 'duration': 120}
            ]
        },
        
        # Emotionale Szenen
        'relax': {
            'name': 'Entspannung',
            'description': 'Sanfte Lavendel-Töne',
            'sequence': [
                {'hue': 56100, 'sat': 120, 'bri': 100, 'duration': 180}
            ]
        },
        'energy': {
            'name': 'Energie',
            'description': 'Dynamische Orange-Rot Impulse',
            'sequence': [
                {'hue': 5000, 'sat': 255, 'bri': 200, 'duration': 30},
                {'hue': 0, 'sat': 255, 'bri': 254, 'duration': 30},
                {'hue': 8000, 'sat': 255, 'bri': 220, 'duration': 30}
            ]
        },
        'focus': {
            'name': 'Konzentration',
            'description': 'Kühles Weiß mit subtilen Akzenten',
            'sequence': [
                {'hue': 0, 'sat': 0, 'bri': 254, 'duration': 300},
                {'hue': 46920, 'sat': 50, 'bri': 200, 'duration': 60}
            ]
        },
        'romance': {
            'name': 'Romantik',
            'description': 'Warme Rosa-Rot Töne',
            'sequence': [
                {'hue': 65000, 'sat': 200, 'bri': 120, 'duration': 240}
            ]
        },
        'meditation': {
            'name': 'Meditation',
            'description': 'Ruhige Blau-Violett Übergänge',
            'sequence': [
                {'hue': 46920, 'sat': 150, 'bri': 80, 'duration': 120},
                {'hue': 50000, 'sat': 180, 'bri': 100, 'duration': 120},
                {'hue': 43000, 'sat': 120, 'bri': 60, 'duration': 120}
            ]
        },
        'creativity': {
            'name': 'Kreativität',
            'description': 'Bunte, inspirierende Farbwechsel',
            'sequence': [
                {'hue': 25500, 'sat': 255, 'bri': 200, 'duration': 45},
                {'hue': 46920, 'sat': 255, 'bri': 200, 'duration': 45},
                {'hue': 0, 'sat': 255, 'bri': 200, 'duration': 45},
                {'hue': 56100, 'sat': 255, 'bri': 200, 'duration': 45}
            ]
        },
        'calm': {
            'name': 'Beruhigung',
            'description': 'Sehr sanfte Grün-Blau Töne',
            'sequence': [
                {'hue': 33000, 'sat': 100, 'bri': 90, 'duration': 300}
            ]
        },
        
        # Aktivitäts-Szenen
        'party': {
            'name': 'Party',
            'description': 'Rhythmische Farbwechsel',
            'sequence': [
                {'hue': 0, 'sat': 255, 'bri': 254, 'duration': 15},
                {'hue': 25500, 'sat': 255, 'bri': 254, 'duration': 15},
                {'hue': 46920, 'sat': 255, 'bri': 254, 'duration': 15},
                {'hue': 56100, 'sat': 255, 'bri': 254, 'duration': 15}
            ]
        },
        'gaming': {
            'name': 'Gaming',
            'description': 'Reaktive RGB-Beleuchtung',
            'sequence': [
                {'hue': 46920, 'sat': 255, 'bri': 200, 'duration': 60},
                {'hue': 0, 'sat': 255, 'bri': 220, 'duration': 60},
                {'hue': 25500, 'sat': 255, 'bri': 240, 'duration': 60}
            ]
        },
        'reading': {
            'name': 'Lesen',
            'description': 'Optimales warmweißes Licht',
            'sequence': [
                {'hue': 8000, 'sat': 80, 'bri': 220, 'duration': 300}
            ]
        },
        'cooking': {
            'name': 'Kochen',
            'description': 'Helles, funktionales Küchenlicht',
            'sequence': [
                {'hue': 0, 'sat': 0, 'bri': 254, 'duration': 300}
            ]
        },
        'movie': {
            'name': 'Film',
            'description': 'Gedämmtes Ambiente mit Akzentbeleuchtung',
            'sequence': [
                {'hue': 46920, 'sat': 200, 'bri': 40, 'duration': 300}
            ]
        },
        'workout': {
            'name': 'Workout',
            'description': 'Motivierende, energetische Beleuchtung',
            'sequence': [
                {'hue': 5000, 'sat': 255, 'bri': 254, 'duration': 90},
                {'hue': 25500, 'sat': 255, 'bri': 254, 'duration': 90}
            ]
        }
    }
    
    if scene_type not in mood_scenes:
        return jsonify({'error': 'Unknown mood scene', 'success': False})
    
    scene = mood_scenes[scene_type]
    data = request.get_json() or {}
    target_lights = data.get('lights', 'all')
    
    # Start mood scene sequence
    def mood_scene_effect():
        effect_id = f"mood_{scene_type}_{int(time.time())}"
        running_effects[effect_id] = True
        
        try:
            for step in scene['sequence']:
                if effect_id not in running_effects:
                    break
                
                # Apply to all lights or specific lights
                if target_lights == 'all':
                    lights = get_lights_raw()
                    for light_id in lights.keys():
                        hue_request(f'lights/{light_id}/state', 'PUT', {
                            'on': True,
                            'hue': step['hue'],
                            'sat': step['sat'],
                            'bri': step['bri'],
                            'transitiontime': step.get('duration', 60)
                        })
                else:
                    for light_id in target_lights:
                        hue_request(f'lights/{light_id}/state', 'PUT', {
                            'on': True,
                            'hue': step['hue'],
                            'sat': step['sat'],
                            'bri': step['bri'],
                            'transitiontime': step.get('duration', 60)
                        })
                
                time.sleep(step.get('duration', 60) / 10)  # Wait for transition
                
        finally:
            if effect_id in running_effects:
                del running_effects[effect_id]
    
    # Start in background thread
    threading.Thread(target=mood_scene_effect, daemon=True).start()
    
    return jsonify({
        'success': True,
        'scene': scene['name'],
        'description': scene['description'],
        'message': f'Stimmungsszene "{scene["name"]}" aktiviert'
    })

@app.route('/api/mood-scenes', methods=['GET'])
def get_mood_scenes():
    """Liste aller verfügbaren Stimmungsszenen"""
    scenes = {
        'natural': [
            {'id': 'sunrise', 'name': 'Sonnenaufgang', 'icon': '🌅', 'category': 'natural'},
            {'id': 'sunset', 'name': 'Sonnenuntergang', 'icon': '🌇', 'category': 'natural'},
            {'id': 'aurora', 'name': 'Nordlicht', 'icon': '🌌', 'category': 'natural'},
            {'id': 'thunder', 'name': 'Gewitter', 'icon': '⛈️', 'category': 'natural'},
            {'id': 'ocean', 'name': 'Ozean', 'icon': '🌊', 'category': 'natural'},
            {'id': 'forest', 'name': 'Regenwald', 'icon': '🌲', 'category': 'natural'},
            {'id': 'desert', 'name': 'Wüste', 'icon': '🏜️', 'category': 'natural'}
        ],
        'emotional': [
            {'id': 'relax', 'name': 'Entspannung', 'icon': '🧘', 'category': 'emotional'},
            {'id': 'energy', 'name': 'Energie', 'icon': '⚡', 'category': 'emotional'},
            {'id': 'focus', 'name': 'Konzentration', 'icon': '🎯', 'category': 'emotional'},
            {'id': 'romance', 'name': 'Romantik', 'icon': '💕', 'category': 'emotional'},
            {'id': 'meditation', 'name': 'Meditation', 'icon': '🕯️', 'category': 'emotional'},
            {'id': 'creativity', 'name': 'Kreativität', 'icon': '🎨', 'category': 'emotional'},
            {'id': 'calm', 'name': 'Beruhigung', 'icon': '😌', 'category': 'emotional'}
        ],
        'activity': [
            {'id': 'party', 'name': 'Party', 'icon': '🎉', 'category': 'activity'},
            {'id': 'gaming', 'name': 'Gaming', 'icon': '🎮', 'category': 'activity'},
            {'id': 'reading', 'name': 'Lesen', 'icon': '📚', 'category': 'activity'},
            {'id': 'cooking', 'name': 'Kochen', 'icon': '👨‍🍳', 'category': 'activity'},
            {'id': 'movie', 'name': 'Film', 'icon': '🎬', 'category': 'activity'},
            {'id': 'workout', 'name': 'Workout', 'icon': '💪', 'category': 'activity'}
        ]
    }
    
    return jsonify({'scenes': scenes, 'success': True})

# === MUSIK-SYNCHRONISATION ===
audio_processor = None
music_sync_active = False

@app.route('/api/audio/devices', methods=['GET'])
def get_audio_devices():
    """Liste verfügbare Audio-Geräte"""
    try:
        from audio_processor import AudioProcessor
        processor = AudioProcessor()
        devices = processor.get_audio_devices()
        return jsonify({'devices': devices, 'success': True})
    except ImportError:
        return jsonify({
            'error': 'Audio-Module nicht verfügbar',
            'message': 'Installiere: pip install pyaudio scipy',
            'success': False
        })

@app.route('/api/audio/start-sync', methods=['POST'])
def start_music_sync():
    """Starte Musik-Synchronisation"""
    global audio_processor, music_sync_active
    
    try:
        from audio_processor import AudioProcessor, frequency_to_hue, amplitude_to_brightness
        
        data = request.get_json() or {}
        device_index = data.get('device_index')
        sync_mode = data.get('mode', 'frequency')  # frequency, beat, spectrum
        sensitivity = data.get('sensitivity', 0.5)
        
        # Stoppe vorherige Session
        if audio_processor:
            audio_processor.stop_processing()
        
        # Neue Audio-Processor Instanz
        from audio_processor import AudioConfig
        config = AudioConfig()
        if device_index is not None:
            config.device_index = device_index
            
        audio_processor = AudioProcessor(config)
        
        # Sync-Mode spezifische Callbacks
        if sync_mode == 'frequency':
            def frequency_sync_callback(freq_data):
                if not music_sync_active:
                    return
                
                try:
                    lights = get_lights_raw()
                    for light_id in lights.keys():
                        # Bass -> Rot, Mitten -> Grün, Höhen -> Blau
                        dominant_band = max(freq_data, key=freq_data.get)
                        hue_value = frequency_to_hue(freq_data['dominant'])
                        brightness = amplitude_to_brightness(
                            max(freq_data.values()) * sensitivity
                        )
                        
                        hue_request(f'lights/{light_id}/state', 'PUT', {
                            'on': True,
                            'hue': hue_value,
                            'sat': 254,
                            'bri': brightness,
                            'transitiontime': 1
                        })
                except Exception as e:
                    print(f"Frequency sync error: {e}")
            
            audio_processor.add_frequency_callback(frequency_sync_callback)
            
        elif sync_mode == 'beat':
            def beat_sync_callback(bpm):
                if not music_sync_active:
                    return
                
                try:
                    lights = get_lights_raw()
                    for light_id in lights.keys():
                        # Beat-Flash Effekt
                        hue_request(f'lights/{light_id}/state', 'PUT', {
                            'on': True,
                            'bri': 254,
                            'transitiontime': 0
                        })
                        
                        # Kurze Pause dann zurück zu normalem Zustand
                        threading.Timer(0.1, lambda: hue_request(
                            f'lights/{light_id}/state', 'PUT', {
                                'bri': int(150 * sensitivity),
                                'transitiontime': 5
                            }
                        )).start()
                        
                except Exception as e:
                    print(f"Beat sync error: {e}")
            
            audio_processor.add_beat_callback(beat_sync_callback)
            
        elif sync_mode == 'spectrum':
            def spectrum_sync_callback(freq_data):
                if not music_sync_active:
                    return
                
                try:
                    lights = get_lights_raw()
                    light_ids = list(lights.keys())
                    
                    # Verschiedene Lichter für verschiedene Frequenzbänder
                    bands = ['bass', 'mid', 'treble']
                    colors = [0, 25500, 46920]  # Rot, Grün, Blau
                    
                    for i, light_id in enumerate(light_ids[:len(bands)]):
                        band = bands[i % len(bands)]
                        energy = freq_data.get(band, 0)
                        brightness = amplitude_to_brightness(energy * sensitivity)
                        
                        hue_request(f'lights/{light_id}/state', 'PUT', {
                            'on': True,
                            'hue': colors[i % len(colors)],
                            'sat': 254,
                            'bri': brightness,
                            'transitiontime': 2
                        })
                        
                except Exception as e:
                    print(f"Spectrum sync error: {e}")
            
            audio_processor.add_frequency_callback(spectrum_sync_callback)
        
        # Audio-Verarbeitung starten
        if audio_processor.start_processing():
            music_sync_active = True
            return jsonify({
                'success': True,
                'message': f'Musik-Synchronisation gestartet ({sync_mode})',
                'mode': sync_mode,
                'device_index': device_index
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Audio-Verarbeitung konnte nicht gestartet werden'
            })
            
    except ImportError:
        return jsonify({
            'error': 'Audio-Module nicht verfügbar',
            'message': 'Installiere: pip install pyaudio scipy',
            'success': False
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/audio/stop-sync', methods=['POST'])
def stop_music_sync():
    """Stoppe Musik-Synchronisation"""
    global audio_processor, music_sync_active
    
    music_sync_active = False
    
    if audio_processor:
        audio_processor.stop_processing()
        audio_processor = None
    
    return jsonify({
        'success': True,
        'message': 'Musik-Synchronisation gestoppt'
    })

@app.route('/api/audio/status', methods=['GET'])
def get_audio_status():
    """Status der Musik-Synchronisation"""
    global music_sync_active, audio_processor
    
    return jsonify({
        'active': music_sync_active,
        'processor_running': audio_processor is not None and audio_processor.is_running if audio_processor else False,
        'audio_available': True  # TODO: Check if audio libraries are available
    })

# === STROMVERBRAUCH (SIMULIERT) ===
@app.route('/api/power/current', methods=['GET'])
def get_current_power():
    """Aktuellen Stromverbrauch berechnen (ohne DB)"""
    lights = get_lights_raw()
    total_consumption = 0
    active_lights = 0
    light_details = []
    
    for light_id, light in lights.items():
        # Nur Lichter zählen die eingeschaltet sind (unabhängig von reachable-Status)
        # Hinweis: Unreachable Lichter verbrauchen auch Strom wenn sie "on" sind
        if light.get('state', {}).get('on', False):
            brightness = light.get('state', {}).get('bri', 254)
            estimated_watts = (brightness / 254) * 9  # Geschätzt: max 9W pro LED
            total_consumption += estimated_watts
            active_lights += 1
            
            light_details.append({
                'id': light_id,
                'name': light['name'],
                'watts': round(estimated_watts, 2),
                'brightness': brightness,
                'reachable': light.get('state', {}).get('reachable', True)
            })
    
    return jsonify({
        'total_watts': round(total_consumption, 2),
        'active_lights': active_lights,
        'light_details': light_details,
        'estimated_monthly_kwh': round(total_consumption * 24 * 30 / 1000, 2),
        'estimated_monthly_cost_eur': round(total_consumption * 24 * 30 / 1000 * 0.30, 2),
        'database_logging': db_pool is not None
    })

@app.route('/api/power/history', methods=['GET'])
def get_power_history():
    """Stromverbrauch Historie aus Datenbank"""
    if not db_pool:
        return jsonify({
            'message': 'Database not configured',
            'daily_summary': [],
            'today_hourly': []
        })
    
    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Tages-Zusammenfassung (letzte 7 Tage)
        cursor.execute("""
            SELECT 
                DATE(timestamp) as date,
                AVG(total_watts) as avg_watts,
                MAX(total_watts) as max_watts,
                SUM(total_watts * 5 / 60) / 1000 as kwh,
                AVG(active_lights) as avg_lights
            FROM total_consumption
            WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            GROUP BY DATE(timestamp)
            ORDER BY date DESC
        """)
        daily_summary = cursor.fetchall()
        
        # Stündliche Daten für heute
        cursor.execute("""
            SELECT 
                HOUR(timestamp) as hour,
                AVG(total_watts) as avg_watts,
                MAX(total_watts) as max_watts,
                AVG(active_lights) as avg_lights
            FROM total_consumption
            WHERE DATE(timestamp) = CURDATE()
            GROUP BY HOUR(timestamp)
            ORDER BY hour
        """)
        today_hourly = cursor.fetchall()
        
        # Einzelne Lichter - Top Verbraucher heute
        cursor.execute("""
            SELECT 
                light_name,
                SUM(watts * 5 / 60) / 1000 as total_kwh,
                AVG(watts) as avg_watts,
                COUNT(*) as measurements
            FROM power_log
            WHERE DATE(timestamp) = CURDATE()
            GROUP BY light_name
            ORDER BY total_kwh DESC
            LIMIT 10
        """)
        top_consumers = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'daily_summary': daily_summary,
            'today_hourly': today_hourly,
            'top_consumers': top_consumers,
            'database_active': True
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'daily_summary': [],
            'today_hourly': []
        })

@app.route('/api/power/weekly', methods=['GET'])
def get_power_weekly():
    """Wochentags-Analyse des Stromverbrauchs"""
    if not db_pool:
        return jsonify({'error': 'Database not configured'})
    
    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Durchschnittlicher Verbrauch pro Wochentag (letzte 30 Tage)
        cursor.execute("""
            SELECT 
                DAYNAME(timestamp) as weekday,
                DAYOFWEEK(timestamp) as day_num,
                AVG(total_watts) as avg_watts,
                MAX(total_watts) as max_watts,
                MIN(total_watts) as min_watts,
                SUM(total_watts / 60) / 1000 as total_kwh,
                COUNT(DISTINCT DATE(timestamp)) as days_counted
            FROM total_consumption
            WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            GROUP BY DAYOFWEEK(timestamp), DAYNAME(timestamp)
            ORDER BY DAYOFWEEK(timestamp)
        """)
        weekday_data = cursor.fetchall()
        
        # Stundenverteilung pro Wochentag
        cursor.execute("""
            SELECT 
                DAYNAME(timestamp) as weekday,
                HOUR(timestamp) as hour,
                AVG(total_watts) as avg_watts
            FROM total_consumption
            WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            GROUP BY DAYOFWEEK(timestamp), HOUR(timestamp)
            ORDER BY DAYOFWEEK(timestamp), HOUR(timestamp)
        """)
        weekday_hourly = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'weekday_summary': weekday_data,
            'weekday_hourly': weekday_hourly
        })
        
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/power/monthly', methods=['GET'])
def get_power_monthly():
    """Monatsansicht des Stromverbrauchs"""
    if not db_pool:
        return jsonify({'error': 'Database not configured'})
    
    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Monatszusammenfassung (letzte 12 Monate)
        cursor.execute("""
            SELECT 
                DATE_FORMAT(timestamp, '%Y-%m') as month,
                AVG(total_watts) as avg_watts,
                MAX(total_watts) as max_watts,
                SUM(total_watts / 60) / 1000 as total_kwh,
                AVG(active_lights) as avg_lights,
                COUNT(DISTINCT DATE(timestamp)) as days_in_month
            FROM total_consumption
            WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
            GROUP BY DATE_FORMAT(timestamp, '%Y-%m')
            ORDER BY month DESC
        """)
        monthly_data = cursor.fetchall()
        
        # Kostenberechnung pro Monat
        for month in monthly_data:
            month['cost_eur'] = round(month['total_kwh'] * 0.30, 2)
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'monthly_summary': monthly_data
        })
        
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/power/seasonal', methods=['GET'])
def get_power_seasonal():
    """Sommer vs Winter Vergleich"""
    if not db_pool:
        return jsonify({'error': 'Database not configured'})
    
    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Sommer (April - September) vs Winter (Oktober - März)
        cursor.execute("""
            SELECT 
                CASE 
                    WHEN MONTH(timestamp) BETWEEN 4 AND 9 THEN 'Sommer'
                    ELSE 'Winter'
                END as season,
                AVG(total_watts) as avg_watts,
                MAX(total_watts) as max_watts,
                SUM(total_watts / 60) / 1000 as total_kwh,
                AVG(active_lights) as avg_lights,
                COUNT(DISTINCT DATE(timestamp)) as days_counted,
                MIN(timestamp) as first_date,
                MAX(timestamp) as last_date
            FROM total_consumption
            WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 365 DAY)
            GROUP BY season
        """)
        seasonal_data = cursor.fetchall()
        
        # Stundenverteilung Sommer vs Winter
        cursor.execute("""
            SELECT 
                CASE 
                    WHEN MONTH(timestamp) BETWEEN 4 AND 9 THEN 'Sommer'
                    ELSE 'Winter'
                END as season,
                HOUR(timestamp) as hour,
                AVG(total_watts) as avg_watts
            FROM total_consumption
            WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 365 DAY)
            GROUP BY season, HOUR(timestamp)
            ORDER BY season, hour
        """)
        seasonal_hourly = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'seasonal_comparison': seasonal_data,
            'seasonal_hourly': seasonal_hourly
        })
        
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/power/detailed/<timeframe>', methods=['GET'])
def get_power_detailed(timeframe):
    """Detaillierte Ansicht für verschiedene Zeiträume"""
    if not db_pool:
        return jsonify({'error': 'Database not configured'})
    
    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Zeitraum bestimmen
        if timeframe == 'today':
            time_filter = "DATE(timestamp) = CURDATE()"
            group_by = "HOUR(timestamp), MINUTE(timestamp)"
            select_time = "CONCAT(HOUR(timestamp), ':', LPAD(MINUTE(timestamp), 2, '0')) as time"
            order_by = "HOUR(timestamp), MINUTE(timestamp)"
        elif timeframe == 'week':
            time_filter = "timestamp >= DATE_SUB(NOW(), INTERVAL 7 DAY)"
            group_by = "DATE(timestamp), HOUR(timestamp)"
            select_time = "CONCAT(DATE(timestamp), ' ', HOUR(timestamp), ':00') as time"
            order_by = "DATE(timestamp), HOUR(timestamp)"
        elif timeframe == 'month':
            time_filter = "timestamp >= DATE_SUB(NOW(), INTERVAL 30 DAY)"
            group_by = "DATE(timestamp)"
            select_time = "DATE(timestamp) as time"
            order_by = "DATE(timestamp)"
        else:
            return jsonify({'error': 'Invalid timeframe'})
        
        # Detaillierte Daten abrufen
        query = f"""
            SELECT 
                {select_time},
                AVG(total_watts) as avg_watts,
                MAX(total_watts) as max_watts,
                MIN(total_watts) as min_watts,
                AVG(active_lights) as avg_lights
            FROM total_consumption
            WHERE {time_filter}
            GROUP BY {group_by}
            ORDER BY {order_by} ASC
        """
        
        cursor.execute(query)
        detailed_data = cursor.fetchall()
        
        # Top Verbraucher für den Zeitraum
        cursor.execute(f"""
            SELECT 
                light_name,
                SUM(watts / 60) / 1000 as total_kwh,
                AVG(watts) as avg_watts,
                MAX(watts) as max_watts,
                COUNT(*) as measurements,
                SUM(CASE WHEN brightness > 0 THEN 1 ELSE 0 END) / COUNT(*) * 100 as on_percentage
            FROM power_log
            WHERE {time_filter}
            GROUP BY light_name
            ORDER BY total_kwh DESC
            LIMIT 20
        """)
        top_lights = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'timeframe': timeframe,
            'detailed_data': detailed_data,
            'top_lights': top_lights
        })
        
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/power/lamp/<lamp_id>/<timeframe>', methods=['GET'])
def get_power_lamp_data(lamp_id, timeframe):
    """Detaillierte Daten für eine einzelne Lampe"""
    if not db_pool:
        return jsonify({'error': 'Database not configured'})
    
    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Zeitraum bestimmen (gleiche Logik wie bei detailed endpoint)
        if timeframe == 'today':
            time_filter = "DATE(timestamp) = CURDATE()"
            group_by = "HOUR(timestamp), MINUTE(timestamp)"
            select_time = "CONCAT(HOUR(timestamp), ':', LPAD(MINUTE(timestamp), 2, '0')) as time"
            order_by = "HOUR(timestamp), MINUTE(timestamp)"
        elif timeframe == 'week':
            time_filter = "timestamp >= DATE_SUB(NOW(), INTERVAL 7 DAY)"
            group_by = "DATE(timestamp), HOUR(timestamp)"
            select_time = "CONCAT(DATE(timestamp), ' ', HOUR(timestamp), ':00') as time"
            order_by = "DATE(timestamp), HOUR(timestamp)"
        elif timeframe == 'month':
            time_filter = "timestamp >= DATE_SUB(NOW(), INTERVAL 30 DAY)"
            group_by = "DATE(timestamp)"
            select_time = "DATE(timestamp) as time"
            order_by = "DATE(timestamp)"
        else:
            return jsonify({'error': 'Invalid timeframe'})
        
        # Daten für spezifische Lampe abrufen
        query = f"""
            SELECT 
                {select_time},
                AVG(watts) as avg_watts,
                MAX(watts) as max_watts,
                MIN(watts) as min_watts,
                AVG(brightness) as avg_brightness
            FROM power_log
            WHERE light_id = %s AND {time_filter}
            GROUP BY {group_by}
            ORDER BY {order_by} ASC
        """
        
        cursor.execute(query, (lamp_id,))
        detailed_data = cursor.fetchall()
        
        # Lampenname abrufen
        cursor.execute("""
            SELECT DISTINCT light_name
            FROM power_log
            WHERE light_id = %s
            ORDER BY timestamp DESC
            LIMIT 1
        """, (lamp_id,))
        name_result = cursor.fetchone()
        lamp_name = name_result['light_name'] if name_result else f"Lamp {lamp_id}"
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'lamp_id': lamp_id,
            'lamp_name': lamp_name,
            'timeframe': timeframe,
            'detailed_data': detailed_data
        })
        
    except Exception as e:
        return jsonify({'error': str(e)})

# === STATUS ===
# === ONBOARDING API ===
@app.route('/api/onboarding/discover-bridge', methods=['GET'])
def discover_bridge():
    """Automatische Hue Bridge Erkennung"""
    try:
        # Philips Hue Discovery Service
        response = requests.get('https://discovery.meethue.com/', timeout=10)
        bridges = response.json()
        
        # Local network scan als Fallback
        if not bridges:
            import subprocess
            result = subprocess.run(['nmap', '-sn', '192.168.1.0/24'], 
                                  capture_output=True, text=True, timeout=30)
            # Parse nmap results for potential bridges
            bridges = [{'internalipaddress': HUE_BRIDGE_IP}]  # Fallback
            
        return jsonify({'bridges': bridges, 'success': True})
    except Exception as e:
        return jsonify({'error': str(e), 'success': False})

@app.route('/api/onboarding/generate-key', methods=['POST'])
def generate_api_key():
    """Generiere neuen API Key für Bridge"""
    data = request.get_json()
    bridge_ip = data.get('bridge_ip', HUE_BRIDGE_IP)
    
    try:
        response = requests.post(
            f"http://{bridge_ip}/api",
            json={"devicetype": "HueControllerProX#RaspberryPi"},
            timeout=10
        )
        result = response.json()[0]
        
        if 'error' in result:
            if result['error']['type'] == 101:
                return jsonify({
                    'success': False, 
                    'error': 'button_not_pressed',
                    'message': 'Bitte drücken Sie den Button auf der Hue Bridge'
                })
        
        if 'success' in result:
            username = result['success']['username']
            return jsonify({
                'success': True, 
                'username': username,
                'message': 'API Key erfolgreich generiert!'
            })
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/onboarding/test-connection', methods=['POST'])
def onboarding_test_hue_connection():
    """Teste Verbindung mit Bridge und API Key"""
    data = request.get_json()
    bridge_ip = data.get('bridge_ip')
    username = data.get('username')
    
    try:
        response = requests.get(f"http://{bridge_ip}/api/{username}/lights", timeout=5)
        lights = response.json()
        
        if isinstance(lights, dict) and 'error' not in str(lights):
            return jsonify({
                'success': True,
                'lights_count': len(lights),
                'lights': lights
            })
        else:
            return jsonify({'success': False, 'error': 'Invalid credentials'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/onboarding/save-config', methods=['POST'])
def save_onboarding_config():
    """Speichere Onboarding-Konfiguration"""
    data = request.get_json()
    
    try:
        # Update .env file
        env_content = []
        env_path = Path('.env')
        
        if env_path.exists():
            with open(env_path, 'r') as f:
                env_content = f.readlines()
        
        # Update or add values
        config_map = {
            'HUE_BRIDGE_IP': data.get('bridge_ip'),
            'HUE_USERNAME': data.get('username')
        }
        
        for key, value in config_map.items():
            found = False
            for i, line in enumerate(env_content):
                if line.startswith(f"{key}="):
                    env_content[i] = f"{key}={value}\n"
                    found = True
                    break
            if not found:
                env_content.append(f"{key}={value}\n")
        
        # Write back to file
        with open(env_path, 'w') as f:
            f.writelines(env_content)
        
        # Mark onboarding as completed
        with open('.onboarding_completed', 'w') as f:
            f.write(str(datetime.now()))
        
        return jsonify({'success': True, 'message': 'Konfiguration gespeichert!'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

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
            'database': 'enabled' if db_pool else 'disabled',
            'onboarding_completed': os.path.exists('.onboarding_completed'),
            'features': {
                'basic_control': True,
                'scenes': True,
                'effects': True,
                'timers': True,
                'sensors': True,
                'global_control': True,
                'power_estimation': True,
                'power_logging': db_pool is not None
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

# === SMART ERROR HANDLING & SYSTEM HEALTH ===

@app.route('/api/system/health', methods=['GET'])
@smart_error_handler('system_health_check')
def system_health():
    """System-Gesundheitscheck mit Diagnose"""
    health_report = get_system_health()
    return jsonify({
        'success': True,
        'health': health_report,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/system/errors', methods=['GET'])
@smart_error_handler('error_statistics')
def error_statistics():
    """Fehlerstatistiken und Recent Errors"""
    stats = get_error_stats()
    return jsonify({
        'success': True,
        'statistics': stats,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/system/diagnose', methods=['POST'])
@smart_error_handler('system_diagnosis')
def diagnose_issue():
    """Erweiterte Systemdiagnose für spezifische Probleme"""
    data = request.get_json() or {}
    issue_type = data.get('type', 'general')
    
    diagnosis = {
        'issue_type': issue_type,
        'timestamp': datetime.now().isoformat(),
        'tests': {},
        'solutions': []
    }
    
    if issue_type == 'lights':
        # Licht-spezifische Diagnose
        try:
            lights = hue_request('lights')
            if isinstance(lights, list) and len(lights) > 0 and 'error' in lights[0]:
                diagnosis['tests']['hue_api'] = 'authentication_failed'
                diagnosis['solutions'].extend([
                    'API-Schlüssel erneuern',
                    'Bridge-Button drücken und neu verbinden'
                ])
            else:
                diagnosis['tests']['hue_api'] = 'ok'
                diagnosis['tests']['lights_count'] = len(lights) if isinstance(lights, dict) else 0
        except Exception as e:
            diagnosis['tests']['hue_api'] = f'connection_error: {str(e)}'
            diagnosis['solutions'].append('Bridge-IP und Netzwerkverbindung prüfen')
    
    elif issue_type == 'database':
        # Datenbank-spezifische Diagnose
        try:
            if db_pool:
                conn = db_pool.get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM power_log")
                count = cursor.fetchone()[0]
                diagnosis['tests']['database_connection'] = 'ok'
                diagnosis['tests']['power_log_entries'] = count
                conn.close()
            else:
                diagnosis['tests']['database_connection'] = 'pool_not_initialized'
                diagnosis['solutions'].append('Datenbank-Konfiguration prüfen')
        except Exception as e:
            diagnosis['tests']['database_connection'] = f'error: {str(e)}'
            diagnosis['solutions'].extend([
                'MariaDB Service prüfen: systemctl status mariadb',
                'Datenbank-Credentials überprüfen'
            ])
    
    elif issue_type == 'audio':
        # Audio-spezifische Diagnose
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            device_count = p.get_device_count()
            devices = []
            for i in range(device_count):
                info = p.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
                    devices.append({
                        'index': i,
                        'name': info['name'],
                        'channels': info['maxInputChannels']
                    })
            p.terminate()
            diagnosis['tests']['audio_devices'] = devices
            diagnosis['tests']['pyaudio_available'] = True
        except ImportError:
            diagnosis['tests']['pyaudio_available'] = False
            diagnosis['solutions'].append('Audio-Libraries installieren: pip install pyaudio scipy')
        except Exception as e:
            diagnosis['tests']['audio_error'] = str(e)
            diagnosis['solutions'].append('Audio-System-Konfiguration prüfen')
    
    return jsonify({
        'success': True,
        'diagnosis': diagnosis
    })

@app.route('/api/system/recovery', methods=['POST'])
@smart_error_handler('system_recovery')
def recovery_action():
    """Automatische Recovery-Aktionen"""
    data = request.get_json() or {}
    action = data.get('action')
    
    recovery_result = {
        'action': action,
        'timestamp': datetime.now().isoformat(),
        'success': False,
        'message': '',
        'details': {}
    }
    
    if action == 'restart_effects':
        # Alle Effekte stoppen und zurücksetzen
        global running_effects
        stopped_effects = list(running_effects.keys())
        running_effects.clear()
        recovery_result['success'] = True
        recovery_result['message'] = f'Alle Effekte gestoppt ({len(stopped_effects)} Effekte)'
        recovery_result['details']['stopped_effects'] = stopped_effects
    
    elif action == 'reset_database_pool':
        # Datenbank-Pool neu initialisieren
        try:
            global db_pool
            if db_pool:
                db_pool = None
            init_db()
            recovery_result['success'] = True
            recovery_result['message'] = 'Datenbank-Pool neu initialisiert'
        except Exception as e:
            recovery_result['message'] = f'Fehler beim DB-Reset: {str(e)}'
    
    elif action == 'test_bridge':
        # Bridge-Verbindung testen
        try:
            lights = hue_request('lights')
            if isinstance(lights, dict):
                recovery_result['success'] = True
                recovery_result['message'] = f'Bridge erreichbar, {len(lights)} Lichter gefunden'
                recovery_result['details']['lights_count'] = len(lights)
            else:
                recovery_result['message'] = 'Bridge-Verbindung fehlgeschlagen'
        except Exception as e:
            recovery_result['message'] = f'Bridge-Test fehlgeschlagen: {str(e)}'
    
    elif action == 'stop_audio':
        # Audio-Processing stoppen
        try:
            global audio_processor, music_sync_active
            if audio_processor:
                audio_processor.stop_processing()
                audio_processor = None
            music_sync_active = False
            recovery_result['success'] = True
            recovery_result['message'] = 'Audio-Processing gestoppt'
        except Exception as e:
            recovery_result['message'] = f'Audio-Stop fehlgeschlagen: {str(e)}'
    
    else:
        recovery_result['message'] = f'Unbekannte Recovery-Aktion: {action}'
    
    return jsonify({
        'success': recovery_result['success'],
        'recovery': recovery_result
    })

# === EFFECT BUILDER SYSTEM ===

@app.route('/api/effect-builder/templates', methods=['GET'])
@smart_error_handler('effect_builder_templates')
def get_effect_templates():
    """Verfügbare Effekt-Templates abrufen"""
    global effect_builder
    if not effect_builder:
        effect_builder = EffectBuilder(db_pool)
    
    templates = effect_builder.get_templates()
    return jsonify({
        'success': True,
        'templates': templates
    })

@app.route('/api/effect-builder/effects', methods=['GET'])
@smart_error_handler('effect_builder_list')
def list_custom_effects():
    """Alle Custom-Effekte auflisten"""
    global effect_builder
    if not effect_builder:
        effect_builder = EffectBuilder(db_pool)
    
    category = request.args.get('category')
    author = request.args.get('author')
    
    effects = effect_builder.list_effects(category, author)
    return jsonify({
        'success': True,
        'effects': effects,
        'count': len(effects)
    })

@app.route('/api/effect-builder/effects', methods=['POST'])
@smart_error_handler('effect_builder_create')
def create_custom_effect():
    """Neuen Custom-Effekt erstellen"""
    global effect_builder
    if not effect_builder:
        effect_builder = EffectBuilder(db_pool)
    
    data = request.get_json()
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    category = data.get('category', 'custom')
    author = data.get('author', 'user')
    
    if len(name) < 3:
        return jsonify({
            'success': False,
            'error': 'Name muss mindestens 3 Zeichen lang sein'
        }), 400
    
    effect = effect_builder.create_effect(name, description, category, author)
    
    return jsonify({
        'success': True,
        'effect': {
            'id': effect.id,
            'name': effect.name,
            'description': effect.description,
            'category': effect.category,
            'author': effect.author,
            'created_at': effect.created_at,
            'steps': [],
            'preview_colors': effect.preview_colors
        }
    })

@app.route('/api/effect-builder/effects/<effect_id>', methods=['GET'])
@smart_error_handler('effect_builder_get')
def get_custom_effect(effect_id):
    """Custom-Effekt laden"""
    global effect_builder
    if not effect_builder:
        effect_builder = EffectBuilder(db_pool)
    
    effect = effect_builder.load_effect(effect_id)
    if not effect:
        return jsonify({
            'success': False,
            'error': 'Effekt nicht gefunden'
        }), 404
    
    return jsonify({
        'success': True,
        'effect': {
            'id': effect.id,
            'name': effect.name,
            'description': effect.description,
            'category': effect.category,
            'author': effect.author,
            'created_at': effect.created_at,
            'steps': [asdict(step) for step in effect.steps],
            'tags': effect.tags,
            'preview_colors': effect.preview_colors,
            'is_public': effect.is_public
        }
    })

@app.route('/api/effect-builder/effects/<effect_id>/steps', methods=['POST'])
@smart_error_handler('effect_builder_add_step')
def add_effect_step(effect_id):
    """Schritt zu Effekt hinzufügen"""
    global effect_builder
    if not effect_builder:
        effect_builder = EffectBuilder(db_pool)
    
    effect = effect_builder.load_effect(effect_id)
    if not effect:
        return jsonify({
            'success': False,
            'error': 'Effekt nicht gefunden'
        }), 404
    
    data = request.get_json()
    step_type = data.get('type')
    duration = float(data.get('duration', 0))
    parameters = data.get('parameters', {})
    target_type = data.get('target_type', 'all')
    target_id = data.get('target_id')
    
    # Validierung
    if step_type not in ['color', 'brightness', 'transition', 'delay', 'loop']:
        return jsonify({
            'success': False,
            'error': 'Ungültiger Schritt-Typ'
        }), 400
    
    step = effect_builder.add_step(effect, step_type, duration, parameters, target_type, target_id)
    
    # Effekt speichern
    effect_builder.save_effect(effect)
    
    # Preview-Farben aktualisieren
    effect_builder.generate_preview_colors(effect)
    effect_builder.save_effect(effect)
    
    return jsonify({
        'success': True,
        'step': {
            'id': step.id,
            'type': step.type,
            'duration': step.duration,
            'parameters': step.parameters,
            'target_type': step.target_type,
            'target_id': step.target_id
        },
        'preview_colors': effect.preview_colors
    })

@app.route('/api/effect-builder/effects/<effect_id>/steps/<step_id>', methods=['DELETE'])
@smart_error_handler('effect_builder_remove_step')
def remove_effect_step(effect_id, step_id):
    """Schritt aus Effekt entfernen"""
    global effect_builder
    if not effect_builder:
        effect_builder = EffectBuilder(db_pool)
    
    effect = effect_builder.load_effect(effect_id)
    if not effect:
        return jsonify({
            'success': False,
            'error': 'Effekt nicht gefunden'
        }), 404
    
    removed = effect_builder.remove_step(effect, step_id)
    if not removed:
        return jsonify({
            'success': False,
            'error': 'Schritt nicht gefunden'
        }), 404
    
    # Effekt speichern
    effect_builder.save_effect(effect)
    
    # Preview-Farben aktualisieren
    effect_builder.generate_preview_colors(effect)
    effect_builder.save_effect(effect)
    
    return jsonify({
        'success': True,
        'message': 'Schritt entfernt',
        'preview_colors': effect.preview_colors
    })

@app.route('/api/effect-builder/effects/<effect_id>/reorder', methods=['PUT'])
@smart_error_handler('effect_builder_reorder')
def reorder_effect_steps(effect_id):
    """Schritte neu ordnen"""
    global effect_builder
    if not effect_builder:
        effect_builder = EffectBuilder(db_pool)
    
    effect = effect_builder.load_effect(effect_id)
    if not effect:
        return jsonify({
            'success': False,
            'error': 'Effekt nicht gefunden'
        }), 404
    
    data = request.get_json()
    step_ids = data.get('step_ids', [])
    
    reordered = effect_builder.reorder_steps(effect, step_ids)
    if not reordered:
        return jsonify({
            'success': False,
            'error': 'Fehler beim Neuordnen'
        }), 400
    
    # Effekt speichern
    effect_builder.save_effect(effect)
    
    return jsonify({
        'success': True,
        'message': 'Schritte neu geordnet'
    })

@app.route('/api/effect-builder/effects/<effect_id>/validate', methods=['GET'])
@smart_error_handler('effect_builder_validate')
def validate_custom_effect(effect_id):
    """Effekt validieren"""
    global effect_builder
    if not effect_builder:
        effect_builder = EffectBuilder(db_pool)
    
    effect = effect_builder.load_effect(effect_id)
    if not effect:
        return jsonify({
            'success': False,
            'error': 'Effekt nicht gefunden'
        }), 404
    
    validation = effect_builder.validate_effect(effect)
    return jsonify({
        'success': True,
        'validation': validation
    })

@app.route('/api/effect-builder/effects/<effect_id>/execute', methods=['POST'])
@smart_error_handler('effect_builder_execute')
def execute_custom_effect(effect_id):
    """Custom-Effekt ausführen"""
    global effect_builder
    if not effect_builder:
        effect_builder = EffectBuilder(db_pool)
    
    effect = effect_builder.load_effect(effect_id)
    if not effect:
        return jsonify({
            'success': False,
            'error': 'Effekt nicht gefunden'
        }), 404
    
    # Validation
    validation = effect_builder.validate_effect(effect)
    if not validation['valid']:
        return jsonify({
            'success': False,
            'error': 'Effekt ist nicht gültig',
            'issues': validation['issues']
        }), 400
    
    # Effekt in separatem Thread ausführen
    def execute_effect():
        effect_execution_id = str(uuid.uuid4())
        running_effects[effect_execution_id] = {
            'type': 'custom',
            'name': effect.name,
            'start_time': time.time()
        }
        
        try:
            import random
            loop_count = 0
            max_loops = 1000  # Sicherheitsgrenze
            
            while effect_execution_id in running_effects and loop_count < max_loops:
                for step in effect.steps:
                    if effect_execution_id not in running_effects:
                        break
                    
                    if step.type == 'loop':
                        count = step.parameters.get('count', 1)
                        if count == -1:  # Endlos
                            loop_count += 1
                            if loop_count >= max_loops:
                                break
                        continue
                    
                    # Ziel-Lichter bestimmen
                    if step.target_type == 'all':
                        lights = hue_request('lights')
                        if isinstance(lights, dict):
                            target_lights = list(lights.keys())
                        else:
                            continue
                    elif step.target_type == 'light':
                        target_lights = [step.target_id] if step.target_id else []
                    elif step.target_type == 'group':
                        target_lights = []  # Würde Gruppen-API verwenden
                    else:
                        continue
                    
                    # Schritt ausführen
                    for light_id in target_lights:
                        if effect_execution_id not in running_effects:
                            break
                        
                        command = {}
                        
                        if step.type in ['color', 'brightness', 'transition']:
                            params = step.parameters.copy()
                            
                            # Zufällige Werte behandeln
                            if params.get('hue') == 'random':
                                params['hue'] = random.randint(0, 65535)
                            
                            command.update(params)
                            
                            # Transition-Zeit für sanfte Übergänge
                            if step.type == 'transition':
                                command['transitiontime'] = int(step.duration * 10)
                        
                        if command:
                            hue_request(f'lights/{light_id}/state', 'PUT', command)
                    
                    # Warten für Schritt-Dauer
                    if step.duration > 0:
                        time.sleep(step.duration)
                
                # Loop prüfen
                has_loop = any(s.type == 'loop' for s in effect.steps)
                if not has_loop:
                    break
                    
        finally:
            if effect_execution_id in running_effects:
                del running_effects[effect_execution_id]
    
    import threading
    threading.Thread(target=execute_effect, daemon=True).start()
    
    return jsonify({
        'success': True,
        'message': f'Custom-Effekt "{effect.name}" gestartet',
        'effect_name': effect.name,
        'total_steps': len(effect.steps)
    })

@app.route('/api/effect-builder/effects/<effect_id>', methods=['DELETE'])
@smart_error_handler('effect_builder_delete')
def delete_custom_effect(effect_id):
    """Custom-Effekt löschen"""
    global effect_builder
    if not effect_builder:
        effect_builder = EffectBuilder(db_pool)
    
    deleted = effect_builder.delete_effect(effect_id)
    if not deleted:
        return jsonify({
            'success': False,
            'error': 'Effekt nicht gefunden oder konnte nicht gelöscht werden'
        }), 404
    
    return jsonify({
        'success': True,
        'message': 'Effekt gelöscht'
    })

@app.route('/api/effect-builder/create-from-template', methods=['POST'])
@smart_error_handler('effect_builder_from_template')
def create_effect_from_template():
    """Effekt aus Template erstellen"""
    global effect_builder
    if not effect_builder:
        effect_builder = EffectBuilder(db_pool)
    
    data = request.get_json()
    template_key = data.get('template')
    name = data.get('name', '').strip()
    author = data.get('author', 'user')
    
    if not template_key or not name:
        return jsonify({
            'success': False,
            'error': 'Template und Name sind erforderlich'
        }), 400
    
    effect = effect_builder.create_from_template(template_key, name, author)
    if not effect:
        return jsonify({
            'success': False,
            'error': 'Template nicht gefunden'
        }), 404
    
    # Effekt speichern
    saved = effect_builder.save_effect(effect)
    if not saved:
        return jsonify({
            'success': False,
            'error': 'Fehler beim Speichern'
        }), 500
    
    return jsonify({
        'success': True,
        'effect': {
            'id': effect.id,
            'name': effect.name,
            'description': effect.description,
            'category': effect.category,
            'steps_count': len(effect.steps),
            'preview_colors': effect.preview_colors
        },
        'message': f'Effekt "{effect.name}" aus Template erstellt'
    })

# === EXTENDED DATABASE FEATURES ===

@app.route('/api/analytics/usage', methods=['GET'])
@smart_error_handler('usage_analytics')
def get_usage_analytics():
    """Usage-Analytics abrufen"""
    if not db_pool:
        return jsonify({
            'success': False,
            'error': 'Database nicht verfügbar'
        }), 503
    
    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor()
        
        # Scene Usage Analytics
        cursor.execute("""
            SELECT scene_type, scene_name, COUNT(*) as usage_count, 
                   AVG(duration_seconds) as avg_duration
            FROM scene_usage 
            WHERE activation_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            GROUP BY scene_type, scene_name
            ORDER BY usage_count DESC
            LIMIT 10
        """)
        popular_scenes = [
            {
                'type': row[0],
                'name': row[1],
                'usage_count': row[2],
                'avg_duration': float(row[3]) if row[3] else 0
            }
            for row in cursor.fetchall()
        ]
        
        # Effect Usage Analytics
        cursor.execute("""
            SELECT effect_type, effect_name, COUNT(*) as usage_count,
                   AVG(duration_seconds) as avg_duration
            FROM effect_usage 
            WHERE start_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            GROUP BY effect_type, effect_name
            ORDER BY usage_count DESC
            LIMIT 10
        """)
        popular_effects = [
            {
                'type': row[0],
                'name': row[1],
                'usage_count': row[2],
                'avg_duration': float(row[3]) if row[3] else 0
            }
            for row in cursor.fetchall()
        ]
        
        # System Health Trend
        cursor.execute("""
            SELECT overall_status, COUNT(*) as count
            FROM system_health_log 
            WHERE check_time >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            GROUP BY overall_status
        """)
        health_trend = {row[0]: row[1] for row in cursor.fetchall()}
        
        conn.close()
        
        return jsonify({
            'success': True,
            'analytics': {
                'popular_scenes': popular_scenes,
                'popular_effects': popular_effects,
                'health_trend': health_trend,
                'period': '30 days'
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Analytics-Fehler: {str(e)}'
        }), 500

@app.route('/api/preferences', methods=['GET'])
@smart_error_handler('user_preferences_get')
def get_user_preferences():
    """User-Präferenzen abrufen"""
    if not db_pool:
        return jsonify({
            'success': True,
            'preferences': {}  # Fallback ohne DB
        })
    
    try:
        user_id = request.args.get('user_id', 'default')
        conn = db_pool.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT preference_key, preference_value, data_type 
            FROM user_preferences 
            WHERE user_id = %s
        """, (user_id,))
        
        preferences = {}
        for row in cursor.fetchall():
            key, value, data_type = row
            
            # Datentyp-Konvertierung
            if data_type == 'int':
                preferences[key] = int(value)
            elif data_type == 'float':
                preferences[key] = float(value)
            elif data_type == 'bool':
                preferences[key] = value.lower() == 'true'
            elif data_type == 'json':
                preferences[key] = json.loads(value)
            else:
                preferences[key] = value
        
        conn.close()
        
        return jsonify({
            'success': True,
            'preferences': preferences,
            'user_id': user_id
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Preferences-Fehler: {str(e)}'
        }), 500

@app.route('/api/preferences', methods=['POST'])
@smart_error_handler('user_preferences_set')
def set_user_preferences():
    """User-Präferenzen setzen"""
    if not db_pool:
        return jsonify({
            'success': False,
            'error': 'Database nicht verfügbar'
        }), 503
    
    try:
        data = request.get_json()
        user_id = data.get('user_id', 'default')
        preferences = data.get('preferences', {})
        
        conn = db_pool.get_connection()
        cursor = conn.cursor()
        
        for key, value in preferences.items():
            # Datentyp bestimmen
            if isinstance(value, bool):
                data_type = 'bool'
                value_str = 'true' if value else 'false'
            elif isinstance(value, int):
                data_type = 'int'
                value_str = str(value)
            elif isinstance(value, float):
                data_type = 'float'
                value_str = str(value)
            elif isinstance(value, (dict, list)):
                data_type = 'json'
                value_str = json.dumps(value)
            else:
                data_type = 'string'
                value_str = str(value)
            
            # Upsert
            cursor.execute("""
                INSERT INTO user_preferences (user_id, preference_key, preference_value, data_type)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                preference_value = VALUES(preference_value),
                data_type = VALUES(data_type),
                updated_at = CURRENT_TIMESTAMP
            """, (user_id, key, value_str, data_type))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'{len(preferences)} Präferenzen gespeichert',
            'user_id': user_id
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Preferences-Fehler: {str(e)}'
        }), 500

@app.route('/api/system/settings', methods=['GET'])
@smart_error_handler('system_settings_get')
def get_system_settings():
    """System-Einstellungen abrufen"""
    if not db_pool:
        return jsonify({
            'success': True,
            'settings': {}
        })
    
    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor()
        
        include_private = request.args.get('include_private', 'false').lower() == 'true'
        
        if include_private:
            cursor.execute("""
                SELECT setting_key, setting_value, data_type, description 
                FROM system_settings
            """)
        else:
            cursor.execute("""
                SELECT setting_key, setting_value, data_type, description 
                FROM system_settings 
                WHERE is_public = TRUE
            """)
        
        settings = {}
        for row in cursor.fetchall():
            key, value, data_type, description = row
            
            # Datentyp-Konvertierung
            if data_type == 'int':
                parsed_value = int(value)
            elif data_type == 'float':
                parsed_value = float(value)
            elif data_type == 'bool':
                parsed_value = value.lower() == 'true'
            elif data_type == 'json':
                parsed_value = json.loads(value)
            else:
                parsed_value = value
            
            settings[key] = {
                'value': parsed_value,
                'description': description
            }
        
        conn.close()
        
        return jsonify({
            'success': True,
            'settings': settings
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Settings-Fehler: {str(e)}'
        }), 500

def track_scene_usage(scene_type: str, scene_id: str, scene_name: str, user_id: str = 'default'):
    """Scene-Usage in Datenbank loggen"""
    if not db_pool:
        return
    
    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO scene_usage (scene_type, scene_id, scene_name, user_id)
            VALUES (%s, %s, %s, %s)
        """, (scene_type, scene_id, scene_name, user_id))
        
        conn.commit()
        conn.close()
    except Exception:
        pass  # Silent fail für Tracking

def track_effect_usage(effect_type: str, effect_name: str, target_type: str, 
                      target_count: int = 0, effect_id: str = None, user_id: str = 'default'):
    """Effect-Usage in Datenbank loggen"""
    if not db_pool:
        return
    
    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO effect_usage (effect_type, effect_id, effect_name, user_id, 
                                    target_type, target_count)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (effect_type, effect_id, effect_name, user_id, target_type, target_count))
        
        conn.commit()
        conn.close()
    except Exception:
        pass  # Silent fail für Tracking

def log_system_health():
    """System-Health in Datenbank loggen"""
    if not db_pool:
        return
    
    try:
        import psutil
        
        # System-Metriken sammeln
        memory_usage = psutil.virtual_memory().used / (1024 * 1024)  # MB
        cpu_usage = psutil.cpu_percent()
        uptime = int(time.time() - psutil.boot_time())
        
        # Health-Check durchführen
        health = get_system_health()
        
        conn = db_pool.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO system_health_log 
            (overall_status, hue_bridge_status, database_status, audio_system_status,
             active_effects_count, memory_usage_mb, cpu_usage_percent, uptime_seconds,
             recommendations_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            health['status'],
            health['checks'].get('hue_bridge', 'unknown'),
            health['checks'].get('database', 'unknown'),
            health['checks'].get('audio_system', 'unknown'),
            len(running_effects),
            memory_usage,
            cpu_usage,
            uptime,
            json.dumps(health.get('recommendations', []))
        ))
        
        conn.commit()
        conn.close()
    except Exception:
        pass  # Silent fail für Health-Logging

if __name__ == '__main__':
    print("🏠 Hue Controller Pro gestartet!")
    print(f"📡 Bridge: {HUE_BRIDGE_IP}")
    
    # Datenbank initialisieren
    db_enabled = init_db()
    if db_enabled:
        print("🗄️ Database: Enabled - Power logging active")
        
        # Effect Builder Datenbank-Tabelle erstellen
        init_effect_builder_db(db_pool)
        print("🎨 Effect Builder: Database tables created")
        
        # Effect Builder initialisieren
        effect_builder = EffectBuilder(db_pool)
        print("🎨 Effect Builder: Initialized")
        
        # Power logging Thread starten
        power_logging_thread = threading.Thread(target=power_logging_worker, daemon=True)
        power_logging_thread.start()
        print("⚡ Power logging thread started (5 min interval)")
    else:
        print("🗄️ Database: Disabled - Running without logging")
        # Effect Builder ohne DB initialisieren
        effect_builder = EffectBuilder(None)
        print("🎨 Effect Builder: Initialized (file-based storage)")
    
    # Debug-System initialisieren
    add_debug_log('info', '🚀 Hue Controller Pro gestartet')
    add_debug_log('info', f'📡 Bridge IP: {HUE_BRIDGE_IP}')
    add_debug_log('success', '🎨 Effect Builder initialisiert')
    
    print("🌐 Starting server...")
    add_debug_log('info', '🌐 Server wird gestartet...')
    
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
