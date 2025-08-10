"""
PIR Motion Sensor Manager for Hue Controller
Manages PIR sensor detection and triggers automatic lighting
"""

import time
import threading
import logging
from typing import Callable, Optional
import requests
import json
from datetime import datetime, timedelta
import math

# Try to import gpiozero for Raspberry Pi 5 compatibility
try:
    from gpiozero import MotionSensor
    GPIO_AVAILABLE = True
    print("Using gpiozero for PIR sensor (Raspberry Pi 5 compatible)")
except (ImportError, RuntimeError) as e:
    # This will happen on non-Raspberry Pi systems or when GPIO is not available
    GPIO_AVAILABLE = False
    print(f"Warning: GPIO not available for PIR sensor - {e}")
    
    # Create a mock MotionSensor for testing
    class MockMotionSensor:
        def __init__(self, pin):
            self.pin = pin
        
        @property
        def motion_detected(self):
            return False
        
        def close(self):
            pass
    
    MotionSensor = MockMotionSensor

class PIRManager:
    def __init__(self, hue_bridge_ip: str, hue_username: str, db_pool=None):
        """
        Initialize PIR Motion Sensor Manager
        
        Args:
            hue_bridge_ip: IP address of the Hue bridge
            hue_username: Hue bridge username for API access
            db_pool: Database connection pool for logging
        """
        self.hue_bridge_ip = hue_bridge_ip
        self.hue_username = hue_username
        self.db_pool = db_pool
        
        # PIR Configuration
        self.pir_pin = 23  # GPIO Pin für PIR Sensor (working pin confirmed by detect.py test)
        self.garden_group_id = "86"  # Garten Gruppe ID
        self.light_duration = 600  # 10 Minuten in Sekunden
        
        # State management
        self.running = False
        self.thread = None
        self.monitor_thread = None
        self.gpio_available = GPIO_AVAILABLE
        self.last_motion_time = 0
        self.motion_cooldown = 30  # 30 Sekunden Pause zwischen Bewegungserkennungen
        self.garden_timer = None
        self.garden_timer_start_time = None
        self.lights_manually_controlled = False
        self.pir_sensor = None  # gpiozero MotionSensor instance
        
        # NEW: Motion Detection Settings
        self.motion_detection_enabled = True  # Toggle für Bewegungserkennung
        self.daylight_detection_enabled = True  # Nur bei Sonnenuntergang aktiv
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
    
    def calculate_sunrise_sunset_berlin(self, date=None):
        """
        Berechnet Sonnenauf- und -untergang für Berlin für ein gegebenes Datum
        Approximation basierend auf astronomischen Formeln
        
        Args:
            date: datetime object, Standard ist heute
            
        Returns:
            tuple: (sunrise_time, sunset_time) als datetime objects
        """
        if date is None:
            date = datetime.now()
        
        # Berlin Koordinaten
        latitude = 52.5200  # Grad Nord
        longitude = 13.4050  # Grad Ost
        
        # Tag des Jahres
        day_of_year = date.timetuple().tm_yday
        
        # Approximationsformeln für Sonnenauf- und -untergang
        # Declination of the sun
        declination = 23.45 * math.sin(math.radians(360 * (284 + day_of_year) / 365))
        
        # Hour angle
        hour_angle_deg = math.degrees(math.acos(-math.tan(math.radians(latitude)) * math.tan(math.radians(declination))))
        
        # Sunrise and sunset times (in decimal hours from solar noon)
        sunrise_hours = 12 - (hour_angle_deg / 15) + (longitude / 15) - 1  # -1 for CET
        sunset_hours = 12 + (hour_angle_deg / 15) + (longitude / 15) - 1   # -1 for CET
        
        # Convert to datetime objects
        sunrise_time = date.replace(hour=int(sunrise_hours), 
                                   minute=int((sunrise_hours % 1) * 60), 
                                   second=0, microsecond=0)
        
        sunset_time = date.replace(hour=int(sunset_hours), 
                                  minute=int((sunset_hours % 1) * 60), 
                                  second=0, microsecond=0)
        
        return sunrise_time, sunset_time
    
    def is_nighttime(self):
        """
        Prüft ob es aktuell Nacht ist (nach Sonnenuntergang und vor Sonnenaufgang)
        
        Returns:
            bool: True wenn es Nacht ist, False wenn Tag
        """
        if not self.daylight_detection_enabled:
            return True  # Wenn Tageslichteerkennung deaktiviert, immer als Nacht behandeln
        
        now = datetime.now()
        sunrise, sunset = self.calculate_sunrise_sunset_berlin(now)
        
        # Prüfen ob es zwischen Sonnenuntergang und Sonnenaufgang ist
        if now < sunrise or now > sunset:
            return True  # Es ist Nacht
        else:
            return False  # Es ist Tag
        
    def setup_pir_sensor(self):
        """Setup PIR sensor using gpiozero"""
        if not self.gpio_available:
            self.logger.warning("GPIO not available - PIR sensor running in simulation mode")
            return False
            
        try:
            self.pir_sensor = MotionSensor(self.pir_pin)
            self.logger.info(f"PIR sensor setup completed on GPIO pin {self.pir_pin}")
            print(f"🔍 PIR Sensor: Setup completed on GPIO pin {self.pir_pin} (gpiozero)")
            return True
        except Exception as e:
            self.logger.error(f"Error setting up PIR sensor on pin {self.pir_pin}: {e}")
            print(f"❌ PIR Sensor: Error setting up on pin {self.pir_pin}: {e}")
            return False
    
    def turn_on_garden_lights(self):
        """Turn on garden lights (group 86) for specified duration with warm white at 100%"""
        try:
            base_url = f"http://{self.hue_bridge_ip}/api/{self.hue_username}"
            
            # Turn on garden lights with warm white at 100% brightness
            # Forget previous color/brightness settings as requested
            payload = {
                'on': True,
                'bri': 254,  # 100% brightness (254 is max in Hue API)
                'ct': 370,   # Warm white (2700K) - perfect for outdoor security lighting
                'transitiontime': 2  # Quick 0.2s transition for immediate lighting
            }
            
            print(f"🌱 PIR: Schalte Garten-Beleuchtung ein für {self.light_duration/60} Minuten (Warmweiß 100%)")
            response = requests.put(
                f"{base_url}/groups/{self.garden_group_id}/action",
                json=payload,
                timeout=5
            )
            
            if response.status_code == 200:
                self.logger.info(f"Garden lights activated for {self.light_duration} seconds (warm white 100%)")
                print(f"✅ PIR: Garten-Beleuchtung aktiviert (Warmweiß 100%)")
                
                # Mark as PIR-controlled (not manually controlled)
                self.lights_manually_controlled = False
                
                # Schedule automatic turn-off after duration
                self.schedule_garden_turn_off()
                
                # Log to database if available
                self._log_motion_detection(True)
                
            else:
                self.logger.error(f"Failed to turn on garden lights: {response.status_code} - {response.text}")
                print(f"❌ PIR: Fehler beim Einschalten der Garten-Beleuchtung: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Network error turning on garden lights: {e}")
            print(f"❌ PIR: Netzwerkfehler: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error turning on garden lights: {e}")
            print(f"❌ PIR: Unerwarteter Fehler: {e}")
    
    def turn_off_garden_lights(self):
        """Turn off garden lights"""
        try:
            base_url = f"http://{self.hue_bridge_ip}/api/{self.hue_username}"
            
            payload = {'on': False}
            
            print("🌱 PIR: Schalte Garten-Beleuchtung aus (Timer abgelaufen)")
            response = requests.put(
                f"{base_url}/groups/{self.garden_group_id}/action",
                json=payload,
                timeout=5
            )
            
            if response.status_code == 200:
                self.logger.info("Garden lights turned off automatically")
                print("✅ PIR: Garten-Beleuchtung automatisch ausgeschaltet")
            else:
                self.logger.error(f"Failed to turn off garden lights: {response.status_code} - {response.text}")
                print(f"❌ PIR: Fehler beim Ausschalten: {response.status_code}")
                
        except Exception as e:
            self.logger.error(f"Error turning off garden lights: {e}")
            print(f"❌ PIR: Fehler beim Ausschalten: {e}")
    
    def schedule_garden_turn_off(self):
        """Schedule automatic turn-off of garden lights"""
        # Cancel existing timer if any
        if self.garden_timer:
            self.garden_timer.cancel()
        
        # Record timer start time for monitoring
        self.garden_timer_start_time = time.time()
        
        # Create new timer
        self.garden_timer = threading.Timer(self.light_duration, self.turn_off_garden_lights)
        self.garden_timer.daemon = True
        self.garden_timer.start()
        print(f"⏰ PIR: Timer gesetzt für {self.light_duration/60} Minuten")
    
    def detect_motion(self):
        """Main motion detection loop using gpiozero"""
        print("🔍 PIR Sensor: Warte auf Bewegung...")
        self.logger.info("PIR motion detection started")
        
        while self.running:
            try:
                # Prüfe zuerst ob Bewegungserkennung aktiviert ist
                if not self.motion_detection_enabled:
                    time.sleep(5)  # Längere Pause wenn deaktiviert
                    continue
                
                # Prüfe ob es Nacht ist (nur dann aktiv)
                if not self.is_nighttime():
                    time.sleep(30)  # Tagsüber längere Pause
                    continue
                
                if self.gpio_available and self.pir_sensor and self.pir_sensor.motion_detected:
                    current_time = time.time()
                    
                    # Check cooldown period to avoid rapid triggering
                    if current_time - self.last_motion_time > self.motion_cooldown:
                        sunrise, sunset = self.calculate_sunrise_sunset_berlin()
                        print(f"🚶 PIR: Bewegung erkannt! (Nachtzeit: {sunset.strftime('%H:%M')} - {sunrise.strftime('%H:%M')})")
                        self.logger.info(f"Motion detected by PIR sensor during nighttime")
                        
                        # Turn on garden lights
                        self.turn_on_garden_lights()
                        
                        # Update last motion time
                        self.last_motion_time = current_time
                    else:
                        print("🔄 PIR: Bewegung erkannt (Cooldown aktiv)")
                
                time.sleep(1)  # Check every second
                
            except Exception as e:
                self.logger.error(f"Error in motion detection loop: {e}")
                print(f"❌ PIR: Fehler in Bewegungserkennung: {e}")
                time.sleep(5)  # Wait longer on error
    
    def _log_motion_detection(self, success: bool):
        """Log motion detection events to database"""
        if not self.db_pool:
            return
            
        try:
            conn = self.db_pool.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO motion_detection_log 
                (timestamp, sensor_pin, group_id, action_taken, success)
                VALUES (NOW(), %s, %s, %s, %s)
            """, (self.pir_pin, self.garden_group_id, 'lights_on', success))
            
            conn.commit()
            cursor.close()
            conn.close()
            
        except Exception as e:
            self.logger.error(f"Error logging motion detection: {e}")
    
    def start_monitoring(self):
        """Start PIR motion monitoring in a separate thread"""
        if self.running:
            self.logger.warning("PIR monitoring is already running")
            print("⚠️ PIR Sensor: Monitoring läuft bereits")
            return
        
        # Setup PIR sensor
        if not self.setup_pir_sensor():
            if not self.gpio_available:
                print("⚠️ PIR Sensor: Läuft im Simulationsmodus (kein GPIO verfügbar)")
            else:
                print("❌ PIR Sensor: Setup fehlgeschlagen")
                return
        
        self.running = True
        self.thread = threading.Thread(target=self.detect_motion, daemon=True)
        self.thread.start()
        
        self.logger.info("PIR motion monitoring started")
        print("✅ PIR Sensor: Monitoring gestartet")
    
    def stop_monitoring(self):
        """Stop PIR motion monitoring and cleanup resources"""
        if not self.running:
            return
        
        self.running = False
        
        # Cancel any pending timer
        if self.garden_timer:
            self.garden_timer.cancel()
            self.garden_timer = None
        
        # Wait for thread to finish
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        
        # Cleanup PIR sensor
        if self.gpio_available and self.pir_sensor:
            try:
                self.pir_sensor.close()
                print("🔍 PIR Sensor: Cleanup completed")
            except Exception as e:
                print(f"⚠️ PIR Sensor: Cleanup error: {e}")
        
        self.logger.info("PIR motion monitoring stopped")
        print("⏹️ PIR Sensor: Monitoring gestoppt")
    
    def get_status(self) -> dict:
        """Get current PIR sensor status"""
        # Berechne aktuelle Sonnenzeiten
        sunrise, sunset = self.calculate_sunrise_sunset_berlin()
        is_night = self.is_nighttime()
        
        return {
            'running': self.running,
            'gpio_available': self.gpio_available,
            'pir_pin': self.pir_pin,
            'garden_group_id': self.garden_group_id,
            'light_duration_minutes': self.light_duration / 60,
            'motion_cooldown_seconds': self.motion_cooldown,
            'last_motion_time': self.last_motion_time,
            'timer_active': self.garden_timer is not None and self.garden_timer.is_alive() if self.garden_timer else False,
            # NEW: Motion detection settings
            'motion_detection_enabled': self.motion_detection_enabled,
            'daylight_detection_enabled': self.daylight_detection_enabled,
            'is_nighttime': is_night,
            'sunrise_today': sunrise.strftime('%H:%M'),
            'sunset_today': sunset.strftime('%H:%M'),
            'motion_active': self.motion_detection_enabled and is_night
        }
    
    def test_motion_trigger(self):
        """Manually trigger motion detection for testing"""
        print("🧪 PIR: Test-Bewegung ausgelöst")
        self.logger.info("Manual motion trigger for testing")
        self.turn_on_garden_lights()
        return True
    
    def set_motion_detection_enabled(self, enabled: bool):
        """
        Aktiviert/deaktiviert die Bewegungserkennung
        
        Args:
            enabled: True um zu aktivieren, False um zu deaktivieren
        """
        self.motion_detection_enabled = enabled
        status_text = "aktiviert" if enabled else "deaktiviert"
        print(f"🔧 PIR: Bewegungserkennung {status_text}")
        self.logger.info(f"Motion detection {'enabled' if enabled else 'disabled'}")
        
    def set_daylight_detection_enabled(self, enabled: bool):
        """
        Aktiviert/deaktiviert die Tageslichteerkennung
        
        Args:
            enabled: True für zeitbasierte Aktivierung, False für 24h Betrieb
        """
        self.daylight_detection_enabled = enabled
        status_text = "aktiviert (nur nachts)" if enabled else "deaktiviert (24h Betrieb)"
        print(f"🔧 PIR: Tageslichteerkennung {status_text}")
        self.logger.info(f"Daylight detection {'enabled' if enabled else 'disabled'}")
    
    def get_sunrise_sunset_info(self, days=7) -> dict:
        """
        Gibt Sonnenauf- und -untergangszeiten für mehrere Tage zurück
        
        Args:
            days: Anzahl der Tage (Standard: 7)
            
        Returns:
            dict: Sonnenzeiten für die nächsten Tage
        """
        info = {}
        today = datetime.now()
        
        for i in range(days):
            date = today + timedelta(days=i)
            sunrise, sunset = self.calculate_sunrise_sunset_berlin(date)
            
            day_name = date.strftime("%A") if i == 0 else date.strftime("%A")
            if i == 0:
                day_name = "Heute"
            elif i == 1:
                day_name = "Morgen"
            
            info[date.strftime("%Y-%m-%d")] = {
                'day_name': day_name,
                'date': date.strftime("%d.%m.%Y"),
                'sunrise': sunrise.strftime("%H:%M"),
                'sunset': sunset.strftime("%H:%M"),
                'daylight_hours': f"{(sunset - sunrise).seconds // 3600}h {((sunset - sunrise).seconds % 3600) // 60}min"
            }
        
        return info