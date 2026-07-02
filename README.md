# Hue Controller

> **⚡ Update 2026-06 — Stack & UI**
>
> - **Backend:** Python/**Flask** — jetzt als **systemd-Service** `hue-controller` (war PM2 mit Port-5000-Crash-Loop, behoben). 
> - **UI (2026-06, von Grund auf neu):** **Material Design 3 Expressive** — ruhige **„⚡ Schnellsteuerung"** (ersetzt die alarmierende rote „🚨 Globale Steuerung"): blaues „Alles An" / neutrales „Alles Aus", Disco-Toggle, gefüllter Helligkeits-Slider, runde Farb-Chips. **Live-Farb-Lampenkarten** — echter Lampen-Farbton als Akzent (Dot + Glow + Slider-Track), **MD3-An/Aus-Switch**, Inline-Helligkeit, ausklappbare Farben/Effekte; klare an/aus/nicht-erreichbar-Zustände, responsives Grid. Plus Animationen (Tab-Fade, Status-Dots, Hover-Lift). Service-Worker-Cache `app-v2`.
> - **Deploy:** `git pull && sudo systemctl restart hue-controller`

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/release/python-3110/)
[![Flask](https://img.shields.io/badge/Flask-3.0-000000.svg?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Philips Hue](https://img.shields.io/badge/Philips%20Hue-API%20v1-008000.svg?logo=philips&logoColor=white)](https://developers.meethue.com/)
[![Platform: Raspberry Pi](https://img.shields.io/badge/Platform-Raspberry%20Pi-C51A4A.svg?logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/)
[![systemd](https://img.shields.io/badge/Process%20Manager-systemd-0D597F.svg?logo=linux&logoColor=white)](https://systemd.io/)
[![PWA](https://img.shields.io/badge/PWA-enabled-5A0FC8.svg?logo=googlechrome&logoColor=white)](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps)
[![Tests](https://img.shields.io/badge/Tests-81%20passed-brightgreen.svg?logo=pytest&logoColor=white)](tests/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/pepperonas/hue-controller/pulls)
[![Made with ❤️](https://img.shields.io/badge/Made%20with-%E2%9D%A4%EF%B8%8F-red.svg)](https://celox.io)

A smart Philips Hue lighting controller for Raspberry Pi with web interface, motion detection, disco mode, and custom effect builder.

</div>

## Features

- **Web Dashboard** — Real-time control of all Hue lights with color picker and brightness sliders
- **Motion Detection** — PIR sensor integration for automatic lighting based on room occupancy
- **Disco Mode** — Synchronized light effects with music via audio processing
- **Effect Builder** — Create and save custom lighting effects and sequences
- **GPIO Buttons** — Physical buttons for quick light control (configurable via DB)
- **Smart Error Handling** — Resilient error recovery with system health monitoring
- **Database Logging** — MySQL-backed event logging and analytics

## Wiring Diagram

```
    Raspberry Pi 5                       PIR Sensor (HC-SR501)
    ┌──────────────┐                     ┌────────────────────┐
    │              │                     │                    │
    │  GPIO23(16) ─┼─────────────────────┤── OUT              │
    │              │                     │   Range:  ~7m      │
    │    5V   (4) ─┼─────────────────────┤── VCC    Angle: 120°
    │              │                     │                    │
    │   GND   (6) ─┼──────────┬──────────┤── GND              │
    │              │          │          └────────────────────┘
    │              │          │
    │              │          │           GPIO Buttons (optional)
    │              │          │           ┌────────────────────┐
    │   GPIO n   ──┼──────────┼───────────┤── Button (NO)      │
    │  (DB config) │          └───────────┤── GND              │
    │              │                      └────────────────────┘
    │              │                      (internal pull-up, 200ms debounce)
    └──────────────┘
            │
            │ Network (HTTP)
            ▼
    ┌──────────────────────┐
    │  Philips Hue Bridge  │
    │  192.168.178.29       │
    │  REST API            │
    └──────────────────────┘

    PIR: auto night detection (sunset/sunrise) · 30s cooldown
    Buttons: gpiozero · single + double press support

    ┌──────────┬──────────┬──────────────────────────────────┐
    │ Pi Pin   │ GPIO     │ Connection                       │
    ├──────────┼──────────┼──────────────────────────────────┤
    │ Pin 16   │ GPIO 23  │ PIR sensor OUT                   │
    │ Pin 4    │ 5V       │ PIR sensor VCC                   │
    │ Pin 6    │ GND      │ PIR sensor + button GND          │
    │ varies   │ DB config│ Optional GPIO buttons (NO)       │
    └──────────┴──────────┴──────────────────────────────────┘
```

> **Note:** The PIR sensor triggers garden lights (Hue group 86) automatically at night using sunset/sunrise calculation for Berlin. 3-minute auto-off timer, 30-second cooldown between triggers. GPIO button pins are configured dynamically via MySQL database.

## Quick Start

```bash
# Clone the repository
git clone https://github.com/pepperonas/hue-controller.git
cd hue-controller

# Set up virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure Hue Bridge IP in .env
cp .env.example .env
# Edit .env with your Hue Bridge IP and username

# Start the application
python app_lite.py
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/status` | GET | Current light states |
| `/api/lights` | GET | List all lights |
| `/api/lights/<id>` | PUT | Control individual light |
| `/api/effects` | GET | List saved effects |
| `/api/disco/start` | POST | Start disco mode |
| `/api/disco/stop` | POST | Stop disco mode |
| `/api/pir/status` | GET | PIR sensor status and daylight info |
| `/api/pir/test` | POST | Manually trigger garden lights |
| `/api/pir/settings` | PUT | Enable/disable motion detection |

## Tech Stack

- **Backend** — Python 3.11, Flask, Flask-SocketIO
- **Frontend** — HTML5, CSS3, JavaScript (vanilla)
- **Database** — MySQL
- **Hardware** — Philips Hue Bridge API, PIR sensor (HC-SR501), GPIO buttons (gpiozero)
- **Process Manager** — systemd (`hue-controller.service`)

## Architecture

```
hue-controller/
├── app_lite.py           # Main Flask application
├── audio_processor.py    # Music analysis for disco mode
├── disco_mode.py         # Disco effect engine
├── effect_builder.py     # Custom effect creation
├── error_handler.py      # Smart error recovery
├── gpio_manager.py       # GPIO button management
├── pir_manager.py        # PIR motion sensor handler
├── public/               # Web UI assets
│   ├── index.html        # Main dashboard
│   └── onboarding.html   # Setup wizard
└── ecosystem.config.js   # legacy PM2 config (unused — runs under systemd)
```

## Tests

Pure-logic unit tests run without any hardware (GPIO, audio, MySQL, Flask are all
mocked). 81 tests covering colour/audio maths, power estimation, effect validation,
sunrise/sunset calculation, colour palettes, BPM estimation, and error categorisation.

```bash
# Install dev dependencies
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt

# Run all tests
pytest tests/ -v

# Quick summary only
pytest tests/ -q
```

| Module | Functions covered |
|---|---|
| `audio_processor.py` | `frequency_to_hue`, `amplitude_to_brightness`, `tempo_to_effect_speed`, `TempoEstimator.estimate_bpm` |
| `effect_builder.py` | `EffectBuilder.create_effect`, `add_step`, `remove_step`, `reorder_steps`, `validate_effect`, `generate_preview_colors`, `get_templates`, `create_from_template` |
| `pir_manager.py` | `PIRManager.calculate_sunrise_sunset_berlin` |
| `disco_mode.py` | `DiscoMode.simple_volume_color` |
| `error_handler.py` | `SmartErrorHandler.categorize_error` |
| `app_lite.py` (inline) | Power estimation (`brightness→watts`, `monthly_kwh`, `monthly_cost_eur`), colour palettes |

## Author

**Martin Pfeffer** — [celox.io](https://celox.io)

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
