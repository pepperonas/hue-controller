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
- **GPIO Control** — Direct hardware integration via Raspberry Pi GPIO pins
- **Smart Error Handling** — Resilient error recovery with system health monitoring
- **Database Logging** — MySQL-backed event logging and analytics

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
- **Hardware** — Philips Hue Bridge API, PIR sensor (GPIO)
- **Process Manager** — PM2

## Architecture

```
hue-controller/
├── app_lite.py           # Main Flask application
├── audio_processor.py    # Music analysis for disco mode
├── disco_mode.py         # Disco effect engine
├── effect_builder.py     # Custom effect creation
├── error_handler.py      # Smart error recovery
├── gpio_manager.py       # GPIO pin management
├── pir_manager.py        # Motion sensor handler
├── public/               # Web UI assets
│   ├── index.html        # Main dashboard
│   └── onboarding.html   # Setup wizard
└── ecosystem.config.js   # PM2 configuration
```

## Author

**Martin Pfeffer** — [celox.io](https://celox.io)

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
