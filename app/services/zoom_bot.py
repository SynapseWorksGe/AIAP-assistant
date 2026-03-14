"""
Zoom Bot — joins a Zoom meeting via the web client using Playwright,
captures audio through a PulseAudio virtual sink, and saves the recording.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.models.schemas import SessionInfo, SessionStatus

logger = logging.getLogger(__name__)

# In-memory store for sessions
_sessions: dict[str, dict] = {}


def _get_recordings_dir() -> str:
    os.makedirs(settings.recordings_dir, exist_ok=True)
    return settings.recordings_dir


def get_session(session_id: str) -> Optional[dict]:
    return _sessions.get(session_id)


def get_all_sessions() -> list[dict]:
    return list(_sessions.values())


def session_to_info(s: dict) -> SessionInfo:
    duration = None
    if s.get("started_at") and s.get("stopped_at"):
        duration = (s["stopped_at"] - s["started_at"]).total_seconds()
    elif s.get("started_at") and s["status"] == SessionStatus.RECORDING:
        duration = (datetime.now(timezone.utc) - s["started_at"]).total_seconds()

    return SessionInfo(
        session_id=s["session_id"],
        zoom_url=s["zoom_url"],
        bot_name=s["bot_name"],
        status=s["status"],
        created_at=s["created_at"],
        started_at=s.get("started_at"),
        stopped_at=s.get("stopped_at"),
        duration_sec=duration,
        recording_file=s.get("recording_file"),
        transcription_job_id=s.get("transcription_job_id"),
        transcription_status=s.get("transcription_status"),
        error=s.get("error"),
    )


async def create_session(zoom_url: str, bot_name: Optional[str], language: str, auto_transcribe: bool) -> dict:
    session_id = uuid.uuid4().hex[:12]
    session = {
        "session_id": session_id,
        "zoom_url": zoom_url,
        "bot_name": bot_name or settings.bot_name,
        "language": language,
        "auto_transcribe": auto_transcribe,
        "status": SessionStatus.PENDING,
        "created_at": datetime.now(timezone.utc),
        "started_at": None,
        "stopped_at": None,
        "recording_file": None,
        "transcription_job_id": None,
        "transcription_status": None,
        "error": None,
        # Internal handles
        "_browser": None,
        "_page": None,
        "_ffmpeg_proc": None,
        "_pulse_module_id": None,
        "_task": None,
    }
    _sessions[session_id] = session
    return session


def _parse_zoom_web_url(zoom_url: str) -> str:
    """Convert a Zoom invite link to the web client join URL."""
    # Typical formats:
    #   https://zoom.us/j/12345678?pwd=xxx
    #   https://us05web.zoom.us/j/12345678?pwd=xxx
    # Web client URL:
    #   https://app.zoom.us/wc/join/12345678?pwd=xxx
    import re
    m = re.search(r"/j/(\d+)", zoom_url)
    if not m:
        raise ValueError(f"Cannot parse meeting ID from URL: {zoom_url}")
    meeting_id = m.group(1)

    # Extract password if present
    pwd_match = re.search(r"[?&]pwd=([^&]+)", zoom_url)
    pwd_part = f"?pwd={pwd_match.group(1)}" if pwd_match else ""

    return f"https://app.zoom.us/wc/join/{meeting_id}{pwd_part}"


async def _setup_pulse_sink(session_id: str) -> tuple[str, str]:
    """Create a PulseAudio virtual sink for capturing browser audio."""
    sink_name = f"{settings.pulse_sink_name}_{session_id}"

    # Load a null sink (virtual output)
    proc = await asyncio.create_subprocess_exec(
        "pactl", "load-module", "module-null-sink",
        f"sink_name={sink_name}",
        f"sink_properties=device.description=ZoomCapture_{session_id}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to create PulseAudio sink: {stderr.decode()}")

    module_id = stdout.decode().strip()
    monitor_source = f"{sink_name}.monitor"
    return module_id, monitor_source


async def _remove_pulse_sink(module_id: str) -> None:
    """Remove a PulseAudio virtual sink."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "pactl", "unload-module", module_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
    except Exception as e:
        logger.warning("Failed to remove PulseAudio module %s: %s", module_id, e)


