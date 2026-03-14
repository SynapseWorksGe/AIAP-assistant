#!/bin/bash
set -e

echo "[entrypoint] Starting PulseAudio (system mode)..."
pulseaudio --system --daemonize --no-cpu-limit --disable-shm 2>/dev/null || true

echo "[entrypoint] Starting Xvfb..."
Xvfb :99 -screen 0 1280x720x24 -nolisten tcp &
export DISPLAY=:99

# Wait for services
sleep 1

echo "[entrypoint] Starting AIAP Zoom Assistant as appuser..."
exec gosu appuser uvicorn app.main:app --host 0.0.0.0 --port 8001
