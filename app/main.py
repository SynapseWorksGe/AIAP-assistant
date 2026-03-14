"""
AIAP Zoom Assistant — records Zoom meetings and sends them
for transcription via the AIAP Meeting Protocol service.
"""

import logging
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import zoom

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AIAP Zoom Assistant",
    description="Joins Zoom meetings, records audio, and sends recordings for transcription via AIAP Protocol.",
    version="0.1.0",
)

app.include_router(zoom.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "aiap-zoom-assistant", "version": "0.1.0"}


@app.get("/health/details")
async def health_details():
    """Check connectivity to AIAP transcription service."""
    import httpx

    aiap_ok = False
    aiap_error = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(f"{settings.aiap_base_url}/health")
            aiap_ok = resp.status_code == 200
    except Exception as e:
        aiap_error = str(e)

    return {
        "status": "ok" if aiap_ok else "degraded",
        "aiap_protocol": {"ok": aiap_ok, "url": settings.aiap_base_url, "error": aiap_error},
        "recordings_dir": settings.recordings_dir,
        "recordings_dir_exists": os.path.isdir(settings.recordings_dir),
    }


@app.on_event("startup")
async def startup():
    os.makedirs(settings.recordings_dir, exist_ok=True)
    logger.info("AIAP Zoom Assistant started — %s:%s", settings.app_host, settings.app_port)
    logger.info("AIAP Protocol URL: %s", settings.aiap_base_url)
