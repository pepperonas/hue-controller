module.exports = {
  apps: [
    {
      name: 'hue-controller',
      script: 'venv/bin/python3',
      args: 'app_lite.py',
      cwd: '/home/martin/apps/hue-controller',
      interpreter: 'none',
      
      // Process Management
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      restart_delay: 2000,
      min_uptime: '10s',
      max_restarts: 10,
      
      // Environment Variables
      env: {
        NODE_ENV: 'production',
        FLASK_ENV: 'production',
        FLASK_DEBUG: 'false',
        FLASK_PORT: '5000'
      },
      
      // Development Environment
      env_development: {
        NODE_ENV: 'development', 
        FLASK_ENV: 'development',
        FLASK_DEBUG: 'true',
        FLASK_PORT: '5000'
      },
      
      // Logging
      log_file: 'logs/combined.log',
      out_file: 'logs/out.log', 
      error_file: 'logs/error.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      
      // Process Behavior
      kill_timeout: 5000,
      wait_ready: false,
      listen_timeout: 10000,
      
      // Advanced Features
      exec_mode: 'fork',
      pmx: true,
      
      // File watching ignore
      ignore_watch: [
        'node_modules',
        'logs', 
        'venv',
        '*.log',
        '.git',
        '__pycache__'
      ],
      
      // Scheduled restart (daily at 2 AM)
      cron_restart: '0 2 * * *'
    }
  ]
};
