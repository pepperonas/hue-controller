#!/usr/bin/env python3
"""
Audio-Verarbeitungsmodul für Musik-Synchronisation
Raspberry Pi Audio-Erfassung und Echtzeit-Analyse
"""

import numpy as np
import threading
import time
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional, Callable

# Audio-Libraries (installiert werden später)
try:
    import pyaudio
    import scipy.signal
    from scipy.fft import fft, fftfreq
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False
    print("⚠️ Audio-Libraries nicht installiert. Führe aus: pip install pyaudio scipy")

@dataclass
class AudioConfig:
    """Audio-Konfiguration"""
    sample_rate: int = 44100
    chunk_size: int = 1024
    channels: int = 1
    format: int = pyaudio.paInt16 if AUDIO_AVAILABLE else None
    device_index: Optional[int] = None
    
@dataclass
class FrequencyBands:
    """Frequenzbänder für Analyse"""
    bass: tuple = (20, 250)      # Bass
    low_mid: tuple = (250, 500)  # Untere Mitten
    mid: tuple = (500, 2000)     # Mitten
    high_mid: tuple = (2000, 4000) # Obere Mitten
    treble: tuple = (4000, 20000)  # Höhen

@dataclass
class AudioFeatures:
    """Extrahierte Audio-Features"""
    timestamp: float
    amplitude: float
    bass_energy: float
    mid_energy: float
    treble_energy: float
    beat_detected: bool
    tempo_bpm: float
    dominant_frequency: float
    spectral_centroid: float
    zero_crossing_rate: float

class BeatDetector:
    """Beat-Detection mit Onset-Erkennung"""
    
    def __init__(self, sample_rate: int = 44100, hop_length: int = 512):
        self.sample_rate = sample_rate
        self.hop_length = hop_length
        self.onset_threshold = 0.3
        self.min_beat_interval = 0.2  # Min 300 BPM
        self.last_beat_time = 0
        self.energy_history = []
        self.max_history_size = 43  # ~1 Sekunde bei hop_length=512
        
    def detect_beat(self, audio_chunk: np.ndarray) -> bool:
        """Erkenne Beat in Audio-Chunk"""
        current_time = time.time()
        
        # Energie berechnen
        energy = np.sum(audio_chunk ** 2)
        self.energy_history.append(energy)
        
        # History begrenzen
        if len(self.energy_history) > self.max_history_size:
            self.energy_history.pop(0)
        
        # Beat-Erkennung: Energie-Anstieg über Durchschnitt
        if len(self.energy_history) >= 10:
            avg_energy = np.mean(self.energy_history[:-3])
            current_energy = np.mean(self.energy_history[-3:])
            
            # Beat erkannt wenn Energie-Anstieg und Mindestabstand
            if (current_energy > avg_energy * (1 + self.onset_threshold) and 
                current_time - self.last_beat_time > self.min_beat_interval):
                self.last_beat_time = current_time
                return True
        
        return False

class TempoEstimator:
    """Tempo-Schätzung (BPM)"""
    
    def __init__(self, window_size: int = 100):
        self.beat_times = []
        self.window_size = window_size
        
    def add_beat(self, timestamp: float):
        """Füge Beat-Zeitstempel hinzu"""
        self.beat_times.append(timestamp)
        if len(self.beat_times) > self.window_size:
            self.beat_times.pop(0)
    
    def estimate_bpm(self) -> float:
        """Schätze BPM aus Beat-Zeitstempeln"""
        if len(self.beat_times) < 4:
            return 0.0
        
        # Intervalle zwischen Beats berechnen
        intervals = np.diff(self.beat_times)
        
        # Median-Intervall für Stabilität
        median_interval = np.median(intervals)
        
        if median_interval > 0:
            bpm = 60.0 / median_interval
            # Realistischen BPM-Bereich begrenzen
            return max(60, min(200, bpm))
        
        return 0.0

