"""API routers."""

from fastapi import APIRouter

from app.api.v1 import audio, calls, deals, health, integrations, reference, report, share, webhooks

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(reference.router)
api_router.include_router(calls.router)
api_router.include_router(deals.router)
api_router.include_router(audio.router)
api_router.include_router(report.router)
api_router.include_router(integrations.router)
api_router.include_router(share.router)
api_router.include_router(webhooks.router)
