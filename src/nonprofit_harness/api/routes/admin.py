from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from nonprofit_harness.api.deps import AppContext, get_ctx, require_admin
from nonprofit_harness.auth import Principal

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/config")
def effective_config(
    ctx: AppContext = Depends(get_ctx), _: Principal = Depends(require_admin)
) -> dict[str, Any]:
    """The settings actually in force, and anything about them worth worrying about.

    Secrets are reported as booleans. A config endpoint that echoes a signing key
    is a config endpoint that leaks a signing key.
    """
    config = ctx.config
    return {
        "provider": config.provider,
        "storage": config.storage,
        "model": config.model,
        "budget": {
            "max_cost_usd": config.max_cost_usd,
            "max_tokens": config.max_tokens,
            "max_calls": config.max_calls,
        },
        "redact_inputs": config.redact_inputs,
        "auth_required": config.auth_required,
        "google_client_id_set": bool(config.google_client_id),
        "jwt_secret_set": bool(config.jwt_secret),
        "admin_count": len(config.admin_emails),
        "agents": [a.name for a in ctx.registry.all()],
        "instrument": {"id": ctx.instrument.id, "version": ctx.instrument.version},
        "warnings": config.validate(),
    }


@router.get("/orgs")
def list_orgs(
    ctx: AppContext = Depends(get_ctx), _: Principal = Depends(require_admin)
) -> list[dict[str, Any]]:
    return [
        {"id": o.id, "name": o.name, "created_at": o.created_at} for o in ctx.stores.orgs.list()
    ]


__all__ = ["router"]