class AudioProcessor:
    """Haupt-Audio-Verarbeitungsklasse"""
    
    def __init__(self, config: AudioConfig = None):
        self.config = config or AudioConfig()
        self.is_running = False
        self.audio_stream = None
        self.pyaudio_instance = None
        
        # Analyse-Komponenten
        self.beat_detector = BeatDetector(self.config.sample_rate)
        self.tempo_estimator = TempoEstimator()
        self.freq_bands = FrequencyBands()
        
        # Callbacks für verschiedene Events
        self.beat_callbacks: List[Callable] = []
        self.frequency_callbacks: List[Callable] = []
        self.amplitude_callbacks: List[Callable] = []
        
        # Thread für Audio-Verarbeitung
        self.processing_thread = None
        
        # Logging
        self.logger = logging.getLogger(__name__)
        
    def add_beat_callback(self, callback: Callable[[float], None]):
        """Füge Beat-Callback hinzu"""
        self.beat_callbacks.append(callback)
        
    def add_frequency_callback(self, callback: Callable[[Dict], None]):
        """Füge Frequenz-Callback hinzu"""
        self.frequency_callbacks.append(callback)
        
    def add_amplitude_callback(self, callback: Callable[[float], None]):
        """Füge Amplitude-Callback hinzu"""
        self.amplitude_callbacks.append(callback)
    
    def get_audio_devices(self) -> List[Dict]:
        """Liste verfügbare Audio-Geräte"""
        if not AUDIO_AVAILABLE:
            return []
        
        devices = []
        p = pyaudio.PyAudio()
        
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info['maxInputChannels'] > 0:  # Nur Input-Geräte
                devices.append({
                    'index': i,
                    'name': info['name'],
                    'channels': info['maxInputChannels'],
                    'sample_rate': info['defaultSampleRate']
                })
        
        p.terminate()
        return devices
    
    def start_processing(self) -> bool:
        """Starte Audio-Verarbeitung"""
        if not AUDIO_AVAILABLE:
            self.logger.error("Audio-Libraries nicht verfügbar")
            return False
        
        if self.is_running:
            self.logger.warning("Audio-Verarbeitung läuft bereits")
            return True
        
        try:
            # PyAudio initialisieren
            self.pyaudio_instance = pyaudio.PyAudio()
            
            # Audio-Stream öffnen
            self.audio_stream = self.pyaudio_instance.open(
                format=self.config.format,
                channels=self.config.channels,
                rate=self.config.sample_rate,
                input=True,
                input_device_index=self.config.device_index,
                frames_per_buffer=self.config.chunk_size
            )
            
            self.is_running = True
            
            # Processing-Thread starten
            self.processing_thread = threading.Thread(
                target=self._process_audio_loop, 
                daemon=True
            )
            self.processing_thread.start()
            
            self.logger.info("Audio-Verarbeitung gestartet")
            return True
            
        except Exception as e:
            self.logger.error(f"Fehler beim Starten der Audio-Verarbeitung: {e}")
            return False
    
    def stop_processing(self):
        """Stoppe Audio-Verarbeitung"""
        self.is_running = False
        
        if self.processing_thread:
            self.processing_thread.join(timeout=2.0)
        
        if self.audio_stream:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
            self.audio_stream = None
        
        if self.pyaudio_instance:
            self.pyaudio_instance.terminate()
            self.pyaudio_instance = None
        
        self.logger.info("Audio-Verarbeitung gestoppt")
    
    def _process_audio_loop(self):
        """Haupt-Audio-Verarbeitungsschleife"""
        while self.is_running:
            try:
                # Audio-Daten lesen
                audio_data = self.audio_stream.read(
                    self.config.chunk_size, 
                    exception_on_overflow=False
                )
                
                # Zu NumPy-Array konvertieren
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
                audio_array = audio_array.astype(np.float32) / 32768.0  # Normalisieren
                
                # Audio-Features extrahieren
                features = self._extract_features(audio_array)
                
                # Callbacks ausführen
                self._trigger_callbacks(features)
                
            except Exception as e:
                self.logger.error(f"Fehler in Audio-Verarbeitung: {e}")
                time.sleep(0.1)
    
    def _extract_features(self, audio_chunk: np.ndarray) -> AudioFeatures:
        """Extrahiere Audio-Features aus Chunk"""
        timestamp = time.time()
        
        # Amplitude (RMS)
        amplitude = np.sqrt(np.mean(audio_chunk ** 2))
        
        # FFT für Frequenzanalyse
        fft_data = fft(audio_chunk)
        fft_freqs = fftfreq(len(audio_chunk), 1/self.config.sample_rate)
        magnitude = np.abs(fft_data)
        
        # Frequenzbänder-Energie
        bass_energy = self._get_band_energy(magnitude, fft_freqs, self.freq_bands.bass)
        mid_energy = self._get_band_energy(magnitude, fft_freqs, self.freq_bands.mid)
        treble_energy = self._get_band_energy(magnitude, fft_freqs, self.freq_bands.treble)
        
        # Beat-Erkennung
        beat_detected = self.beat_detector.detect_beat(audio_chunk)
        if beat_detected:
            self.tempo_estimator.add_beat(timestamp)
        
        # Tempo (BPM)
        tempo_bpm = self.tempo_estimator.estimate_bpm()
        
        # Dominante Frequenz
        dominant_freq_idx = np.argmax(magnitude[:len(magnitude)//2])
        dominant_frequency = abs(fft_freqs[dominant_freq_idx])
        
        # Spektraler Schwerpunkt
        spectral_centroid = np.sum(fft_freqs[:len(fft_freqs)//2] * magnitude[:len(magnitude)//2]) / np.sum(magnitude[:len(magnitude)//2])
        
        # Zero Crossing Rate
        zero_crossings = np.where(np.diff(np.sign(audio_chunk)))[0]
        zero_crossing_rate = len(zero_crossings) / len(audio_chunk)
        
        return AudioFeatures(
            timestamp=timestamp,
            amplitude=amplitude,
            bass_energy=bass_energy,
            mid_energy=mid_energy,
            treble_energy=treble_energy,
            beat_detected=beat_detected,
            tempo_bpm=tempo_bpm,
            dominant_frequency=dominant_frequency,
            spectral_centroid=spectral_centroid,
            zero_crossing_rate=zero_crossing_rate
        )
    
    def _get_band_energy(self, magnitude: np.ndarray, freqs: np.ndarray, band: tuple) -> float:
        """Berechne Energie in Frequenzband"""
        band_mask = (freqs >= band[0]) & (freqs <= band[1])
        return np.sum(magnitude[band_mask])
    
    def _trigger_callbacks(self, features: AudioFeatures):
        """Triggere registrierte Callbacks"""
        try:
            # Beat-Callbacks
            if features.beat_detected:
                for callback in self.beat_callbacks:
                    callback(features.tempo_bpm)
            
            # Frequenz-Callbacks
            freq_data = {
                'bass': features.bass_energy,
                'mid': features.mid_energy,
                'treble': features.treble_energy,
                'dominant': features.dominant_frequency,
                'centroid': features.spectral_centroid
            }
            
            for callback in self.frequency_callbacks:
                callback(freq_data)
            
            # Amplitude-Callbacks
            for callback in self.amplitude_callbacks:
                callback(features.amplitude)
                
        except Exception as e:
            self.logger.error(f"Fehler in Callbacks: {e}")

# Utility-Funktionen für Hue-Integration
def frequency_to_hue(frequency: float) -> int:
    """Konvertiere Frequenz zu Hue-Farbwert"""
    # Mapping: Bass=Rot, Mitten=Grün, Höhen=Blau
    if frequency < 250:  # Bass
        return 0  # Rot
    elif frequency < 2000:  # Mitten
        return 25500  # Grün
    else:  # Höhen
        return 46920  # Blau

def amplitude_to_brightness(amplitude: float, min_bri: int = 50, max_bri: int = 254) -> int:
    """Konvertiere Amplitude zu Hue-Helligkeit"""
    # Logarithmische Skalierung für bessere Wahrnehmung
    log_amp = np.log10(max(amplitude, 0.001))
    normalized = max(0, min(1, (log_amp + 3) / 3))  # -3 bis 0 dB
    return int(min_bri + (max_bri - min_bri) * normalized)

def tempo_to_effect_speed(bpm: float) -> float:
    """Konvertiere BPM zu Effekt-Geschwindigkeit"""
    # Normalisiere BPM (60-200) zu Geschwindigkeit (0.5-3.0)
    normalized_bpm = max(60, min(200, bpm))
    return 0.5 + ((normalized_bpm - 60) / 140) * 2.5

# Beispiel-Verwendung und Tests
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Audio-Geräte auflisten
    processor = AudioProcessor()
    devices = processor.get_audio_devices()
    print("📱 Verfügbare Audio-Geräte:")
    for device in devices:
        print(f"  {device['index']}: {device['name']} ({device['channels']} Kanäle)")
    
    # Test-Callbacks
    def on_beat(bpm):
        print(f"🎵 Beat erkannt! BPM: {bpm:.1f}")
    
    def on_frequency(freq_data):
        print(f"🎼 Bass: {freq_data['bass']:.1f}, Mid: {freq_data['mid']:.1f}, Treble: {freq_data['treble']:.1f}")
    
    def on_amplitude(amplitude):
        brightness = amplitude_to_brightness(amplitude)
        print(f"🔊 Amplitude: {amplitude:.3f} -> Helligkeit: {brightness}")
    
    # Callbacks registrieren
    processor.add_beat_callback(on_beat)
    processor.add_frequency_callback(on_frequency)
    processor.add_amplitude_callback(on_amplitude)
    
    print("\n🎤 Starte Audio-Verarbeitung (Ctrl+C zum Beenden)...")
    
    try:
        if processor.start_processing():
            while True:
                time.sleep(1)
        else:
            print("❌ Audio-Verarbeitung konnte nicht gestartet werden")
            
    except KeyboardInterrupt:
        print("\n⏹️ Stoppe Audio-Verarbeitung...")
        processor.stop_processing()
        print("✅ Beendet")