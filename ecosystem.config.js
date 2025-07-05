module.exports = {
  apps: [{
    name: 'hue-controller',
    script: './venv/bin/python3',
    args: 'app_lite.py',
    cwd: '/home/martin/hue-controller',
    env: {
      FLASK_ENV: 'production'
    },
    watch: false,
    restart_delay: 1000,
    max_restarts: 10
  }]
};
