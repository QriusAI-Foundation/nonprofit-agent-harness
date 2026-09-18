from nonprofit_harness.auth.google import GoogleIdentity, verify_google_id_token
from nonprofit_harness.auth.session import ANONYMOUS, Principal, SessionTokens

__all__ = [
    "ANONYMOUS",
    "GoogleIdentity",
    "Principal",
    "SessionTokens",
    "is_admin_email",
    "verify_google_id_token",
]


def is_admin_email(email: str, admin_emails: list[str]) -> bool:
    """Allowlist check. Case-insensitive, exact match only, no domain wildcards."""
    normalised = email.strip().lower()
    return bool(normalised) and normalised in {a.strip().lower() for a in admin_emails}
