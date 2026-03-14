"""
Integration with the AIAP Meeting Protocol transcription service.
Sends recorded audio files for transcription and polls for results.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from app.config import settings
from app.models.schemas import SessionStatus

logger = logging.getLogger(__name__)

TRANSCRIBE_URL = f"{settings.aiap_base_url}/api/v1/meetings/transcribe"
STATUS_URL = f"{settings.aiap_base_url}/api/v1/meetings/status"


async def send_for_transcription(session: dict, language: str = "ru-RU") -> Optional[str]:
    """
    Send recording file to AIAP transcription service.
    Returns the transcription job_id or None on failure.
    """
    rec_file = session.get("recording_file")
    if not rec_file or not os.path.exists(rec_file):
        logger.error("Session %s: recording file not found: %s", session["session_id"], rec_file)
        session["status"] = SessionStatus.FAILED
        session["error"] = "Recording file not found"
        return None

    file_size = os.path.getsize(rec_file)
    logger.info(
        "Session %s: sending %s (%d bytes) to AIAP for transcription",
        session["session_id"],
        rec_file,
        file_size,
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            filename = os.path.basename(rec_file)
            with open(rec_file, "rb") as f:
                files = {"file": (filename, f, "audio/ogg")}
                data = {"language": language}
                response = await client.post(TRANSCRIBE_URL, files=files, data=data)

            response.raise_for_status()
            result = response.json()
            job_id = result.get("job_id")

            if job_id:
                session["transcription_job_id"] = job_id
                session["transcription_status"] = "submitted"
                session["status"] = SessionStatus.COMPLETED
                logger.info(
                    "Session %s: transcription job submitted → %s",
                    session["session_id"],
                    job_id,
                )
                return job_id
            else:
                session["status"] = SessionStatus.FAILED
                session["error"] = f"AIAP returned no job_id: {result}"
                return None

    except httpx.HTTPStatusError as e:
        logger.error(
            "Session %s: AIAP HTTP error %s: %s",
            session["session_id"],
            e.response.status_code,
            e.response.text,
        )
        session["status"] = SessionStatus.FAILED
        session["error"] = f"AIAP HTTP {e.response.status_code}: {e.response.text[:200]}"
        return None
    except Exception as e:
        logger.exception("Session %s: failed to send to AIAP", session["session_id"])
        session["status"] = SessionStatus.FAILED
        session["error"] = str(e)
        return None


async def check_transcription_status(job_id: str) -> dict:
    """Check transcription job status from AIAP service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.get(f"{STATUS_URL}/{job_id}")
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error("Failed to check transcription status for %s: %s", job_id, e)
        return {"error": str(e)}
