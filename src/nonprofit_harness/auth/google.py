from __future__ import annotations

from dataclasses import dataclass

from nonprofit_harness.core.errors import Unauthorized

_GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    email: str
    email_verified: bool
    name: str = ""
    subject: str = ""
    picture: str = ""


def verify_google_id_token(token: str, *, client_id: str) -> GoogleIdentity:
    """Check a Google Sign-In credential and return who it belongs to.

    Needs the `gcp` extra for `google-auth`, which does the certificate fetching and
    signature checking. Verification is never done by decoding the token unchecked.
    """
    if not token:
        raise Unauthorized("Missing Google credential")
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise Unauthorized(
            "Google sign-in needs the `gcp` extra: pip install 'nonprofit-agent-harness[gcp]'"
        ) from exc

    try:
        claims = google_id_token.verify_oauth2_token(
            token, google_requests.Request(), client_id
        )
    except ValueError as exc:
        raise Unauthorized(f"Google credential rejected: {exc}") from None

    if claims.get("iss") not in _GOOGLE_ISSUERS:
        raise Unauthorized("Google credential has an unexpected issuer")

    email = claims.get("email", "")
    if not email:
        raise Unauthorized("Google credential carries no email")
    if not claims.get("email_verified", False):
        raise Unauthorized("Google account email is not verified")

    return GoogleIdentity(
        email=email,
        email_verified=True,
        name=claims.get("name", ""),
        subject=claims.get("sub", ""),
        picture=claims.get("picture", ""),
    )


__all__ = ["GoogleIdentity", "verify_google_id_token"]
