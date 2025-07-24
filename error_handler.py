#!/usr/bin/env python3
"""
Smart Error Handling System für Hue by mrx3k1
Zentrale Fehlerbehandlung mit intelligenten Lösungsvorschlägen
"""

import logging
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, List
from functools import wraps
import requests
import mysql.connector

# Error-Kategorien und Lösungsvorschläge
ERROR_SOLUTIONS = {
    'hue_bridge_connection': {
        'title': 'Hue Bridge nicht erreichbar',
        'solutions': [
            'Prüfen Sie, ob die Bridge eingeschaltet ist',
            'Überprüfen Sie die IP-Adresse in der .env Datei',
            'Stellen Sie sicher, dass Bridge und Server im gleichen Netzwerk sind',
            'Testen Sie die Verbindung: ping <bridge_ip>'
        ],
        'technical': 'Netzwerk-Konnektivitätsproblem zur Hue Bridge',
        'user_action': 'Bridge-Status prüfen'
    },
    'hue_api_key': {
        'title': 'Hue API-Schlüssel ungültig',
        'solutions': [
            'API-Schlüssel neu generieren',
            'Bridge-Button drücken und innerhalb 30 Sek. neue Verbindung',
            'HUE_USERNAME in .env Datei aktualisieren',
            'Onboarding-Prozess erneut durchlaufen'
        ],
        'technical': 'Authentifizierung fehlgeschlagen',
        'user_action': 'API-Key erneuern'
    },
    'database_connection': {
        'title': 'Datenbankverbindung fehlgeschlagen',
        'solutions': [
            'MariaDB/MySQL Service prüfen: systemctl status mariadb',
            'Datenbank-Credentials in .env überprüfen',
            'Benutzerberechtigungen kontrollieren',
            'test_db.py zur Diagnose ausführen'
        ],
        'technical': 'MySQL-Verbindungsproblem',
        'user_action': 'DB-Service prüfen'
    },
    'audio_system': {
        'title': 'Audio-System nicht verfügbar',
        'solutions': [
            'Audio-Dependencies installieren: pip install pyaudio scipy',
            'Audio-Geräte-Berechtigungen prüfen',
            'ALSA/PulseAudio-Konfiguration überprüfen',
            'Verfügbare Audio-Geräte testen'
        ],
        'technical': 'Audio-Bibliotheken oder Hardware nicht verfügbar',
        'user_action': 'Audio-Setup prüfen'
    },
    'light_control': {
        'title': 'Lichtsteuerung fehlgeschlagen',
        'solutions': [
            'Licht-ID überprüfen (evtl. wurde Licht entfernt)',
            'Bridge-Verbindung testen',
            'Licht manuell über Philips Hue App testen',
            'Lichter neu in Bridge einlernen'
        ],
        'technical': 'Hue API Lichtsteuerungs-Fehler',
        'user_action': 'Licht-Status prüfen'
    },
    'effect_system': {
        'title': 'Effekt konnte nicht gestartet werden',
        'solutions': [
            'Aktive Effekte beenden und erneut versuchen',
            'Thread-Pool-Status prüfen',
            'Server neu starten falls nötig',
            'Einzelne Lichter statt Gruppe testen'
        ],
        'technical': 'Threading oder Effekt-Engine Problem',
        'user_action': 'Effekte zurücksetzen'
    },
    'config_error': {
        'title': 'Konfigurationsfehler',
        'solutions': [
            '.env Datei auf Syntax-Fehler prüfen',
            'Alle erforderlichen Umgebungsvariablen setzen',
            'Beispiel-Konfiguration aus README verwenden',
            'Onboarding erneut durchlaufen'
        ],
        'technical': 'Fehlende oder ungültige Konfigurationswerte',
        'user_action': 'Konfiguration prüfen'
    }
}

