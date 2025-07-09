# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Philips Hue smart lighting controller web application called "Hue by mrx3k1". It provides a comprehensive web interface for managing Hue lights, groups, scenes, effects, and power consumption monitoring.

## Commands

### Running the Application
```bash
# Activate virtual environment
source venv/bin/activate

# Run the Flask application with database support
python3 app_lite.py

# Run in background
nohup venv/bin/python3 app_lite.py > /dev/null 2>&1 &
```

### Testing Database Connection
```bash
source venv/bin/activate
python3 test_db.py
```

### Database Setup (MariaDB/MySQL)
```bash
# Create database and user
sudo mysql -u root
CREATE DATABASE IF NOT EXISTS hue_monitoring;
CREATE USER IF NOT EXISTS 'hueuser'@'localhost' IDENTIFIED BY 'password';
GRANT ALL PRIVILEGES ON hue_monitoring.* TO 'hueuser'@'localhost';
FLUSH PRIVILEGES;
```

### Production Deployment (PM2)
```bash
# Mit PM2-Management-Script (empfohlen)
./pm2-manage.sh start       # Anwendung starten
./pm2-manage.sh status      # Status prüfen  
./pm2-manage.sh logs        # Logs anzeigen
./pm2-manage.sh restart     # Neustart
./pm2-manage.sh stop        # Stoppen
./pm2-manage.sh health      # Health-Check

# Direkte PM2-Befehle
pm2 start ecosystem.config.js
pm2 logs hue-controller
pm2 stop hue-controller
pm2 restart hue-controller
pm2 monit                   # Monitoring Dashboard
```

### PM2 Auto-Start Setup
```bash
# Einmalig: PM2 beim Systemstart aktivieren
pm2 startup
pm2 save

# Nach Änderungen: Aktuelle Konfiguration speichern
./pm2-manage.sh save
```

### Development Environment
- Python 3.11+ required
- Flask application runs on port 5000 by default
- Virtual environment located in `venv/`
- Configuration via `.env` file

## Architecture

### Application Structure
- **app_lite.py**: Main Flask application with database support and power monitoring
- **public/index.html**: Single-page web interface with embedded JavaScript
- **public/onboarding.html**: Setup wizard for initial configuration
- **.env**: Environment configuration (Hue Bridge IP, API key, Flask settings)
- **ecosystem.config.js**: PM2 process manager configuration
- **.gitignore**: Prevents core files and system files from being tracked

### Technology Stack
- Backend: Flask (Python) with Flask-CORS
- Frontend: Vanilla JavaScript, HTML5, CSS3 with glassmorphism UI, Chart.js for visualizations
- API: Direct integration with Philips Hue Bridge REST API
- Threading: Python threads for effects and timers
- Database: MySQL/MariaDB with connection pooling for power consumption tracking

### Key API Endpoints

#### Light Control
- `GET /api/lights` - List all lights
- `PUT /api/lights/<id>/state` - Control individual light
- `PUT /api/groups/<id>/action` - Control light group

#### Effects & Animations
- `POST /api/effects/strobe` - Strobe effect with configurable speed
- `POST /api/effects/colorloop` - Color cycling effect
- `POST /api/effects/advanced/<type>` - Advanced effects (wave, pulse, rainbow, fire, sunset, lightning)
- `GET /api/effects` - List active effects
- `DELETE /api/effects/<id>/stop` - Stop specific effect

#### Global Operations
- `PUT /api/global/all-lights` - Control all lights simultaneously
- `POST /api/global/emergency-off` - Emergency shutdown
- `PUT /api/global/all-groups` - Control all groups

#### Other Features
- `POST /api/timer` - Create timer for delayed actions
- `GET /api/sensors` - List sensors/switches
- `GET /api/power/current` - Get current power consumption (simulated)

### Important Implementation Details

1. **Effects System**: 
   - Uses Python threading for non-blocking effects
   - Effects tracked in `running_effects` dictionary
   - Supports targeting individual lights, groups, or all lights
   - Effects have configurable duration and speed parameters

2. **Power Monitoring**: 
   - Tracks actual power consumption (9W max per LED bulb)
   - Calculation based on brightness level (0-254 scale)
   - Automatic database logging every 5 minutes
   - Historical data with daily/hourly aggregations
   - Top consumer tracking by kWh

3. **German UI**: 
   The interface is primarily in German. Key terms:
   - Lichter = Lights
   - Gruppen = Groups
   - Szenen = Scenes
   - Leistung = Power
   - Helligkeit = Brightness
   - Farbschleife = Color loop
   - Notaus = Emergency off

4. **Hue Bridge Communication**: 
   - All API calls use `hue_request()` helper function
   - Base URL: `http://{HUE_BRIDGE_IP}/api/{HUE_USERNAME}/`
   - Supports GET, PUT, POST methods
   - 5-second timeout on all requests

