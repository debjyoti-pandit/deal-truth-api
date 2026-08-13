"""Public architecture and design docs (allowlisted files under docs/)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/api/v1", tags=["reference"])

_DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"

_ALLOWED: dict[str, str] = {
    "ARCHITECTURE.md": "System architecture",
    "README.md": "Design doc index",
    "evidence.md": "Evidence model",
    "providers.md": "Provider interfaces",
    "deterministic-analysis.md": "Deterministic analysis",
    "named-errors.md": "Named errors",
    "frontend-contract.md": "Frontend contract (gap resolutions)",
    "search.md": "Transcript and insight full-text search",
}


def _safe_doc(name: str) -> Path:
    if name not in _ALLOWED:
        raise HTTPException(status_code=404, detail="Unknown reference document")
    path = (_DOCS_DIR / name).resolve()
    if path.parent != _DOCS_DIR.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="Reference document not found")
    return path


@router.get("/reference")
async def list_reference_docs() -> dict[str, object]:
    items = [
        {
            "name": name,
            "title": title,
            "path": f"/api/v1/reference/{name}",
        }
        for name, title in _ALLOWED.items()
        if (_DOCS_DIR / name).is_file()
    ]
    return {"docs": items}


@router.get("/reference/{name}")
async def get_reference_doc(name: str) -> PlainTextResponse:
    path = _safe_doc(name)
    return PlainTextResponse(
        path.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
    )
