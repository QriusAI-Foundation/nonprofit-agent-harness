from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from nonprofit_harness.auth import Principal, SessionTokens, is_admin_email
from nonprofit_harness.auth.session import ANONYMOUS
from nonprofit_harness.config import HarnessConfig
from nonprofit_harness.core.errors import Forbidden, Unauthorized
from nonprofit_harness.core.registry import AgentRegistry
from nonprofit_harness.core.runner import AgentRunner
from nonprofit_harness.readiness.instrument import Instrument
from nonprofit_harness.review.gate import ReviewGate
from nonprofit_harness.storage.base import Stores

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


def reviewer_name(principal: Principal) -> str:
    return principal.email or "anonymous"


__all__ = [
    "ANONYMOUS",
    "DEFAULT_ORG",
    "AppContext",
    "get_ctx",
    "get_principal",
    "require_admin",
    "reviewer_name",
]
