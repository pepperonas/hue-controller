#!/usr/bin/env python3
"""
Disco Mode Audio-Reactive Controller for Hue Lights
Simplified version for integration with main app
"""

import pyaudio
import numpy as np
import time
import threading
import requests
from scipy import signal
from scipy.fft import fft, fftfreq

class DiscoMode:
    def __init__(self, hue_bridge_ip, hue_username):
        self.hue_bridge_ip = hue_bridge_ip
        self.hue_username = hue_username
        self.hue_base_url = f"http://{hue_bridge_ip}/api/{hue_username}"
        
        # Audio configuration
        self.CHUNK = 1024
        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.RATE = 44100
        self.MAX_VOLUME = 10000
        
        # Frequency analysis settings
        self.WINDOW_SIZE = 2048  # FFT window size
        self.frequency_bands = {
            'bass': (20, 250),      # Bass frequencies
            'mid_low': (250, 500),  # Low-mid frequencies  
            'mid': (500, 2000),     # Mid frequencies
            'mid_high': (2000, 4000), # High-mid frequencies
            'treble': (4000, 8000)  # Treble frequencies
        }
        
        # Current frequency band levels
        self.band_levels = {
            'bass': 0,
            'mid_low': 0, 
            'mid': 0,
            'mid_high': 0,
            'treble': 0
        }
        
        # Smoothing for frequency bands
        self.band_smoothing = 0.7  # How much to smooth between updates
        self.previous_bands = self.band_levels.copy()
        
        # Audio buffer for FFT analysis
        self.audio_buffer = np.zeros(self.WINDOW_SIZE)
        
        # Control variables
        self.running = False
        self.current_volume = 0
        self.audio_device = None
        self.stream = None
        self.p = None
        self.audio_thread = None
        self.hue_thread = None
        
    def find_audio_input_device(self):
        """Find the best audio input device"""
        if self.p is None:
            self.p = pyaudio.PyAudio()
        
        # Preferred device names in order of preference
        preferred_devices = ['pulse', 'default', 'USB Audio Device']
        
        best_device = None
        for pref in preferred_devices:
            for i in range(self.p.get_device_count()):
                try:
                    info = self.p.get_device_info_by_index(i)
                    if pref.lower() in info['name'].lower() and info['maxInputChannels'] > 0:
                        best_device = i
                        print(f"Disco Mode: Found audio device: {info['name']} (index {i})")
                        return best_device
                except:
                    continue
        
        # If no preferred device found, use any device with input channels
        if best_device is None:
            for i in range(self.p.get_device_count()):
                try:
                    info = self.p.get_device_info_by_index(i)
                    if info['maxInputChannels'] > 0:
                        best_device = i
                        print(f"Disco Mode: Using fallback audio device: {info['name']} (index {i})")
                        break
                except:
                    continue
        
        return best_device
    
    def calculate_volume(self, data):
        """Calculate RMS volume from audio data"""
        try:
            audio_data = np.frombuffer(data, dtype=np.int16)
            if len(audio_data) == 0:
                return 0
            rms = np.sqrt(np.mean(audio_data.astype(np.float64)**2))
            # Handle NaN values
            if np.isnan(rms) or np.isinf(rms):
                return 0
            return max(0, rms)
        except Exception:
            return 0
    
    def analyze_frequency_bands(self, data):
        """Analyze frequency bands using FFT"""
        try:
            audio_data = np.frombuffer(data, dtype=np.int16)
            if len(audio_data) == 0:
                return
            
            # Update rolling buffer for FFT analysis
            if len(audio_data) < self.WINDOW_SIZE:
                # Shift buffer and add new data
                shift_amount = len(audio_data)
                self.audio_buffer[:-shift_amount] = self.audio_buffer[shift_amount:]
                self.audio_buffer[-shift_amount:] = audio_data.astype(np.float64)
            else:
                # Use last WINDOW_SIZE samples
                self.audio_buffer = audio_data[-self.WINDOW_SIZE:].astype(np.float64)
            
            # Apply window function to reduce spectral leakage
            windowed_data = self.audio_buffer * np.hanning(self.WINDOW_SIZE)
            
            # Compute FFT
            fft_data = np.abs(fft(windowed_data))
            freqs = fftfreq(self.WINDOW_SIZE, 1.0 / self.RATE)
            
            # Only use positive frequencies
            fft_data = fft_data[:self.WINDOW_SIZE // 2]
            freqs = freqs[:self.WINDOW_SIZE // 2]
            
            # Calculate energy in each frequency band
            for band_name, (low_freq, high_freq) in self.frequency_bands.items():
                # Find frequency indices for this band
                band_indices = np.where((freqs >= low_freq) & (freqs <= high_freq))[0]
                
                if len(band_indices) > 0:
                    # Calculate average energy in this band
                    band_energy = np.mean(fft_data[band_indices])
                    
                    # Apply smoothing to reduce rapid changes
                    smoothed_energy = (self.band_smoothing * self.previous_bands[band_name] + 
                                     (1 - self.band_smoothing) * band_energy)
                    
                    self.band_levels[band_name] = smoothed_energy
                    self.previous_bands[band_name] = smoothed_energy
                else:
                    self.band_levels[band_name] = 0
                    
        except Exception as e:
            print(f"FFT Analysis error: {e}")
            # Reset to safe values
            for band in self.band_levels:
                self.band_levels[band] = 0
    
    def hue_request(self, endpoint, method='GET', data=None):
        """Make a request to the Hue Bridge"""
        try:
            url = f"{self.hue_base_url}/{endpoint}"
            if method == 'GET':
                response = requests.get(url, timeout=1)
            elif method == 'PUT':
                response = requests.put(url, json=data, timeout=1)
            elif method == 'POST':
                response = requests.post(url, json=data, timeout=1)
            
            if response.status_code == 200:
                return response.json()
            else:
                return None
        except Exception:
            return None
    
    def get_all_lights(self):
        """Get all available lights"""
        lights = self.hue_request('lights')
        if lights:
            return {light_id: info for light_id, info in lights.items() 
                   if info.get('state', {}).get('reachable', False)}
        return {}
    
    def volume_to_hue_values(self, volume):
        """Convert volume level and frequency bands to Hue brightness and color values"""
        volume_percent = min(volume / self.MAX_VOLUME, 1.0)
        
        # Base brightness from overall volume
        base_brightness = max(10, int(volume_percent * 254))
        
        # Find dominant frequency band
        max_band = max(self.band_levels.keys(), key=lambda k: self.band_levels[k])
        max_band_level = self.band_levels[max_band]
        
        # Normalize band levels for color mixing
        total_energy = sum(self.band_levels.values())
        if total_energy == 0:
            # Fallback to simple volume-based color
            return self.simple_volume_color(volume_percent, base_brightness)
        
        # Color mapping for different frequency bands
        band_colors = {
            'bass': {'hue': 0, 'name': 'Red'},        # Bass = Red (powerful, warm)
            'mid_low': {'hue': 8000, 'name': 'Orange'}, # Low-mid = Orange
            'mid': {'hue': 15000, 'name': 'Yellow'},   # Mid = Yellow (balanced)
            'mid_high': {'hue': 35000, 'name': 'Blue'}, # High-mid = Blue (cool)
            'treble': {'hue': 50000, 'name': 'Purple'}  # Treble = Purple (ethereal)
        }
        
        # Calculate weighted color based on frequency content
        if max_band_level > total_energy * 0.4:  # Dominant band threshold
            # Use dominant band color
            dominant_color = band_colors[max_band]
            hue = dominant_color['hue']
            saturation = min(254, int(200 + (max_band_level / total_energy) * 54))
            
            # Boost brightness for strong bass
            if max_band == 'bass' and self.band_levels['bass'] > total_energy * 0.5:
                brightness = min(254, int(base_brightness * 1.3))
            else:
                brightness = base_brightness
                
        else:
            # Mix colors from multiple bands
            weighted_hue = 0
            total_weight = 0
            
            for band, level in self.band_levels.items():
                if level > 0:
                    weight = level / total_energy
                    weighted_hue += band_colors[band]['hue'] * weight
                    total_weight += weight
            
            if total_weight > 0:
                hue = int(weighted_hue)
                saturation = min(254, int(150 + total_weight * 104))
                brightness = base_brightness
            else:
                return self.simple_volume_color(volume_percent, base_brightness)
        
        return brightness, hue, saturation
    
    def simple_volume_color(self, volume_percent, brightness):
        """Fallback simple volume-based coloring"""
        if volume_percent < 0.3:
            hue, saturation = 25500, 200  # Green
        elif volume_percent < 0.7:
            hue, saturation = 12750, 254  # Yellow-Orange
        else:
            hue, saturation = 0, 254      # Red
        return brightness, hue, saturation
    
    def update_hue_lights(self):
        """Update Hue lights based on current volume"""
        while self.running:
            try:
                if self.current_volume > 50:  # Only update for significant volume
                    brightness, hue, saturation = self.volume_to_hue_values(self.current_volume)
                    
                    # Get all lights
                    lights = self.get_all_lights()
                    
                    # Update each light
                    for light_id in lights.keys():
                        light_data = {
                            "on": True,
                            "bri": brightness,
                            "hue": hue,
                            "sat": saturation,
                            "transitiontime": 1  # Quick transition (0.1 seconds)
                        }
                        self.hue_request(f'lights/{light_id}/state', 'PUT', light_data)
                
                time.sleep(0.15)  # Update every 150ms for better responsiveness
                
            except Exception as e:
                print(f"Disco Mode Hue update error: {e}")
                time.sleep(1)
    
    def audio_processing(self):
        """Process audio input in real-time with frequency analysis"""
        while self.running:
            try:
                # Read audio data
                data = self.stream.read(self.CHUNK, exception_on_overflow=False)
                
                # Calculate volume (RMS)
                volume = self.calculate_volume(data)
                self.current_volume = volume
                
                # Analyze frequency bands using FFT
                self.analyze_frequency_bands(data)
                
                time.sleep(0.05)  # Update every 50ms for better frequency response
                
            except Exception as e:
                print(f"Disco Mode audio processing error: {e}")
                break
    
    def start(self):
        """Start the disco mode"""
        if self.running:
            return {"status": "error", "message": "Disco Mode already running"}
        
        # Find audio device
        self.audio_device = self.find_audio_input_device()
        if self.audio_device is None:
            return {"status": "error", "message": "No audio input device found"}
        
        # Test Hue connection
        lights = self.get_all_lights()
        if not lights:
            return {"status": "error", "message": "Could not connect to Hue Bridge or no lights found"}
        
        try:
            # Initialize audio stream
            if self.p is None:
                self.p = pyaudio.PyAudio()
                
            self.stream = self.p.open(
                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                input_device_index=self.audio_device,
                frames_per_buffer=self.CHUNK
            )
            
            self.running = True
            
            # Start threads
            self.hue_thread = threading.Thread(target=self.update_hue_lights, daemon=True)
            self.audio_thread = threading.Thread(target=self.audio_processing, daemon=True)
            
            self.hue_thread.start()
            self.audio_thread.start()
            
            print(f"Disco Mode started with {len(lights)} lights")
            return {"status": "success", "message": f"Disco Mode started with {len(lights)} lights"}
            
        except Exception as e:
            self.running = False
            return {"status": "error", "message": f"Failed to start Disco Mode: {str(e)}"}
    
    def stop(self):
        """Stop the disco mode"""
        if not self.running:
            return {"status": "error", "message": "Disco Mode not running"}
        
        self.running = False
        
        # Close audio stream
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except:
                pass
        
        if self.p:
            try:
                self.p.terminate()
                self.p = None
            except:
                pass
        
        # Turn off all lights (optional)
        # lights = self.get_all_lights()
        # for light_id in lights.keys():
        #     self.hue_request(f'lights/{light_id}/state', 'PUT', {"on": False})
        
        print("Disco Mode stopped")
        return {"status": "success", "message": "Disco Mode stopped"}
    
    def is_running(self):
        """Check if disco mode is currently running"""
        return self.running
    
    def get_status(self):
        """Get current status of disco mode including frequency analysis"""
        status = {
            "running": self.running,
            "current_volume": self.current_volume,
            "audio_device": self.audio_device,
            "frequency_bands": self.band_levels.copy()
        }
        
        # Add dominant frequency info
        if self.running:
            total_energy = sum(self.band_levels.values())
            if total_energy > 0:
                dominant_band = max(self.band_levels.keys(), key=lambda k: self.band_levels[k])
                dominant_percentage = (self.band_levels[dominant_band] / total_energy) * 100
                status["dominant_frequency"] = {
                    "band": dominant_band,
                    "percentage": round(dominant_percentage, 1)
                }
            else:
                status["dominant_frequency"] = None
        
        return status