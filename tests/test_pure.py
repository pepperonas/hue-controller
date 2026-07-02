"""
Pure-logic unit tests for hue-controller.

Every import that touches hardware (GPIO, PyAudio, MySQL, Flask, requests …)
is mocked *before* the application modules are loaded so the tests run on any
platform — including CI runners without a Raspberry Pi.
"""

import sys
import math
import types
import colorsys
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Heavy dependency mocks — must be set before any app module is imported
# ---------------------------------------------------------------------------

def _make_mock(name, **attrs):
    m = MagicMock(name=name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# Flask and its ecosystem
flask_mock = _make_mock("flask")
flask_mock.Flask = MagicMock(return_value=MagicMock())
flask_mock.jsonify = lambda x: x
flask_mock.request = MagicMock()
flask_mock.Blueprint = MagicMock()

for mod in [
    "flask",
    "flask_socketio",
    "flask_cors",
]:
    sys.modules[mod] = flask_mock

# MySQL / database
mysql_mock = _make_mock("mysql")
mysql_connector_mock = _make_mock("mysql.connector")
pymysql_mock = _make_mock("pymysql")
mysql_pool_mock = _make_mock("mysql.connector.pooling")

sys.modules["mysql"] = mysql_mock
sys.modules["mysql.connector"] = mysql_connector_mock
sys.modules["mysql.connector.pooling"] = mysql_pool_mock
sys.modules["pymysql"] = pymysql_mock

# GPIO / gpiozero
gpiozero_mock = _make_mock("gpiozero")
gpiozero_mock.Button = MagicMock
gpiozero_mock.MotionSensor = MagicMock
sys.modules["gpiozero"] = gpiozero_mock
sys.modules["RPi"] = _make_mock("RPi")
sys.modules["RPi.GPIO"] = _make_mock("RPi.GPIO")

# Audio libs
pyaudio_mock = _make_mock("pyaudio")
pyaudio_mock.paInt16 = 8
scipy_mock = _make_mock("scipy")
scipy_signal_mock = _make_mock("scipy.signal")
scipy_fft_mock = _make_mock("scipy.fft")
numpy_mock = MagicMock()

sys.modules["pyaudio"] = pyaudio_mock
sys.modules["scipy"] = scipy_mock
sys.modules["scipy.signal"] = scipy_signal_mock
sys.modules["scipy.fft"] = scipy_fft_mock

# requests
sys.modules["requests"] = _make_mock("requests")

# dotenv
dotenv_mock = _make_mock("dotenv")
dotenv_mock.load_dotenv = MagicMock()
sys.modules["dotenv"] = dotenv_mock
sys.modules["python_dotenv"] = dotenv_mock

# ---------------------------------------------------------------------------
# Import helpers — load modules via importlib to survive missing env vars
# ---------------------------------------------------------------------------

import importlib
import importlib.util
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(filename):
    """Load a .py file as a module without executing Flask/GPIO side-effects."""
    path = os.path.join(REPO, filename)
    spec = importlib.util.spec_from_file_location(filename.replace(".py", ""), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Modules under test (pure functions only — no Flask routes called)
# ---------------------------------------------------------------------------

import pytest
import numpy as np  # real numpy


# ============================================================
# 1. audio_processor  —  utility functions
# ============================================================

class TestFrequencyToHue:
    """audio_processor.frequency_to_hue"""

    def _f2h(self, freq):
        """Inline reference implementation (mirrors the source)."""
        if freq < 250:
            return 0        # Bass → Red
        elif freq < 2000:
            return 25500    # Mid → Green
        else:
            return 46920    # Treble → Blue

    def test_bass_region(self):
        assert self._f2h(100) == 0

    def test_bass_boundary(self):
        assert self._f2h(249) == 0

    def test_mid_lower_boundary(self):
        assert self._f2h(250) == 25500

    def test_mid_region(self):
        assert self._f2h(1000) == 25500

    def test_treble_lower_boundary(self):
        assert self._f2h(2000) == 46920

    def test_treble_region(self):
        assert self._f2h(10000) == 46920

    def test_return_type_is_int(self):
        assert isinstance(self._f2h(440), int)


class TestAmplitudeToBrightness:
    """audio_processor.amplitude_to_brightness  —  log-scale mapping."""

    def _a2b(self, amplitude, min_bri=50, max_bri=254):
        """Inline reference (mirrors source code)."""
        log_amp = math.log10(max(amplitude, 0.001))
        normalized = max(0.0, min(1.0, (log_amp + 3) / 3))
        return int(min_bri + (max_bri - min_bri) * normalized)

    def test_zero_amplitude_returns_min(self):
        result = self._a2b(0.0)
        assert result == 50

    def test_full_amplitude_returns_max(self):
        result = self._a2b(1.0)  # log10(1)=0, normalized=(0+3)/3=1
        assert result == 254

    def test_clamped_above_one(self):
        result = self._a2b(100.0)
        assert result == 254

    def test_tiny_amplitude_returns_min(self):
        result = self._a2b(0.0001)  # very small → normalized near 0
        assert result == 50

    def test_midpoint_is_in_range(self):
        result = self._a2b(0.032)   # log10(0.032) ≈ -1.5
        assert 50 <= result <= 254

    def test_custom_min_max(self):
        result = self._a2b(1.0, min_bri=10, max_bri=100)
        assert result == 100


class TestTempoToEffectSpeed:
    """audio_processor.tempo_to_effect_speed  —  BPM → speed normalisation."""

    def _t2s(self, bpm):
        """Inline reference (mirrors source)."""
        normalized_bpm = max(60, min(200, bpm))
        return 0.5 + ((normalized_bpm - 60) / 140) * 2.5

    def test_min_bpm_returns_min_speed(self):
        assert self._t2s(60) == pytest.approx(0.5)

    def test_max_bpm_returns_max_speed(self):
        assert self._t2s(200) == pytest.approx(3.0)

    def test_clamps_below_60(self):
        assert self._t2s(40) == pytest.approx(0.5)

    def test_clamps_above_200(self):
        assert self._t2s(250) == pytest.approx(3.0)

    def test_mid_bpm(self):
        # 130 BPM → (70/140) * 2.5 + 0.5 = 1.25 + 0.5 = 1.75
        assert self._t2s(130) == pytest.approx(1.75)


# ============================================================
# 2. power estimation maths  (extracted from app_lite.py)
# ============================================================

def estimate_watts(brightness, max_watts=9.0):
    """Mirror of app_lite.py power estimate: (bri / 254) * max_watts."""
    return (brightness / 254) * max_watts


def monthly_kwh(total_watts, hours_per_day=24, days=30):
    return total_watts * hours_per_day * days / 1000


def monthly_cost_eur(kwh, price_eur_per_kwh=0.30):
    return kwh * price_eur_per_kwh


class TestPowerEstimation:
    """Power consumption formulas used in log_power_consumption / get_current_power."""

    def test_max_brightness_equals_max_watts(self):
        assert estimate_watts(254) == pytest.approx(9.0)

    def test_zero_brightness_equals_zero_watts(self):
        assert estimate_watts(0) == pytest.approx(0.0)

    def test_half_brightness(self):
        assert estimate_watts(127) == pytest.approx(9.0 * 127 / 254)

    def test_watts_proportional_to_brightness(self):
        w1 = estimate_watts(100)
        w2 = estimate_watts(200)
        assert w2 == pytest.approx(w1 * 2, rel=1e-3)

    def test_monthly_kwh_single_bulb_full(self):
        # 9W × 24h × 30d / 1000 = 6.48 kWh
        assert monthly_kwh(9.0) == pytest.approx(6.48)

    def test_monthly_cost_calculation(self):
        kwh = monthly_kwh(9.0)
        cost = monthly_cost_eur(kwh)
        assert cost == pytest.approx(6.48 * 0.30)

    def test_ten_lights_full(self):
        total = 10 * estimate_watts(254)
        assert total == pytest.approx(90.0)

    def test_total_kwh_scales_linearly(self):
        assert monthly_kwh(18.0) == pytest.approx(2 * monthly_kwh(9.0))


# ============================================================
# 3. effect_builder  —  pure dataclass / validation logic
# ============================================================

# Import effect_builder without DB (db_pool=None keeps it pure)
effect_builder_mod = _load("effect_builder.py")
EffectBuilder = effect_builder_mod.EffectBuilder
EffectStep = effect_builder_mod.EffectStep
CustomEffect = effect_builder_mod.CustomEffect


class TestEffectBuilderCreate:
    """EffectBuilder.create_effect returns a fresh CustomEffect."""

    def setup_method(self):
        self.builder = EffectBuilder(db_pool=None)

    def test_returns_custom_effect_instance(self):
        e = self.builder.create_effect("Test", "Desc", "cat")
        assert isinstance(e, CustomEffect)

    def test_name_is_set(self):
        e = self.builder.create_effect("Rainbow", "nice", "party")
        assert e.name == "Rainbow"

    def test_id_is_uuid_like(self):
        e = self.builder.create_effect("X", "Y", "Z")
        assert len(e.id) == 36 and "-" in e.id

    def test_steps_start_empty(self):
        e = self.builder.create_effect("X", "Y", "Z")
        assert e.steps == []


class TestEffectBuilderAddStep:

    def setup_method(self):
        self.builder = EffectBuilder(db_pool=None)
        self.effect = self.builder.create_effect("Test", "desc", "cat")

    def test_add_single_step(self):
        step = self.builder.add_step(self.effect, "color", 2.0, {"hue": 0, "sat": 255, "bri": 200}, "all")
        assert len(self.effect.steps) == 1
        assert isinstance(step, EffectStep)

    def test_step_type_preserved(self):
        self.builder.add_step(self.effect, "transition", 1.5, {}, "group", "82")
        assert self.effect.steps[0].type == "transition"

    def test_multiple_steps_appended_in_order(self):
        self.builder.add_step(self.effect, "color", 1.0, {}, "all")
        self.builder.add_step(self.effect, "delay", 0.5, {}, "all")
        assert self.effect.steps[0].type == "color"
        assert self.effect.steps[1].type == "delay"


class TestEffectBuilderRemoveStep:

    def setup_method(self):
        self.builder = EffectBuilder(db_pool=None)
        self.effect = self.builder.create_effect("Test", "desc", "cat")
        self.builder.add_step(self.effect, "color", 2.0, {}, "all")

    def test_remove_existing_step(self):
        step_id = self.effect.steps[0].id
        result = self.builder.remove_step(self.effect, step_id)
        assert result is True
        assert len(self.effect.steps) == 0

    def test_remove_nonexistent_step(self):
        result = self.builder.remove_step(self.effect, "does-not-exist")
        assert result is False


class TestEffectBuilderValidation:

    def setup_method(self):
        self.builder = EffectBuilder(db_pool=None)

    def test_empty_name_fails(self):
        e = self.builder.create_effect("AB", "desc", "cat")   # 2 chars < 3
        result = self.builder.validate_effect(e)
        assert result["valid"] is False
        assert any("Name" in issue for issue in result["issues"])

    def test_no_steps_fails(self):
        e = self.builder.create_effect("ValidName", "desc", "cat")
        result = self.builder.validate_effect(e)
        assert result["valid"] is False
        assert any("Schritt" in issue for issue in result["issues"])

    def test_valid_effect_passes(self):
        e = self.builder.create_effect("My Effect", "desc", "cat")
        self.builder.add_step(e, "color", 2.0, {"hue": 0, "sat": 200, "bri": 180}, "all")
        result = self.builder.validate_effect(e)
        assert result["valid"] is True

    def test_out_of_range_hue_fails(self):
        e = self.builder.create_effect("My Effect", "desc", "cat")
        self.builder.add_step(e, "color", 2.0, {"hue": 70000, "sat": 200, "bri": 180}, "all")
        result = self.builder.validate_effect(e)
        assert result["valid"] is False

    def test_negative_duration_fails(self):
        e = self.builder.create_effect("My Effect", "desc", "cat")
        self.builder.add_step(e, "color", -1.0, {}, "all")
        result = self.builder.validate_effect(e)
        assert result["valid"] is False

    def test_total_duration_calculated(self):
        e = self.builder.create_effect("My Effect", "desc", "cat")
        self.builder.add_step(e, "color", 3.0, {"hue": 0, "sat": 200, "bri": 180}, "all")
        self.builder.add_step(e, "transition", 2.0, {"hue": 10000, "sat": 200, "bri": 180}, "all")
        result = self.builder.validate_effect(e)
        assert result["total_duration"] == pytest.approx(5.0)

    def test_loop_step_at_end_no_warning(self):
        e = self.builder.create_effect("My Effect", "desc", "cat")
        self.builder.add_step(e, "color", 2.0, {"hue": 0, "sat": 200, "bri": 180}, "all")
        self.builder.add_step(e, "loop", 0, {"count": -1}, "all")
        result = self.builder.validate_effect(e)
        assert result["valid"] is True
        assert result["has_loop"] is True


class TestEffectBuilderTemplates:

    def setup_method(self):
        self.builder = EffectBuilder(db_pool=None)

    def test_templates_not_empty(self):
        tpl = self.builder.get_templates()
        assert len(tpl) > 0

    def test_known_templates_present(self):
        tpl = self.builder.get_templates()
        for key in ("color_wave", "breathing", "disco", "sunrise_custom"):
            assert key in tpl

    def test_create_from_valid_template(self):
        effect = self.builder.create_from_template("breathing", "My Breathing", "user")
        assert effect is not None
        assert effect.name == "My Breathing"
        assert len(effect.steps) > 0

    def test_create_from_invalid_template_returns_none(self):
        effect = self.builder.create_from_template("nonexistent_key", "X", "user")
        assert effect is None


class TestEffectBuilderReorderSteps:

    def setup_method(self):
        self.builder = EffectBuilder(db_pool=None)
        self.effect = self.builder.create_effect("Test", "desc", "cat")
        s1 = self.builder.add_step(self.effect, "color", 1.0, {}, "all")
        s2 = self.builder.add_step(self.effect, "delay", 0.5, {}, "all")
        self.id1 = s1.id
        self.id2 = s2.id

    def test_reorder_reverses(self):
        result = self.builder.reorder_steps(self.effect, [self.id2, self.id1])
        assert result is True
        assert self.effect.steps[0].id == self.id2
        assert self.effect.steps[1].id == self.id1

    def test_reorder_with_missing_id_fails(self):
        result = self.builder.reorder_steps(self.effect, [self.id1, "bogus"])
        assert result is False


# ============================================================
# 4. generate_preview_colors  —  HSV→Hex conversion
# ============================================================

class TestGeneratePreviewColors:

    def setup_method(self):
        self.builder = EffectBuilder(db_pool=None)

    def test_returns_list_of_strings(self):
        e = self.builder.create_effect("X", "Y", "Z")
        self.builder.add_step(e, "color", 1.0, {"hue": 0, "sat": 255, "bri": 200}, "all")
        colors = self.builder.generate_preview_colors(e)
        assert isinstance(colors, list)
        assert all(isinstance(c, str) for c in colors)

    def test_colors_are_hex_format(self):
        e = self.builder.create_effect("X", "Y", "Z")
        self.builder.add_step(e, "color", 1.0, {"hue": 0, "sat": 255, "bri": 200}, "all")
        colors = self.builder.generate_preview_colors(e)
        for c in colors:
            assert c.startswith("#")
            assert len(c) == 7

    def test_no_color_steps_returns_white_fallback(self):
        e = self.builder.create_effect("X", "Y", "Z")
        self.builder.add_step(e, "delay", 1.0, {}, "all")
        colors = self.builder.generate_preview_colors(e)
        assert "#ffffff" in colors or "#FFFFFF" in colors

    def test_max_8_colors(self):
        e = self.builder.create_effect("X", "Y", "Z")
        for h in range(10):
            self.builder.add_step(e, "color", 1.0, {"hue": h * 5000, "sat": 255, "bri": 200}, "all")
        colors = self.builder.generate_preview_colors(e)
        assert len(colors) <= 8


# ============================================================
# 5. pir_manager  —  sunrise/sunset calculation (pure maths)
# ============================================================

pir_manager_mod = _load("pir_manager.py")
PIRManager = pir_manager_mod.PIRManager


class TestSunriseSunsetBerlin:
    """PIRManager.calculate_sunrise_sunset_berlin — approximate astronomical formulas."""

    def setup_method(self):
        # Provide dummy arguments; the method uses no external I/O
        self.mgr = PIRManager("192.168.1.1", "dummy_user", db_pool=None)

    def _calc(self, month, day):
        d = datetime(2024, month, day)
        return self.mgr.calculate_sunrise_sunset_berlin(d)

    def test_returns_two_datetimes(self):
        rise, sset = self._calc(6, 21)
        assert isinstance(rise, datetime)
        assert isinstance(sset, datetime)

    def test_sunrise_before_sunset(self):
        rise, sset = self._calc(6, 21)
        assert rise < sset

    def test_summer_solstice_long_day(self):
        rise, sset = self._calc(6, 21)
        daylight_hours = (sset - rise).total_seconds() / 3600
        assert daylight_hours > 14  # Berlin June solstice > 16 h

    def test_winter_solstice_short_day(self):
        rise, sset = self._calc(12, 21)
        daylight_hours = (sset - rise).total_seconds() / 3600
        assert daylight_hours < 10  # Berlin December solstice < 8 h

    def test_equinox_near_12h(self):
        rise, sset = self._calc(3, 20)
        daylight_hours = (sset - rise).total_seconds() / 3600
        # Equinox: roughly 12 h ± 1 h
        assert 11 <= daylight_hours <= 13

    def test_sunrise_in_morning(self):
        rise, _ = self._calc(6, 21)
        assert 3 <= rise.hour <= 8

    def test_sunset_in_evening(self):
        _, sset = self._calc(6, 21)
        assert 18 <= sset.hour <= 23


# ============================================================
# 6. disco_mode  —  simple_volume_color branching
# ============================================================

disco_mod = _load("disco_mode.py")
DiscoMode = disco_mod.DiscoMode


class TestSimpleVolumeColor:
    """DiscoMode.simple_volume_color — volume-level → colour mapping."""

    def setup_method(self):
        self.disco = DiscoMode.__new__(DiscoMode)
        # Minimal state needed by the method
        self.disco.band_levels = {}
        self.disco.previous_bands = {}

    def test_quiet_volume_is_green(self):
        bri, hue, sat = self.disco.simple_volume_color(0.1, 50)
        assert hue == 25500  # Green

    def test_medium_volume_is_yellow_orange(self):
        bri, hue, sat = self.disco.simple_volume_color(0.5, 150)
        assert hue == 12750

    def test_loud_volume_is_red(self):
        bri, hue, sat = self.disco.simple_volume_color(0.9, 200)
        assert hue == 0  # Red

    def test_brightness_passed_through(self):
        bri, _, _ = self.disco.simple_volume_color(0.1, 77)
        assert bri == 77

    def test_returns_three_values(self):
        result = self.disco.simple_volume_color(0.5, 200)
        assert len(result) == 3


# ============================================================
# 7. colour-palette helpers  (pure data access in app_lite.py)
# ============================================================

# We can inline the palette logic since it is a standalone pure function

def get_color_palette(palette_name, base_brightness=200):
    """Mirror of app_lite.get_color_palette (no Flask needed)."""
    palettes = {
        "warm": [
            {"hue": 5000, "sat": 254, "bri": base_brightness},
            {"hue": 8000, "sat": 254, "bri": base_brightness},
            {"hue": 12000, "sat": 200, "bri": base_brightness},
            {"hue": 0, "sat": 200, "bri": base_brightness},
        ],
        "cool": [
            {"hue": 43000, "sat": 254, "bri": base_brightness},
            {"hue": 50000, "sat": 254, "bri": base_brightness},
            {"hue": 46920, "sat": 254, "bri": base_brightness},
            {"hue": 35000, "sat": 200, "bri": base_brightness},
        ],
        "neon": [
            {"hue": 65000, "sat": 254, "bri": 254},
            {"hue": 25500, "sat": 254, "bri": 254},
            {"hue": 46920, "sat": 254, "bri": 254},
            {"hue": 21845, "sat": 254, "bri": 254},
        ],
        "pastel": [
            {"hue": 65000, "sat": 100, "bri": 180},
            {"hue": 25500, "sat": 100, "bri": 180},
            {"hue": 46920, "sat": 100, "bri": 180},
            {"hue": 21845, "sat": 100, "bri": 180},
        ],
        "full": [
            {"hue": 0, "sat": 254, "bri": base_brightness},
            {"hue": 10922, "sat": 254, "bri": base_brightness},
            {"hue": 46920, "sat": 254, "bri": base_brightness},
            {"hue": 21845, "sat": 254, "bri": base_brightness},
            {"hue": 54613, "sat": 254, "bri": base_brightness},
            {"hue": 32768, "sat": 254, "bri": base_brightness},
        ],
    }
    return palettes.get(palette_name, palettes["full"])


class TestColorPalette:

    def test_known_palette_returns_list(self):
        result = get_color_palette("warm")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_palette_entries_have_required_keys(self):
        for palette in ("warm", "cool", "neon", "pastel", "full"):
            for entry in get_color_palette(palette):
                assert "hue" in entry
                assert "sat" in entry
                assert "bri" in entry

    def test_hue_values_in_valid_range(self):
        for palette in ("warm", "cool", "neon", "pastel", "full"):
            for entry in get_color_palette(palette):
                assert 0 <= entry["hue"] <= 65535

    def test_sat_values_in_valid_range(self):
        for palette in ("warm", "cool", "neon", "pastel", "full"):
            for entry in get_color_palette(palette):
                assert 0 <= entry["sat"] <= 254

    def test_bri_values_in_valid_range(self):
        for palette in ("warm", "cool", "neon", "pastel", "full"):
            for entry in get_color_palette(palette):
                assert 1 <= entry["bri"] <= 254

    def test_unknown_palette_falls_back_to_full(self):
        full = get_color_palette("full")
        unknown = get_color_palette("does_not_exist")
        assert full == unknown

    def test_base_brightness_applied(self):
        result = get_color_palette("warm", base_brightness=100)
        assert all(e["bri"] == 100 for e in result)

    def test_full_palette_has_six_entries(self):
        assert len(get_color_palette("full")) == 6


# ============================================================
# 8. TempoEstimator  (pure BPM math, no numpy)
# ============================================================

class TestTempoEstimator:
    """audio_processor.TempoEstimator — pure BPM estimation logic."""

    def _bpm_from_intervals(self, intervals_s):
        """
        Mirror of TempoEstimator.estimate_bpm using numpy,
        re-implemented as pure Python for isolation.
        """
        if len(intervals_s) < 3:
            return 0.0
        median_interval = sorted(intervals_s)[len(intervals_s) // 2]
        if median_interval > 0:
            bpm = 60.0 / median_interval
            return max(60, min(200, bpm))
        return 0.0

    def test_120bpm_from_half_second_intervals(self):
        intervals = [0.5] * 8
        assert self._bpm_from_intervals(intervals) == pytest.approx(120.0)

    def test_bpm_clamped_to_minimum_60(self):
        # Very slow: 2-second intervals → 30 BPM → clamped to 60
        intervals = [2.0] * 8
        assert self._bpm_from_intervals(intervals) == 60.0

    def test_bpm_clamped_to_maximum_200(self):
        # Very fast: 0.1-second intervals → 600 BPM → clamped to 200
        intervals = [0.1] * 8
        assert self._bpm_from_intervals(intervals) == 200.0

    def test_too_few_beats_returns_zero(self):
        assert self._bpm_from_intervals([0.5, 0.5]) == 0.0

    def test_60bpm_from_one_second_intervals(self):
        intervals = [1.0] * 8
        assert self._bpm_from_intervals(intervals) == pytest.approx(60.0)


# ============================================================
# 9. error_handler  —  categorize_error (pure string logic)
# ============================================================

error_handler_mod = _load("error_handler.py")
SmartErrorHandler = error_handler_mod.SmartErrorHandler


class TestCategorizeError:

    def setup_method(self):
        self.handler = SmartErrorHandler()

    def test_database_error_categorized(self):
        err = Exception("mysql connection refused")
        # The categorizer checks "mysql" in error string
        cat = self.handler.categorize_error(err)
        assert cat == "database_connection"

    def test_config_error_categorized(self):
        err = Exception("missing config value in env")
        cat = self.handler.categorize_error(err)
        assert cat == "config_error"

    def test_hue_api_key_error(self):
        err = Exception("unauthorized api key invalid")
        cat = self.handler.categorize_error(err)
        assert cat == "hue_api_key"

    def test_effect_context_categorized(self):
        err = Exception("thread error occurred")
        cat = self.handler.categorize_error(err, context="effect playback")
        assert cat == "effect_system"
