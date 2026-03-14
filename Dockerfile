FROM python:3.12-slim

# System dependencies: PulseAudio, FFmpeg, Chromium deps
RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends \
        ffmpeg \
        pulseaudio \
        pulseaudio-utils \
        xvfb \
        dbus \
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
RUN playwright install chromium && \
    playwright install-deps chromium

COPY app/ ./app/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

RUN useradd --system --no-create-home appuser && \
    mkdir -p /tmp/zoom-recordings && chown appuser /tmp/zoom-recordings

EXPOSE 8001

ENTRYPOINT ["./entrypoint.sh"]