class SmartErrorHandler:
    """Intelligenter Error-Handler mit Diagnose und Lösungsvorschlägen"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.error_count = {}
        self.last_errors = []
        self.max_error_history = 50
    
    def categorize_error(self, error: Exception, context: str = None) -> str:
        """Kategorisiere Fehler basierend auf Exception-Typ und Kontext"""
        error_str = str(error).lower()
        error_type = type(error).__name__
        
        # Hue Bridge Verbindungsfehler
        if any(keyword in error_str for keyword in ['connection', 'timeout', 'unreachable']):
            if 'bridge' in (context or '').lower():
                return 'hue_bridge_connection'
        
        # API-Key Probleme
        if any(keyword in error_str for keyword in ['unauthorized', 'api key', 'authentication']):
            return 'hue_api_key'
        
        # Datenbank-Fehler
        if error_type in ['DatabaseError', 'OperationalError'] or 'mysql' in error_str:
            return 'database_connection'
        
        # Audio-Fehler
        if 'audio' in error_str or error_type == 'ImportError' and 'pyaudio' in error_str:
            return 'audio_system'
        
        # Lichtsteuerungs-Fehler
        if 'light' in (context or '').lower() or 'hue' in error_str:
            return 'light_control'
        
        # Effekt-Fehler
        if 'effect' in (context or '').lower() or 'thread' in error_str:
            return 'effect_system'
        
        # Konfigurationsfehler
        if 'config' in error_str or 'env' in error_str:
            return 'config_error'
        
        return 'general_error'
    
    def handle_error(self, error: Exception, context: str = None, user_data: Dict = None) -> Dict[str, Any]:
        """Hauptfunktion für Fehlerbehandlung"""
        error_category = self.categorize_error(error, context)
        
        # Error-Count für Trend-Analyse
        self.error_count[error_category] = self.error_count.get(error_category, 0) + 1
        
        # Error-Info erstellen
        error_info = {
            'timestamp': datetime.now().isoformat(),
            'category': error_category,
            'error_type': type(error).__name__,
            'message': str(error),
            'context': context,
            'count': self.error_count[error_category],
            'solutions': ERROR_SOLUTIONS.get(error_category, {
                'title': 'Unbekannter Fehler',
                'solutions': ['Logs prüfen', 'Server neu starten', 'Support kontaktieren'],
                'technical': str(error),
                'user_action': 'Diagnose durchführen'
            })
        }
        
        # Trace für Development
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            error_info['traceback'] = traceback.format_exc()
        
        # Error-History aktualisieren
        self.last_errors.append(error_info)
        if len(self.last_errors) > self.max_error_history:
            self.last_errors.pop(0)
        
        # Logging
        self.logger.error(f"[{error_category}] {error_info['message']}")
        if context:
            self.logger.error(f"Context: {context}")
        
        return error_info
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """Fehlerstatistiken für Monitoring"""
        return {
            'error_counts': self.error_count,
            'total_errors': sum(self.error_count.values()),
            'categories': list(self.error_count.keys()),
            'most_common': max(self.error_count.items(), key=lambda x: x[1]) if self.error_count else None,
            'recent_errors': self.last_errors[-10:]  # Letzte 10 Fehler
        }
    
    def diagnose_system_health(self) -> Dict[str, Any]:
        """System-Gesundheitscheck mit Diagnose"""
        health_report = {
            'timestamp': datetime.now().isoformat(),
            'status': 'healthy',
            'checks': {},
            'recommendations': []
        }
        
        # Hue Bridge Test
        try:
            import os
            bridge_ip = os.getenv('HUE_BRIDGE_IP')
            username = os.getenv('HUE_USERNAME')
            
            if bridge_ip and username:
                response = requests.get(f"http://{bridge_ip}/api/{username}/lights", timeout=5)
                if response.status_code == 200:
                    health_report['checks']['hue_bridge'] = 'ok'
                else:
                    health_report['checks']['hue_bridge'] = 'error'
                    health_report['status'] = 'degraded'
                    health_report['recommendations'].append('Hue Bridge API-Zugriff prüfen')
            else:
                health_report['checks']['hue_bridge'] = 'config_missing'
                health_report['recommendations'].append('Hue Bridge Konfiguration vervollständigen')
        except Exception as e:
            health_report['checks']['hue_bridge'] = f'error: {str(e)}'
            health_report['status'] = 'degraded'
        
        # Datenbank Test
        try:
            import os
            db_config = {
                'host': os.getenv('DB_HOST', 'localhost'),
                'user': os.getenv('DB_USER', 'root'),
                'password': os.getenv('DB_PASSWORD', ''),
                'database': os.getenv('DB_NAME', 'hue_monitoring'),
            }
            
            conn = mysql.connector.connect(**db_config)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            health_report['checks']['database'] = 'ok'
            conn.close()
        except Exception as e:
            health_report['checks']['database'] = f'error: {str(e)}'
            health_report['status'] = 'degraded'
            health_report['recommendations'].append('Datenbank-Verbindung prüfen')
        
        # Audio System Test
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            device_count = p.get_device_count()
            p.terminate()
            health_report['checks']['audio_system'] = f'ok ({device_count} devices)'
        except ImportError:
            health_report['checks']['audio_system'] = 'libraries_missing'
            health_report['recommendations'].append('Audio-Libraries installieren: pip install pyaudio scipy')
        except Exception as e:
            health_report['checks']['audio_system'] = f'error: {str(e)}'
        
        # Error-Rate Analysis
        total_errors = sum(self.error_count.values())
        if total_errors > 20:
            health_report['status'] = 'degraded'
            health_report['recommendations'].append(f'Hohe Fehlerrate ({total_errors} Fehler) - System-Logs prüfen')
        
        return health_report

# Decorator für automatische Fehlerbehandlung
def smart_error_handler(context: str = None):
    """Decorator für automatische Fehlerbehandlung in Flask-Routes"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_handler = SmartErrorHandler()
                error_info = error_handler.handle_error(e, context or func.__name__)
                
                # Flask JSON Response
                from flask import jsonify
                return jsonify({
                    'success': False,
                    'error': {
                        'category': error_info['category'],
                        'message': error_info['message'],
                        'title': error_info['solutions']['title'],
                        'solutions': error_info['solutions']['solutions'],
                        'user_action': error_info['solutions']['user_action'],
                        'technical_details': error_info['solutions']['technical'],
                        'error_id': f"{error_info['category']}_{error_info['count']}"
                    }
                }), 500
        return wrapper
    return decorator

# Globale Error-Handler Instanz
global_error_handler = SmartErrorHandler()

# Utility-Funktionen
def log_system_error(error: Exception, context: str = None, extra_data: Dict = None):
    """Utility-Funktion für manuelles Error-Logging"""
    return global_error_handler.handle_error(error, context, extra_data)

def get_system_health():
    """Utility-Funktion für System-Health-Check"""
    return global_error_handler.diagnose_system_health()

def get_error_stats():
    """Utility-Funktion für Error-Statistiken"""
    return global_error_handler.get_error_statistics()

# Beispiel-Verwendung
if __name__ == "__main__":
    # Test der Error-Handler
    handler = SmartErrorHandler()
    
    # Simuliere verschiedene Fehlertypen
    try:
        raise requests.ConnectionError("Connection to Hue Bridge failed")
    except Exception as e:
        error_info = handler.handle_error(e, "hue_bridge_test")
        print(f"Error handled: {error_info['solutions']['title']}")
        print(f"Solutions: {error_info['solutions']['solutions']}")
    
    # System-Health Check
    health = handler.diagnose_system_health()
    print(f"\nSystem Status: {health['status']}")
    print(f"Checks: {health['checks']}")
    if health['recommendations']:
        print(f"Recommendations: {health['recommendations']}")