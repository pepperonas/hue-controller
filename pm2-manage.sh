#!/bin/bash
# PM2 Management Script for Hue by mrx3k1

cd /home/martin/apps/hue-controller

case "$1" in
    start)
        echo "🚀 Starting Hue Controller with PM2..."
        pm2 start ecosystem.config.js
        pm2 save
        ;;
    stop)
        echo "🛑 Stopping Hue Controller..."
        pm2 stop hue-controller
        ;;
    restart)
        echo "🔄 Restarting Hue Controller..."
        pm2 restart hue-controller
        ;;
    reload)
        echo "♻️ Reloading Hue Controller (zero-downtime)..."
        pm2 reload hue-controller
        ;;
    delete)
        echo "🗑️ Deleting Hue Controller from PM2..."
        pm2 delete hue-controller
        ;;
    status)
        echo "📊 Hue Controller Status:"
        pm2 status hue-controller
        ;;
    logs)
        echo "📋 Showing logs..."
        pm2 logs hue-controller --lines 50
        ;;
    monit)
        echo "📈 Opening PM2 monitor..."
        pm2 monit
        ;;
    startup)
        echo "⚙️ Setting up PM2 to start on boot..."
        pm2 startup
        echo "After running the command above, execute: pm2 save"
        ;;
    save)
        echo "💾 Saving current PM2 processes..."
        pm2 save
        ;;
    dev)
        echo "🛠️ Starting in development mode..."
        pm2 start ecosystem.config.js --env development
        pm2 save
        ;;
    prod)
        echo "🏭 Starting in production mode..."
        pm2 start ecosystem.config.js --env production
        pm2 save
        ;;
    update)
        echo "⬆️ Updating application and restarting..."
        git pull
        source venv/bin/activate
        pip install -r requirements.txt || echo "No requirements.txt found"
        pm2 restart hue-controller
        ;;
    backup-logs)
        echo "💾 Backing up logs..."
        timestamp=$(date +%Y%m%d_%H%M%S)
        mkdir -p logs/backup
        cp logs/*.log logs/backup/backup_$timestamp/ 2>/dev/null || echo "No logs to backup"
        echo "Logs backed up to logs/backup/backup_$timestamp/"
        ;;
    clean-logs)
        echo "🧹 Cleaning old logs..."
        pm2 flush hue-controller
        > logs/combined.log
        > logs/out.log
        > logs/error.log
        echo "Logs cleaned!"
        ;;
    health)
        echo "🏥 Health Check:"
        echo "PM2 Status:"
        pm2 show hue-controller --silent 2>/dev/null | grep -E "(status|cpu|memory|restarts)" || echo "Process information unavailable"
        echo ""
        echo "Application Health:"
        curl -s http://localhost:5000/api/lights > /dev/null && echo "✅ API responding" || echo "❌ API not responding"
        echo ""
        echo "Port Check:"
        netstat -ln | grep ":5000" > /dev/null && echo "✅ Port 5000 is listening" || echo "❌ Port 5000 not listening"
        ;;
    *)
        echo "🎮 Hue by mrx3k1 - PM2 Management"
        echo ""
        echo "Usage: $0 {command}"
        echo ""
        echo "Process Management:"
        echo "  start      - Start the application"
        echo "  stop       - Stop the application"
        echo "  restart    - Restart the application"
        echo "  reload     - Zero-downtime reload"
        echo "  delete     - Remove from PM2"
        echo "  status     - Show process status"
        echo ""
        echo "Development:"
        echo "  dev        - Start in development mode"
        echo "  prod       - Start in production mode"
        echo "  update     - Pull updates and restart"
        echo ""
        echo "Monitoring:"
        echo "  logs       - Show recent logs"
        echo "  monit      - Open PM2 monitor"
        echo "  health     - Check application health"
        echo ""
        echo "System:"
        echo "  startup    - Setup auto-start on boot"
        echo "  save       - Save current PM2 config"
        echo ""
        echo "Maintenance:"
        echo "  backup-logs - Backup current logs"
        echo "  clean-logs  - Clear all logs"
        echo ""
        echo "Examples:"
        echo "  $0 start     # Start the application"
        echo "  $0 logs      # View logs"
        echo "  $0 health    # Check if everything is working"
        ;;
esac