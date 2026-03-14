from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    PENDING = "pending"          # waiting to join
    JOINING = "joining"          # browser opening Zoom
    RECORDING = "recording"      # actively recording
    STOPPING = "stopping"        # stop requested, finishing up
    UPLOADING = "uploading"      # sending to AIAP transcription
    COMPLETED = "completed"      # transcription job submitted
    FAILED = "failed"


class JoinRequest(BaseModel):
    zoom_url: str = Field(..., description="Zoom meeting invite link")
    bot_name: Optional[str] = Field(None, description="Display name for the bot")
    language: Optional[str] = Field("ru-RU", description="Language for transcription")
    auto_transcribe: bool = Field(True, description="Auto-send to AIAP after recording stops")


class SessionInfo(BaseModel):
    session_id: str
    zoom_url: str
    bot_name: str
    status: SessionStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    duration_sec: Optional[float] = None
    recording_file: Optional[str] = None
    transcription_job_id: Optional[str] = None
    transcription_status: Optional[str] = None
    error: Optional[str] = None


class StopRequest(BaseModel):
    auto_transcribe: Optional[bool] = Field(None, description="Override auto_transcribe setting")


class TranscribeRequest(BaseModel):
    language: Optional[str] = Field("ru-RU", description="Language for transcription")
