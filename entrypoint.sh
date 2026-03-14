#!/bin/bash
set -e

# Start PulseAudio in system mode
pulseaudio --system --daemonize --no-cpu-limit --disable-shm 2>/dev/null || true

# Start virtual X server (needed for non-headless Chromium)
Xvfb :99 -screen 0 1280x720x24 -nolisten tcp &
export DISPLAY=:99

# Wait for PulseAudio
sleep 1

exec uvicorn app.main:app --host 0.0.0.0 --port 8001