async def _start_ffmpeg_recording(monitor_source: str, output_path: str) -> subprocess.Popen:
    """Start ffmpeg process to record from PulseAudio monitor source."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "pulse",
        "-i", monitor_source,
        "-ac", "1",           # mono
        "-ar", "16000",       # 16kHz — good for speech
        "-c:a", "libopus",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    logger.info("FFmpeg recording started (PID %s) → %s", proc.pid, output_path)
    return proc


async def _move_browser_audio_to_sink(sink_name: str) -> None:
    """Move all current playback streams to the virtual sink."""
    await asyncio.sleep(3)  # wait for audio streams to appear
    proc = await asyncio.create_subprocess_exec(
        "pactl", "list", "short", "sink-inputs",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    for line in stdout.decode().strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 1:
            input_id = parts[0]
            await asyncio.create_subprocess_exec(
                "pactl", "move-sink-input", input_id, sink_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            logger.info("Moved sink-input %s → %s", input_id, sink_name)


async def join_and_record(session_id: str) -> None:
    """Main coroutine: join the Zoom meeting and record audio."""
    session = _sessions[session_id]

    try:
        from playwright.async_api import async_playwright

        session["status"] = SessionStatus.JOINING

        web_url = _parse_zoom_web_url(session["zoom_url"])
        logger.info("Session %s: joining %s", session_id, web_url)

        # Setup PulseAudio virtual sink
        module_id, monitor_source = await _setup_pulse_sink(session_id)
        session["_pulse_module_id"] = module_id
        sink_name = f"{settings.pulse_sink_name}_{session_id}"

        # Prepare recording file
        rec_dir = _get_recordings_dir()
        output_file = os.path.join(rec_dir, f"{session_id}.{settings.audio_format}")
        session["recording_file"] = output_file

        # Launch browser
        pw = await async_playwright().__aenter__()
        browser = await pw.chromium.launch(
            headless=settings.headless,
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-blink-features=AutomationControlled",
                f"--audio-output-device-id={sink_name}",
                "--no-sandbox",
            ],
        )
        session["_browser"] = browser

        context = await browser.new_context(
            permissions=["microphone", "camera"],
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        session["_page"] = page

        # Navigate to Zoom web client
        await page.goto(web_url, wait_until="domcontentloaded", timeout=settings.browser_timeout_ms)
        logger.info("Session %s: page loaded", session_id)

        # Wait for and fill the name field, then join
        # Zoom web client flow: name input → join button → waiting room / meeting
        await asyncio.sleep(3)

        # Try to find and fill name input
        name_input = page.locator('input[id="input-for-name"], input[id="inputname"], input[placeholder*="name" i]')
        try:
            await name_input.first.wait_for(state="visible", timeout=15_000)
            await name_input.first.fill(session["bot_name"])
            logger.info("Session %s: filled bot name", session_id)
        except Exception:
            logger.warning("Session %s: name input not found, may already be set", session_id)

        # Click join button
        join_btn = page.locator(
            'button:has-text("Join"), button:has-text("Войти"), '
            'button:has-text("Присоединиться"), button[id="joinBtn"]'
        )
        try:
            await join_btn.first.wait_for(state="visible", timeout=10_000)
            await join_btn.first.click()
            logger.info("Session %s: clicked join", session_id)
        except Exception:
            logger.warning("Session %s: join button not found", session_id)

        # Accept audio via computer / join audio
        await asyncio.sleep(5)
        audio_btn = page.locator(
            'button:has-text("Join Audio by Computer"), '
            'button:has-text("Подключить звук компьютера"), '
            'button:has-text("Computer Audio"), '
            'button:has-text("Join Audio")'
        )
        try:
            await audio_btn.first.wait_for(state="visible", timeout=15_000)
            await audio_btn.first.click()
            logger.info("Session %s: joined audio", session_id)
        except Exception:
            logger.warning("Session %s: audio join button not found, may be auto-joined", session_id)

        # Start recording
        session["status"] = SessionStatus.RECORDING
        session["started_at"] = datetime.now(timezone.utc)

        # Redirect browser audio to virtual sink
        await _move_browser_audio_to_sink(sink_name)

        # Start ffmpeg capture
        ffmpeg_proc = await _start_ffmpeg_recording(monitor_source, output_file)
        session["_ffmpeg_proc"] = ffmpeg_proc

        logger.info("Session %s: recording started", session_id)

        # Wait until stopped or meeting ends or max duration
        max_dur = settings.max_recording_duration_sec
        check_interval = 10  # seconds

        elapsed = 0
        while elapsed < max_dur:
            if session["status"] in (SessionStatus.STOPPING, SessionStatus.FAILED):
                break

            # Check if meeting ended (page navigated away or closed)
            try:
                # Zoom shows "This meeting has been ended by the host" or similar
                ended_el = page.locator(
                    'text="This meeting has been ended", '
                    'text="Собрание завершено", '
                    'text="Meeting ended", '
                    'text="The host has ended the meeting"'
                )
                if await ended_el.first.is_visible(timeout=1000):
                    logger.info("Session %s: meeting ended by host", session_id)
                    break
            except Exception:
                pass

            await asyncio.sleep(check_interval)
            elapsed += check_interval

        # Stop recording
        await _stop_recording(session)

    except asyncio.CancelledError:
        logger.info("Session %s: cancelled", session_id)
        await _stop_recording(session)
    except Exception as e:
        logger.exception("Session %s: error", session_id)
        session["status"] = SessionStatus.FAILED
        session["error"] = str(e)
        await _cleanup(session)


async def _stop_recording(session: dict) -> None:
    """Stop ffmpeg and close browser."""
    if session["status"] == SessionStatus.COMPLETED:
        return

    session["status"] = SessionStatus.STOPPING
    session["stopped_at"] = datetime.now(timezone.utc)

    # Stop ffmpeg gracefully
    ffmpeg_proc = session.get("_ffmpeg_proc")
    if ffmpeg_proc and ffmpeg_proc.returncode is None:
        try:
            ffmpeg_proc.send_signal(signal.SIGINT)
            await asyncio.wait_for(ffmpeg_proc.wait(), timeout=10)
        except (asyncio.TimeoutError, ProcessLookupError):
            ffmpeg_proc.kill()
        logger.info("Session %s: ffmpeg stopped", session["session_id"])

    await _cleanup(session)

    # Check if recording file exists and is non-empty
    rec_file = session.get("recording_file")
    if rec_file and os.path.exists(rec_file) and os.path.getsize(rec_file) > 0:
        logger.info(
            "Session %s: recording saved (%d bytes)",
            session["session_id"],
            os.path.getsize(rec_file),
        )

        if session.get("auto_transcribe", True):
            session["status"] = SessionStatus.UPLOADING
            # Transcription will be triggered by the caller
        else:
            session["status"] = SessionStatus.COMPLETED
    else:
        session["status"] = SessionStatus.FAILED
        session["error"] = "Recording file is empty or missing"


async def _cleanup(session: dict) -> None:
    """Close browser and remove PulseAudio sink."""
    browser = session.get("_browser")
    if browser:
        try:
            await browser.close()
        except Exception:
            pass
        session["_browser"] = None
        session["_page"] = None

    module_id = session.get("_pulse_module_id")
    if module_id:
        await _remove_pulse_sink(module_id)
        session["_pulse_module_id"] = None


async def stop_session(session_id: str) -> Optional[dict]:
    """Request to stop a recording session."""
    session = _sessions.get(session_id)
    if not session:
        return None

    if session["status"] == SessionStatus.RECORDING:
        session["status"] = SessionStatus.STOPPING
        # The join_and_record loop will detect this and stop

    return session
