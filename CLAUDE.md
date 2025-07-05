# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Philips Hue smart lighting controller web application called "Hue Controller Pro". It provides a comprehensive web interface for managing Hue lights, groups, scenes, effects, and power consumption monitoring.

## Commands

### Running the Application
```bash
# Activate virtual environment
source venv/bin/activate

# Run the Flask application
python3 app_lite.py
```

### Testing Database Connection
```bash
python3 test_db.py
```

### Development Environment
- Python 3.11+ required
- Flask application runs on port 5000 by default
- Virtual environment located in `venv/`

## Architecture

### Application Structure
- **app_lite.py**: Main Flask application (database-free version)
- **templates/index.html**: Single-page web interface with embedded JavaScript
- **.env**: Environment configuration (Hue Bridge IP, API key, Flask settings)

### Technology Stack
- Backend: Flask (Python) with Flask-CORS
- Frontend: Vanilla JavaScript, HTML5, CSS3
- API: Direct integration with Philips Hue Bridge REST API
- Threading: Python threads for effects and timers

### Key API Endpoints
- `/api/lights/*` - Individual light control
- `/api/groups/*` - Group management
- `/api/scenes/*` - Scene activation
- `/api/effects/*` - Special effects (strobe, colorloop)
- `/api/timer` - Timer functionality
- `/api/global/*` - Global operations (all on/off, emergency off)
- `/api/power/*` - Power consumption monitoring

### Important Implementation Details

1. **Effects System**: Uses Python threading to implement non-blocking effects like strobe and color loop. Effects can be cancelled via `/api/effects/cancel/<id>`.

2. **Power Monitoring**: Simulates power consumption based on light state and brightness. Real consumption values would require database integration.

3. **German UI**: The interface is primarily in German. Key terms:
   - Lichter = Lights
   - Gruppen = Groups
   - Szenen = Scenes
   - Leistung = Power

4. **Hue Bridge Communication**: All Hue API calls go through `make_hue_request()` function which handles the base URL and authentication.

5. **No Database Mode**: Currently runs in "lite mode" without database persistence. Database code is commented out but available for future use.

6. **Environment Variables**: Critical configuration in .env:
   - HUE_BRIDGE_IP
   - HUE_USERNAME (Hue API key)
   - FLASK_PORT
   - Database credentials (unused in lite mode)

### Frontend Architecture
- Single-page application in index.html
- Modular JavaScript with separate functions for each feature
- Auto-refresh for power monitoring (30-second intervals)
- Dynamic UI updates without page reload
- Responsive design with CSS Grid