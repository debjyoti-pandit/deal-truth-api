"""Hashed share tokens and read-only shared reports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AppContainer, get_container, get_sync_session, require_auth
from app.api.v1.calls import get_transcript
from app.api.v1.report import get_report, require_report_ready
from app.core.errors import NotFoundError, ShareTokenInvalid
from app.core.security import generate_share_token, hash_token
from app.models.call import Call
from app.models.sharing import ShareLink
from app.schemas import ShareCreate, ShareOut

router = APIRouter(prefix="/api/v1", tags=["sharing"])


@router.post("/calls/{call_id}/share", dependencies=[Depends(require_auth)])
def create_share(
    call_id: UUID,
    body: ShareCreate | None = None,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> ShareOut:
    call = session.get(Call, call_id)
    if call is None:
        raise NotFoundError("Call not found")
    ttl = (body.ttl_seconds if body and body.ttl_seconds else None) or container.settings.share_token_ttl_seconds
    token = generate_share_token()
    link = ShareLink(
        call_id=call.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
    )
    session.add(link)
    session.flush()
    # GAP-BE-006: the share URL is a web-app link, not an API link.
    web_base = container.settings.public_web_base_url.strip().rstrip("/")
    url = f"{web_base}/shared/{token}" if web_base else f"/shared/{token}"
    return ShareOut(id=link.id, token=token, expires_at=link.expires_at, url=url)


@router.delete(
    "/calls/{call_id}/share/{share_id}",
    status_code=204,
    dependencies=[Depends(require_auth)],
)
def revoke_share(call_id: UUID, share_id: UUID, session: Session = Depends(get_sync_session)) -> None:
    link = session.get(ShareLink, share_id)
    if link is None or link.call_id != call_id:
        raise NotFoundError("Share link not found")
    link.revoked_at = datetime.now(UTC)


@router.get("/shared/{token}")
def get_shared(
    token: str,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> dict[str, object]:
    digest = hash_token(token)
    link = session.scalar(select(ShareLink).where(ShareLink.token_hash == digest))
    if link is None or link.revoked_at is not None:
        raise ShareTokenInvalid("Share link is invalid")
    expires = link.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        raise ShareTokenInvalid("Share link has expired")
    call = session.get(Call, link.call_id)
    if call is None:
        raise ShareTokenInvalid("Share link is invalid")
    # GAP-BE-002: a share on an unfinished call is a named 409, never a 500.
    require_report_ready(call)
    report = get_report(link.call_id, session, container)
    transcript = get_transcript(link.call_id, session)
    return {"report": report, "transcript": transcript.model_dump(mode="json")}
