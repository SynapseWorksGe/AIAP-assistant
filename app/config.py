from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Bot display name in Zoom
    bot_name: str = "AIAP Recorder"

    # AIAP Protocol transcription service
    aiap_base_url: str = "http://167.86.122.142/aiap"

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8001
    recordings_dir: str = "/tmp/zoom-recordings"

    # Playwright / browser
    headless: bool = True
    browser_timeout_ms: int = 600_000  # 10 min max wait for page loads

    # Recording
    max_recording_duration_sec: int = 14400  # 4 hours max
    audio_format: str = "ogg"  # ogg, wav, mp3

    # PulseAudio virtual sink name (for audio capture)
    pulse_sink_name: str = "zoom_capture"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
