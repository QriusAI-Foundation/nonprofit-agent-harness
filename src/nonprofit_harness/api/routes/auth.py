from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from nonprofit_harness.api.deps import DEFAULT_ORG, AppContext, get_ctx, get_principal
from nonprofit_harness.api.schemas import GoogleSignIn
from nonprofit_harness.auth import Principal, is_admin_email, verify_google_id_token
from nonprofit_harness.core.errors import InvalidRequest
from nonprofit_harness.storage.base import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google")
def sign_in_with_google(body: GoogleSignIn, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    if not ctx.config.google_client_id:
        raise InvalidRequest("Google sign-in is not configured on this deployment")
    if ctx.tokens is None:
        raise InvalidRequest("No session secret is configured on this deployment")

    identity = verify_google_id_token(body.credential, client_id=ctx.config.google_client_id)

    existing = ctx.stores.users.get_by_email(identity.email)
    org_id = body.org_id or (existing.org_id if existing else DEFAULT_ORG)
    is_admin = is_admin_email(identity.email, ctx.config.admin_emails)

    user = existing or User(email=identity.email, org_id=org_id, name=identity.name)
    user.org_id = org_id
    user.name = identity.name or user.name
    user.is_admin = is_admin
    ctx.stores.users.save(user)

    principal = Principal(
        email=identity.email, org_id=org_id, is_admin=is_admin, name=identity.name
    )
    return {
        "token": ctx.tokens.issue(principal),
        "expires_in": ctx.config.jwt_ttl_seconds,
        "user": {
            "email": principal.email,
            "name": principal.name,
            "org_id": principal.org_id,
            "is_admin": principal.is_admin,
        },
    }


@router.get("/me")
def me(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return {
        "email": principal.email,
        "name": principal.name,
        "org_id": principal.org_id,
        "is_admin": principal.is_admin,
        "anonymous": principal.is_anonymous,
    }


__all__ = ["router"]
