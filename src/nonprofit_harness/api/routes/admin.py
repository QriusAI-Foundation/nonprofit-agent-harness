from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from nonprofit_harness.api.deps import AppContext, get_ctx, require_admin
from nonprofit_harness.api.schemas import MembershipIn
from nonprofit_harness.auth import Principal
from nonprofit_harness.core.errors import NotFound
from nonprofit_harness.storage.base import Org, User

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
        "recovery": {
            "interval_seconds": config.reap_interval_seconds,
            "lease_seconds": config.run_lease_seconds,
            "run_timeout_seconds": config.run_timeout_seconds,
            **ctx.runner.recovery.as_dict(),
        },
        "verification": {
            "claims_checked": config.verify_claims,
            "cross_check_passes": config.verify_passes,
            "cross_check_models": config.verify_models,
        },
        "auth_required": config.auth_required,
        "default_org": config.default_org,
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


@router.put("/members/{email}")
def set_membership(
    email: str,
    body: MembershipIn,
    ctx: AppContext = Depends(get_ctx),
    _: Principal = Depends(require_admin),
) -> dict[str, Any]:
    """Put a user in an org. The only way membership changes after a first sign-in.

    A session token carries the org it was issued with, so a move takes effect at
    the user's next sign-in, at the latest when their current token expires.
    """
    _ensure_org(body, ctx)
    normalised = email.strip().lower()
    user = ctx.stores.users.get_by_email(normalised) or User(email=normalised, org_id=body.org_id)
    user.org_id = body.org_id
    ctx.stores.users.save(user)
    return {"email": user.email, "org_id": user.org_id, "name": user.name}


def _ensure_org(body: MembershipIn, ctx: AppContext) -> None:
    try:
        ctx.stores.orgs.get(body.org_id)
    except NotFound:
        ctx.stores.orgs.save(Org(id=body.org_id, name=body.org_name or body.org_id))


__all__ = ["router"]
