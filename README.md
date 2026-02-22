# Hue Controller

<div align="center">

![License](https://img.shields.io/badge/License-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.11-3776AB.svg?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0-000000.svg?logo=flask&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi-C51A4A.svg?logo=raspberrypi&logoColor=white)

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
    Raspberry Pi 5
    ┌──────────────┐
    │              │         PIR Motion Sensor (HC-SR501)
    │              │         ┌──────────────────────┐
    │   GPIO 23 ●──┼─────────┤ OUT                  │
    │   (Pin 16)   │         │                      │
    │              │         │  Detection range:     │
    │      5V  ●───┼─────────┤ VCC    ~7m, 120°     │
    │   (Pin 4)    │         │                      │
    │              │         │                      │
    │      GND ●───┼─────────┤ GND                  │
    │   (Pin 6)    │         └──────────────────────┘
    │              │
    │              │         GPIO Buttons (optional, DB-configured)
    │              │         ┌──────────────────────┐
    │  GPIO n  ●───┼─────────┤ Button (NO)          │
    │  (config)    │         │   ┌──┐               │
    │              │         │   │  │──► GND         │
    │              │         └───┴──┴───────────────┘
    │              │         (internal pull-up, 200ms debounce)
    │              │
    └──────────────┘
          │
          │ Network (HTTP)
          ▼
    ┌──────────────────────┐
    │  Philips Hue Bridge  │
    │  192.168.178.x       │
    │                      │
    │  REST API via HTTP    │
    │  /api/<username>/...  │
    └──────────────────────┘

    Pin Mapping:
    ┌──────────┬──────────┬─────────────────────────────────┐
    │ Pi Pin   │ GPIO     │ Connection                      │
    ├──────────┼──────────┼─────────────────────────────────┤
    │ Pin 16   │ GPIO 23  │ PIR sensor OUT                  │
    │ Pin 4    │ 5V       │ PIR sensor VCC                  │
    │ Pin 6    │ GND      │ PIR sensor GND / Button GND     │
    │ varies   │ DB config│ Optional GPIO buttons            │
    └──────────┴──────────┴─────────────────────────────────┘

    PIR: HC-SR501, auto night detection, 30s cooldown
    Buttons: gpiozero, pull-up, single/double press support
```

> **Note:** The PIR sensor triggers garden lights automatically at night (sunset/sunrise detection). GPIO button pins are configured dynamically via MySQL database.

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
echo "HUE_BRIDGE_IP=192.168.x.x" > .env

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

## Tech Stack

- **Backend** — Python 3.11, Flask, Flask-SocketIO
- **Frontend** — HTML5, CSS3, JavaScript (vanilla)
- **Database** — MySQL
- **Hardware** — Philips Hue Bridge API, PIR sensor (HC-SR501), GPIO buttons (gpiozero)
- **Process Manager** — PM2

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
└── ecosystem.config.js   # PM2 configuration
```

## Author

**Martin Pfeffer** — [celox.io](https://celox.io)

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
