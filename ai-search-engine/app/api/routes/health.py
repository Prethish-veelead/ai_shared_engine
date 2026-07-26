"""Liveness/readiness. /health never touches dependencies; /ready checks them."""
from fastapi import APIRouter

from app.bots.registry import registry

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict:
    return {"status": "ready", "bots": [b.id for b in registry.all()]}
