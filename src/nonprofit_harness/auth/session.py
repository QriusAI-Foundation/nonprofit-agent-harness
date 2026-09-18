from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import jwt

from nonprofit_harness.core.errors import Unauthorized

ALGORITHM = "HS256"
ISSUER = "nonprofit-agent-harness"


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is making a request. The harness knows nothing else about them."""

    email: str
    org_id: str
    is_admin: bool = False
    name: str = ""

    @property
    def is_anonymous(self) -> bool:
        return not self.email


ANONYMOUS = Principal(email="", org_id="", is_admin=False)


class SessionTokens:
    """Issues and verifies the harness's own session token.

    Google verifies who someone is once, at sign-in. After that the harness carries
    its own short-lived token, so no request path depends on a third-party endpoint
    being reachable.
    """

    def __init__(self, secret: str, *, ttl_seconds: int = 60 * 60 * 12) -> None:
        if not secret:
            raise ValueError("A session secret is required")
        self._secret = secret
        self._ttl = ttl_seconds

    def issue(self, principal: Principal) -> str:
        now = int(time.time())
        payload = {
            "iss": ISSUER,
            "sub": principal.email,
            "org": principal.org_id,
            "adm": principal.is_admin,
            "nm": principal.name,
            "iat": now,
            "exp": now + self._ttl,
        }
        return jwt.encode(payload, self._secret, algorithm=ALGORITHM)

    def verify(self, token: str) -> Principal:
        try:
            payload: dict[str, Any] = jwt.decode(
                token, self._secret, algorithms=[ALGORITHM], issuer=ISSUER
            )
        except jwt.ExpiredSignatureError:
            raise Unauthorized("Session has expired") from None
        except jwt.InvalidTokenError as exc:
            raise Unauthorized(f"Invalid session token: {exc}") from None

        return Principal(
            email=payload.get("sub", ""),
            org_id=payload.get("org", ""),
            is_admin=bool(payload.get("adm", False)),
            name=payload.get("nm", ""),
        )


__all__ = ["ALGORITHM", "ANONYMOUS", "ISSUER", "Principal", "SessionTokens"]
