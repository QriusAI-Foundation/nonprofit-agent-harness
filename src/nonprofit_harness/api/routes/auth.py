from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from nonprofit_harness.api.deps import DEFAULT_ORG, AppContext, get_ctx, get_principal
from nonprofit_harness.api.schemas import GoogleSignIn
from nonprofit_harness.auth import Principal, is_admin_email, verify_google_id_token
from nonprofit_harness.core.errors import Forbidden, InvalidRequest
from nonprofit_harness.storage.base import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google")
def sign_in_with_google(body: GoogleSignIn, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    if not ctx.config.google_client_id:
        raise InvalidRequest("Google sign-in is not configured on this deployment")
    if ctx.tokens is None:
        raise InvalidRequest("No session secret is configured on this deployment")

    identity = verify_google_id_token(body.credential, client_id=ctx.config.google_client_id)
    is_admin = is_admin_email(identity.email, ctx.config.admin_emails)
    user = _member(identity.email, is_admin=is_admin, ctx=ctx)

    # Google proves who someone is, never which org they belong to. A body that
    # names a different org is refused loudly, so a client that relied on choosing
    # finds out, instead of being signed in somewhere it did not expect.
    if body.org_id and body.org_id != user.org_id:
        raise Forbidden("Organisation membership is assigned by an administrator, not at sign-in")

    user.name = identity.name or user.name
    user.is_admin = is_admin
    ctx.stores.users.save(user)

    principal = Principal(
        email=identity.email, org_id=user.org_id, is_admin=is_admin, name=identity.name
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


def _member(email: str, *, is_admin: bool, ctx: AppContext) -> User:
    """The server's own record of which org someone belongs to.

    A first sign-in creates it in the deployment's default org. With no default org
    only enrolled users get in, except admins, who must be able to sign in before
    anyone is enrolled.
    """
    existing = ctx.stores.users.get_by_email(email)
    if existing:
        return existing
    org_id = ctx.config.default_org or (DEFAULT_ORG if is_admin else "")
    if not org_id:
        raise Forbidden("This account is not enrolled in any organisation; ask an administrator")
    # Firestore matches emails in lower case, so a mixed-case record is never found
    # again and every sign-in would create another one in the default org.
    return User(email=email.strip().lower(), org_id=org_id)


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