5. **Environment Variables**:
   Required in `.env`:
   - `HUE_BRIDGE_IP` - IP address of Hue Bridge
   - `HUE_USERNAME` - Hue API authentication token
   - `FLASK_PORT` - Flask server port (default: 5000)
   - `FLASK_DEBUG` - Debug mode (default: false)
   - `DB_HOST` - Database host (default: localhost)
   - `DB_USER` - Database username (default: hueuser)
   - `DB_PASSWORD` - Database password
   - `DB_NAME` - Database name (default: hue_monitoring)

### Frontend Architecture

1. **Single Page Application**:
   - All UI logic in `public/index.html`
   - `HueControllerPro` class handles all interactions
   - Tab-based navigation without page reloads
   - Onboarding wizard in `public/onboarding.html` for initial setup

2. **Real-time Updates**:
   - Power monitoring: 30-second intervals
   - Effects/timers: 10-second intervals
   - Light states: 15-second intervals (when visible)

3. **UI Features**:
   - Glassmorphism design with blur effects
   - Responsive grid layout (mobile-first)
   - Touch-optimized controls
   - Floating action buttons for emergency controls
   - Color palette for quick selection
   - Live slider value updates

### Advanced Effects Details

1. **Wave Effect** (`wave`): Sequential color transitions across all lights
2. **Pulse Effect** (`pulse`): Synchronized brightness pulsing
3. **Rainbow Effect** (`rainbow`): Smooth hue transitions
4. **Fire Effect** (`fire`): Random warm colors with flickering
5. **Sunset Effect** (`sunset`): Gradual color temperature change
6. **Lightning Effect** (`lightning`): Random white flashes

### Quick Scene Presets

Predefined color/brightness combinations:
- **Entspannung (Relax)**: Warm white, dimmed (hue: 14000, sat: 140, bri: 150)
- **Arbeit (Work)**: Bright white (hue: 0, sat: 0, bri: 254)
- **Party**: Vibrant colors (hue: 25000, sat: 254, bri: 254)
- **Romantik (Romantic)**: Deep red (hue: 65000, sat: 254, bri: 100)
- **Lesen (Reading)**: Neutral white (hue: 0, sat: 0, bri: 200)
- **Gaming**: Blue accent (hue: 46000, sat: 254, bri: 200)

### Threading Architecture

- Effects run in daemon threads to prevent blocking
- Each effect has unique ID: `{type}_{id}_{effect_name}`
- Effects check `running_effects` dictionary to stop gracefully
- Timer actions also use threading with delays

### Database Architecture

1. **Connection Pooling**:
   - MySQL connection pool with 5 connections
   - Automatic session reset on connection reuse
   - Graceful fallback if database unavailable

2. **Background Logging**:
   - Daemon thread for power consumption logging
   - Runs every 5 minutes (300 seconds)
   - Logs individual light consumption and totals

3. **Data Aggregation**:
   - Hourly averages and maximums
   - Daily summaries with kWh calculations
   - Top consumers by total energy usage

### Database Schema

```sql
-- Power consumption logging
CREATE TABLE power_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    light_id VARCHAR(10) NOT NULL,
    light_name VARCHAR(100) NOT NULL,
    watts DECIMAL(5,2) NOT NULL,
    brightness INT NOT NULL,
    INDEX idx_timestamp (timestamp),
    INDEX idx_light_id (light_id)
);

-- Total consumption tracking
CREATE TABLE total_consumption (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    total_watts DECIMAL(7,2) NOT NULL,
    active_lights INT NOT NULL,
    INDEX idx_timestamp (timestamp)
);
```

## Testing

Use `test_db.py` to verify database connectivity and create tables:
```bash
source venv/bin/activate
python3 test_db.py
```

## Dependencies

- Flask
- Flask-CORS
- requests
- mysql-connector-python
- Chart.js (CDN for frontend charts)

## Power Monitoring Details

### Automatic Logging
- Power consumption is logged every 5 minutes to the database
- Each light's current state (on/off, brightness) is recorded
- Total consumption across all lights is aggregated

### API Response Format
- `/api/power/current`: Real-time consumption with database logging status
- `/api/power/history`: Returns:
  - `daily_summary`: Last 7 days aggregated data
  - `today_hourly`: Hourly breakdown for current day
  - `top_consumers`: Lights sorted by total kWh usage

### Frontend Visualization
- Line chart showing hourly consumption (average and maximum)
- Top consumers list with total kWh and average watts
- Auto-refresh every 30 seconds when on power tab
- Chart.js with dark theme styling

## Recent Changes

### 2025-07-09
- Renamed `templates/` folder to `public/` for better naming convention
- Updated Flask application configuration to use `template_folder='public'`
- Updated all static file serving paths to use `public/` instead of `templates/`
- Enhanced `.gitignore` to prevent core dumps and system files from being tracked
- Application remains fully functional with new folder structure

## Security Notes

- Hue API key stored in environment variables
- No authentication on web interface (intended for local network use)
- CORS enabled for all origins (adjust for production)
- Core dumps and sensitive files excluded via `.gitignore`