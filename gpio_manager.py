"""
GPIO Manager Module for Custom Button Controls
Handles GPIO button detection and triggers Hue group actions
"""

import time
import threading
import logging
from typing import Dict, Callable, Optional
import requests
import json

# Try to import gpiozero, but handle gracefully if not available or on non-Pi hardware
try:
    from gpiozero import Button
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError) as e:
    # This will happen on non-Raspberry Pi systems or when GPIO is not available
    GPIO_AVAILABLE = False
    print(f"Warning: GPIO not available - {e}")
    
    # Create a mock Button class for testing
    class Button:
        def __init__(self, pin, pull_up=True, bounce_time=0.1):
            self.pin = pin
            self.when_pressed = None
            
        def close(self):
            pass

class GPIOManager:
    def __init__(self, hue_bridge_ip: str, hue_username: str, db_pool=None):
        """
        Initialize GPIO Manager
        
        Args:
            hue_bridge_ip: IP address of the Hue bridge
            hue_username: Hue bridge username for API access
            db_pool: Database connection pool for logging and configuration
        """
        self.hue_bridge_ip = hue_bridge_ip
        self.hue_username = hue_username
        self.db_pool = db_pool
        self.buttons: Dict[int, Button] = {}
        self.button_configs: Dict[int, dict] = {}
        self.last_press_times: Dict[int, float] = {}
        self.double_press_threshold = 0.5  # seconds
        self.running = False
        self.thread = None
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        self.gpio_available = GPIO_AVAILABLE
        
    def load_button_configurations(self):
        """Load button configurations from database"""
        if not self.db_pool:
            self.logger.warning("No database pool available for button configurations")
            return
            
        try:
            conn = self.db_pool.get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT gpio_pin, group_id, action_type, enabled, strobo_color, strobo_duration, strobo_mode
                FROM button_configurations 
                WHERE enabled = 1
            """)
            
            configurations = cursor.fetchall()
            self.button_configs = {}
            
            for config in configurations:
                pin = config['gpio_pin']
                self.button_configs[pin] = {
                    'group_id': config['group_id'],
                    'action_type': config['action_type'],  # 'toggle', 'on', 'off', 'strobo_push'
                    'enabled': config['enabled'],
                    'strobo_color': config['strobo_color'],
                    'strobo_duration': config['strobo_duration'] or 5,
                    'strobo_mode': config['strobo_mode'] or 'classic'
                }
                
            self.logger.info(f"Loaded {len(configurations)} button configurations")
            cursor.close()
            conn.close()
            
        except Exception as e:
            self.logger.error(f"Error loading button configurations: {e}")
    
    def setup_button(self, gpio_pin: int):
        """Setup a GPIO button with proper event handling - based on working example"""
        try:
            # Initialize button with pull-up resistor and debouncing (like the working example)
            button = Button(gpio_pin, pull_up=True, bounce_time=0.2)  # 200ms like example
            
            # Create press handler for this specific pin (exactly like the example)
            def on_press():
                self.logger.info(f"🔘 GPIO {gpio_pin}: Button pressed detected!")
                print(f"🔘 GPIO {gpio_pin}: Button pressed detected!")  # Also print to console
                self._handle_button_press(gpio_pin)
            
            # Create release handler for debugging
            def on_release():
                print(f"🔘 GPIO {gpio_pin}: Button released!")
            
            button.when_pressed = on_press
            button.when_released = on_release
            self.buttons[gpio_pin] = button
            self.last_press_times[gpio_pin] = 0
            
            # Test the button state immediately
            print(f"🔘 GPIO {gpio_pin}: Initial button state: is_pressed={button.is_pressed}")
            
            self.logger.info(f"Button setup completed for GPIO pin {gpio_pin} (bounce_time=0.2s)")
            print(f"🔘 GPIO Manager: Button {gpio_pin} setup completed and monitoring started")
            
        except Exception as e:
            self.logger.error(f"Error setting up button on pin {gpio_pin}: {e}")
            print(f"❌ GPIO Manager: Error setting up button on pin {gpio_pin}: {e}")
    
    def _handle_button_press(self, gpio_pin: int):
        """Handle button press events with single/double press detection - like working example"""
        print(f"🔘 _handle_button_press called for GPIO {gpio_pin}")
        
        if gpio_pin not in self.button_configs:
            self.logger.warning(f"No configuration found for GPIO pin {gpio_pin}")
            print(f"⚠️ No configuration found for GPIO pin {gpio_pin}")
            return
            
        now = time.time()
        last_press = self.last_press_times.get(gpio_pin, 0)
        time_since_last = now - last_press
        
        config = self.button_configs[gpio_pin]
        group_id = config['group_id']
        action_type = config['action_type']
        
        # Determine press type (exactly like your example)
        if time_since_last < self.double_press_threshold:
            print(f"🔘 GPIO {gpio_pin}: DOPPEL-PUSH erkannt!")
            self.logger.info(f"GPIO {gpio_pin}: DOPPEL-PUSH erkannt!")
            is_double_press = True
            # Double press always triggers 'off' action, regardless of configured action
            action_to_execute = 'off'
        else:
            print(f"🔘 GPIO {gpio_pin}: Taster gedrückt (Single Press)")
            self.logger.info(f"GPIO {gpio_pin}: Taster gedrückt (Single Press)")
            is_double_press = False
            action_to_execute = action_type
        
        try:
            print(f"🔘 Executing action '{action_to_execute}' on group {group_id}")
            
            # Handle strobo_push action specially
            if action_to_execute == 'strobo_push':
                self._execute_strobo_action(gpio_pin, group_id)
            else:
                self._execute_hue_action(group_id, action_to_execute)
                
            # Log button press to database
            self._log_button_press(gpio_pin, is_double_press, group_id, action_to_execute)
            
        except Exception as e:
            self.logger.error(f"Error handling button press on pin {gpio_pin}: {e}")
            print(f"❌ Error handling button press on pin {gpio_pin}: {e}")
        
        self.last_press_times[gpio_pin] = now
    
    def _execute_hue_action(self, group_id: int, action: str):
        """Execute Hue API action on specified group"""
        print(f"🔘 _execute_hue_action: group_id={group_id}, action={action}")
        
        try:
            base_url = f"http://{self.hue_bridge_ip}/api/{self.hue_username}"
            
            if action == 'toggle':
                print(f"🔘 Getting current state for group {group_id}")
                # First get current state
                response = requests.get(f"{base_url}/groups/{group_id}")
                if response.status_code == 200:
                    group_data = response.json()
                    # Handle both dict and list responses from Hue API
                    if isinstance(group_data, dict):
                        current_state = group_data.get('state', {}).get('any_on', False)
                    else:  # Handle list response
                        current_state = False  # Default to off
                    new_state = not current_state
                    print(f"🔘 Current state: {current_state}, new state: {new_state}")
                else:
                    # Default to on if we can't get current state
                    new_state = True
                    print(f"🔘 Could not get current state, defaulting to: {new_state}")
                    
                payload = {'on': new_state}
                
            elif action == 'on':
                payload = {'on': True, 'bri': 254}
                print(f"🔘 Action ON: payload = {payload}")
                
            elif action == 'off':
                payload = {'on': False}
                print(f"🔘 Action OFF: payload = {payload}")
                
            else:
                self.logger.error(f"Unknown action type: {action}")
                print(f"❌ Unknown action type: {action}")
                return
            
            # Execute the action
            print(f"🔘 Sending to Hue API: PUT {base_url}/groups/{group_id}/action with {payload}")
            response = requests.put(
                f"{base_url}/groups/{group_id}/action",
                json=payload,
                timeout=5
            )
            
            if response.status_code == 200:
                self.logger.info(f"Successfully executed {action} on group {group_id}")
                print(f"✅ Successfully executed {action} on group {group_id}")
                print(f"🔘 Hue API response: {response.text}")
            else:
                self.logger.error(f"Hue API error: {response.status_code} - {response.text}")
                print(f"❌ Hue API error: {response.status_code} - {response.text}")
                
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Network error executing Hue action: {e}")
            print(f"❌ Network error executing Hue action: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error executing Hue action: {e}")
            print(f"❌ Unexpected error executing Hue action: {e}")
    
    def _execute_strobo_action(self, gpio_pin: int, group_id: int):
        """Execute strobo effect with configured parameters"""
        print(f"🔘 _execute_strobo_action: gpio_pin={gpio_pin}, group_id={group_id}")
        
        config = self.button_configs[gpio_pin]
        strobo_color = config.get('strobo_color', '#ff0000')  # Default red
        strobo_duration = config.get('strobo_duration', 5)    # Default 5 seconds
        strobo_mode = config.get('strobo_mode', 'classic')    # Default classic
        
        print(f"🔘 Strobo config: color={strobo_color}, duration={strobo_duration}s, mode={strobo_mode}")
        
        try:
            # Use the existing strobe API endpoint from the main app
            base_url = f"http://127.0.0.1:5000"  # Local Flask app
            
            payload = {
                'target_type': 'group',
                'target_id': group_id,
                'duration': strobo_duration,
                'mode': strobo_mode,
                'restore_state': True  # Always restore state after button strobo
            }
            
            # Convert hex color to hue/sat if provided
            if strobo_color and strobo_color.startswith('#'):
                hue_sat = self._hex_to_hue_sat(strobo_color)
                if hue_sat:
                    payload['hue'] = hue_sat[0]
                    payload['sat'] = hue_sat[1]
            
            print(f"🔘 Sending strobo request: POST {base_url}/api/effects/strobe with {payload}")
            response = requests.post(
                f"{base_url}/api/effects/strobe",
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                self.logger.info(f"Successfully started strobo on group {group_id}")
                print(f"✅ Successfully started strobo on group {group_id}")
                print(f"🔘 Strobo API response: {response.text}")
            else:
                self.logger.error(f"Strobo API error: {response.status_code} - {response.text}")
                print(f"❌ Strobo API error: {response.status_code} - {response.text}")
                
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Network error executing strobo action: {e}")
            print(f"❌ Network error executing strobo action: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error executing strobo action: {e}")
            print(f"❌ Unexpected error executing strobo action: {e}")
    
    def _hex_to_hue_sat(self, hex_color: str):
        """Convert hex color to Hue hue/saturation values"""
        try:
            # Remove # if present
            hex_color = hex_color.lstrip('#')
            
            # Convert to RGB
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0
            
            # Convert RGB to HSV
            max_val = max(r, g, b)
            min_val = min(r, g, b)
            diff = max_val - min_val
            
            if diff == 0:
                hue = 0
            elif max_val == r:
                hue = (60 * ((g - b) / diff) + 360) % 360
            elif max_val == g:
                hue = (60 * ((b - r) / diff) + 120) % 360
            else:
                hue = (60 * ((r - g) / diff) + 240) % 360
            
            sat = 0 if max_val == 0 else diff / max_val
            
            # Convert to Hue values (0-65535 for hue, 0-254 for saturation)
            hue_val = int((hue / 360.0) * 65535)
            sat_val = int(sat * 254)
            
            return (hue_val, sat_val)
            
        except Exception as e:
            print(f"❌ Error converting hex color {hex_color}: {e}")
            return None
    
    def _log_button_press(self, gpio_pin: int, is_double_press: bool, group_id: int, action_type: str):
        """Log button press events to database"""
        if not self.db_pool:
            return
            
        try:
            conn = self.db_pool.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO button_press_log 
                (gpio_pin, press_type, group_id, action_type, timestamp)
                VALUES (%s, %s, %s, %s, NOW())
            """, (gpio_pin, 'double' if is_double_press else 'single', group_id, action_type))
            
            conn.commit()
            cursor.close()
            conn.close()
            
        except Exception as e:
            self.logger.error(f"Error logging button press: {e}")
    
    def start_monitoring(self):
        """Start GPIO monitoring in a separate thread"""
        if self.running:
            self.logger.warning("GPIO monitoring is already running")
            print("⚠️ GPIO monitoring is already running")
            return
            
        self.running = True
        print("🔘 GPIO Manager: Loading button configurations...")
        self.load_button_configurations()
        
        if not self.gpio_available:
            self.logger.warning("GPIO hardware not available - running in simulation mode")
            print("⚠️ GPIO hardware not available - running in simulation mode")
            return
        
        print(f"🔘 GPIO Manager: Setting up {len(self.button_configs)} buttons...")
        # Setup buttons based on configurations
        for gpio_pin in self.button_configs.keys():
            print(f"🔘 Setting up button for GPIO pin {gpio_pin}")
            self.setup_button(gpio_pin)
        
        self.logger.info(f"Started GPIO monitoring for {len(self.buttons)} buttons")
        print(f"✅ GPIO Manager: Started monitoring for {len(self.buttons)} buttons")
        print(f"🔘 Configured pins: {list(self.button_configs.keys())}")
    
    def stop_monitoring(self):
        """Stop GPIO monitoring and cleanup resources"""
        if not self.running:
            return
            
        self.running = False
        
        # Clean up GPIO buttons
        for button in self.buttons.values():
            button.close()
        
        self.buttons.clear()
        self.button_configs.clear()
        self.last_press_times.clear()
        
        self.logger.info("Stopped GPIO monitoring")
    
    def reload_configurations(self):
        """Reload button configurations and restart monitoring"""
        self.logger.info("Reloading button configurations")
        print("🔄 GPIO Manager: Reloading button configurations...")
        self.stop_monitoring()
        time.sleep(0.5)  # Brief pause for cleanup
        self.start_monitoring()
    
    def get_button_status(self) -> dict:
        """Get current status of all configured buttons"""
        return {
            'running': self.running,
            'gpio_available': self.gpio_available,
            'configured_pins': list(self.button_configs.keys()),
            'active_buttons': len(self.buttons),
            'configurations': self.button_configs
        }