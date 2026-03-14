"""
API router for Zoom recording sessions.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    JoinRequest,
    SessionInfo,
    SessionStatus,
    StopRequest,
    TranscribeRequest,
)
from app.services import transcription, zoom_bot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/zoom", tags=["Zoom Recording"])


@router.post("/join", response_model=SessionInfo)
async def join_meeting(req: JoinRequest):
    """Start a new Zoom recording session."""
    session = await zoom_bot.create_session(
        zoom_url=req.zoom_url,
        bot_name=req.bot_name,
        language=req.language,
        auto_transcribe=req.auto_transcribe,
    )

    # Launch recording in background
    async def _run():
        await zoom_bot.join_and_record(session["session_id"])
        # Auto-transcribe after recording stops
        s = zoom_bot.get_session(session["session_id"])
        if s and s["status"] == SessionStatus.UPLOADING and s.get("auto_transcribe", True):
            await transcription.send_for_transcription(s, s.get("language", "ru-RU"))

    task = asyncio.create_task(_run())
    session["_task"] = task

    return zoom_bot.session_to_info(session)


@router.post("/stop/{session_id}", response_model=SessionInfo)
async def stop_recording(session_id: str, req: StopRequest | None = None):
    """Stop a recording session."""
    session = await zoom_bot.stop_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if req and req.auto_transcribe is not None:
        session["auto_transcribe"] = req.auto_transcribe

    return zoom_bot.session_to_info(session)


@router.get("/status/{session_id}", response_model=SessionInfo)
async def get_session_status(session_id: str):
    """Get the status of a recording session."""
    session = zoom_bot.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # If there's a transcription job, refresh its status
    job_id = session.get("transcription_job_id")
    if job_id and session.get("transcription_status") not in ("completed", "failed"):
        result = await transcription.check_transcription_status(job_id)
        session["transcription_status"] = result.get("status", session.get("transcription_status"))

    return zoom_bot.session_to_info(session)


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions():
    """List all recording sessions."""
    return [zoom_bot.session_to_info(s) for s in zoom_bot.get_all_sessions()]


@router.post("/transcribe/{session_id}")
async def transcribe_recording(session_id: str, req: TranscribeRequest | None = None):
    """Manually send a recording to the AIAP transcription service."""
    session = zoom_bot.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session["status"] not in (SessionStatus.COMPLETED, SessionStatus.UPLOADING, SessionStatus.STOPPING):
        # Allow re-transcription of completed sessions too
        if session["status"] != SessionStatus.FAILED or not session.get("recording_file"):
            raise HTTPException(
                status_code=400,
                detail=f"Session is in '{session['status']}' state, cannot transcribe",
            )

    language = req.language if req else "ru-RU"
    session["status"] = SessionStatus.UPLOADING
    job_id = await transcription.send_for_transcription(session, language)

    if not job_id:
        raise HTTPException(status_code=500, detail=session.get("error", "Transcription submission failed"))

    return {
        "session_id": session_id,
        "transcription_job_id": job_id,
        "status": "submitted",
    }
