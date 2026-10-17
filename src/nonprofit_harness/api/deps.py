from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from nonprofit_harness.auth import Principal, SessionTokens, is_admin_email
from nonprofit_harness.auth.session import ANONYMOUS
from nonprofit_harness.config import HarnessConfig
from nonprofit_harness.core.errors import Forbidden, NotFound, Unauthorized
from nonprofit_harness.core.registry import AgentRegistry
from nonprofit_harness.core.runner import AgentRunner
from nonprofit_harness.core.types import Run
from nonprofit_harness.readiness.instrument import Instrument
from nonprofit_harness.review.gate import ReviewGate
from nonprofit_harness.storage.base import StoredBlob, Stores

DEFAULT_ORG = "org_default"


@dataclass(slots=True)
class AppContext:
    config: HarnessConfig
    registry: AgentRegistry
    stores: Stores
    runner: AgentRunner
    gate: ReviewGate
    instrument: Instrument
    tokens: SessionTokens | None = None


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def get_principal(request: Request, ctx: AppContext = Depends(get_ctx)) -> Principal:
    """Resolve the caller.

    With auth switched off the harness runs as a single shared workspace, which is
    what makes a local clone usable in one command. Switching it on is a config
    change, not a code change.
    """
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""

    if not token:
        if ctx.config.auth_required:
            raise Unauthorized("This deployment requires a session token")
        return Principal(email="", org_id=DEFAULT_ORG, is_admin=not ctx.config.admin_emails)

    if ctx.tokens is None:
        raise Unauthorized("This deployment has no session secret configured")

    principal = ctx.tokens.verify(token)
    if not principal.email or not principal.org_id:
        # An empty email reads as the anonymous shared workspace, which may reach
        # every org. Only a token we did not issue through sign-in can carry one.
        raise Unauthorized("Session token names no user or organisation")
    if ctx.config.admin_emails:
        principal = Principal(
            email=principal.email,
            org_id=principal.org_id,
            is_admin=is_admin_email(principal.email, ctx.config.admin_emails),
            name=principal.name,
        )
    return principal


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_admin:
        raise Forbidden("This endpoint is restricted to administrators")
    return principal


def can_access(principal: Principal, org_id: str, ctx: AppContext) -> bool:
    """The one membership rule every lookup by id goes through.

    Listings filter by org, but a direct lookup by id does not, so each one has to
    ask. Admins reach every org on purpose: they are the people who support the
    others. The anonymous caller exists only with auth switched off, where the whole
    deployment is one shared workspace.
    """
    if principal.is_anonymous:
        return not ctx.config.auth_required
    return principal.is_admin or principal.org_id == org_id


def authorized_run(
    run_id: str,
    ctx: AppContext = Depends(get_ctx),
    principal: Principal = Depends(get_principal),
) -> Run:
    """Load a run the caller may see, or answer as if it did not exist.

    A refusal that differs from a miss would confirm that another org's run id is
    real, so both are the same 404.
    """
    run = ctx.stores.runs.get(run_id)
    if not can_access(principal, run.org_id, ctx):
        raise NotFound(f"No run {run_id!r}")
    return run


def authorized_blob(blob_id: str, ctx: AppContext, principal: Principal) -> StoredBlob:
    """Blob metadata, checked before a single byte of the file is read."""
    meta = ctx.stores.blobs.meta(blob_id)
    if not can_access(principal, meta.org_id, ctx):
        raise NotFound(f"No blob {blob_id!r}")
    return meta


def org_for_new_run(requested: str | None, principal: Principal, ctx: AppContext) -> str:
    """Where a new run lands. A member can only create work in their own org.

    A request for another org is refused rather than quietly redirected, so a client
    that asked for the wrong org finds out instead of filing work in an unexpected
    place.
    """
    if principal.is_anonymous:
        return requested or principal.org_id
    if requested and not can_access(principal, requested, ctx):
        raise Forbidden("You can only create runs in your own organisation")
    return requested or principal.org_id


def reviewer_name(principal: Principal) -> str:
    return principal.email or "anonymous"


__all__ = [
    "ANONYMOUS",
    "DEFAULT_ORG",
    "AppContext",
    "authorized_blob",
    "authorized_run",
    "can_access",
    "get_ctx",
    "get_principal",
    "org_for_new_run",
    "require_admin",
    "reviewer_name",
]
