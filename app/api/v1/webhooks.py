"""PyAI transcription webhook. Verify raw bytes, then wake the waiting worker."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AppContainer, get_container, get_sync_session
from app.core.errors import NotFoundError
from app.models.call import Call
from app.providers.pyai import verify_pyai_webhook_signature

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router.post("/pyai/transcription")
async def pyai_transcription_webhook(
    request: Request,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
    x_pyai_signature: str | None = Header(default=None, alias="X-PyAI-Signature"),
) -> dict[str, str]:
    raw = await request.body()
    verify_pyai_webhook_signature(container.settings.webhook_secret_bytes, raw, x_pyai_signature)
    payload = await request.json()
    job_id = str(payload.get("job_id") or payload.get("id") or "")
    public_call_id = str(payload.get("call_id") or payload.get("public_call_id") or "")
    call = None
    if public_call_id:
        call = session.scalar(select(Call).where(Call.public_call_id == public_call_id))
    if call is None and job_id:
        call = session.scalar(select(Call).where(Call.pyai_job_id == job_id))
    if call is None:
        raise NotFoundError("Call not found for webhook")
    if job_id:
        call.pyai_job_id = job_id
    session.commit()
    container.job_ready.signal(job_id or call.pyai_job_id or "")
    return {"status": "accepted"}
