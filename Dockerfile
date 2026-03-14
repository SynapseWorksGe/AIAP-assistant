FROM python:3.12-slim

# System dependencies: PulseAudio, FFmpeg, Chromium deps, gosu for privilege drop
RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends \
        ffmpeg \
        pulseaudio \
        pulseaudio-utils \
        xvfb \
        dbus \
        gosu \
        libnss3 \
        libatk-bridge2.0-0 \
        libdrm2 \
        libxkbcommon0 \
        libgbm1 \
        libasound2 \
        libxshmfence1 \
        libx11-xcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libpango-1.0-0 \
        libcairo2 \
        libcups2 \
        libatspi2.0-0 \
        fonts-dejavu-core \
        fonts-liberation \
        && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium
# Install font packages renamed in Debian Trixie before playwright install-deps
RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends \
        fonts-unifont fonts-ubuntu \
    && rm -rf /var/lib/apt/lists/* && \
    playwright install chromium && \
    (playwright install-deps chromium || true)

COPY app/ ./app/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Create appuser and add to pulse-access group
RUN useradd --system --no-create-home appuser && \
    usermod -aG pulse-access appuser && \
    mkdir -p /tmp/zoom-recordings && chown appuser /tmp/zoom-recordings

# PulseAudio config for system mode
RUN mkdir -p /etc/pulse && \
    echo "load-module module-native-protocol-unix auth-anonymous=1" >> /etc/pulse/system.pa && \
    echo "load-module module-null-sink sink_name=default_capture sink_properties=device.description=DefaultCapture" >> /etc/pulse/system.pa

EXPOSE 8001

# Start as root (entrypoint starts PulseAudio/Xvfb, then drops to appuser)
ENTRYPOINT ["./entrypoint.sh"]
