from __future__ import annotations

import os
from dataclasses import dataclass, field

#: Spelled out in an environment variable to mean "no ceiling of this kind".
UNLIMITED = {"none", "unlimited", "off"}


def _env_float(key: str, default: float | None = None) -> float | None:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    return None if raw.strip().lower() in UNLIMITED else float(raw)


def _env_int(key: str, default: int | None = None) -> int | None:
    """Read an int ceiling.

    Never `int(raw) or default`: a deliberate 0 is falsy, so that idiom silently
    replaces "allow nothing" with the default and the ceiling stops working.
    """
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    return None if raw.strip().lower() in UNLIMITED else int(raw)


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(key: str) -> list[str]:
    raw = os.getenv(key, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class HarnessConfig:
    """Everything the deployment decides, read once at startup.

    Defaults are chosen so that a fresh clone runs offline, for free, with review
    switched on. Loosening any of that is a deliberate act by the deployer.
    """

    provider: str = "echo"
    storage: str = "memory"
    model: str | None = None

    max_cost_usd: float | None = None
    max_tokens: int | None = 200_000
    max_calls: int | None = 50

    redact_inputs: bool = False

    #: Citation checking costs nothing, so it is on. Cross-checking spends model
    #: calls, so it is off until a deployment asks for it.
    verify_claims: bool = True
    verify_passes: int = 0
    verify_models: list[str] = field(default_factory=list)

    google_client_id: str | None = None
    jwt_secret: str | None = None
    jwt_ttl_seconds: int = 60 * 60 * 12
    admin_emails: list[str] = field(default_factory=list)
    auth_required: bool = False

    cors_origins: list[str] = field(default_factory=list)

    gcp_project: str | None = None
    documents_bucket: str | None = None

    @classmethod
    def from_env(cls) -> HarnessConfig:
        return cls(
            provider=os.getenv("HARNESS_PROVIDER", "echo"),
            storage=os.getenv("HARNESS_STORAGE", "memory"),
            model=os.getenv("HARNESS_MODEL"),
            max_cost_usd=_env_float("HARNESS_MAX_COST_USD"),
            max_tokens=_env_int("HARNESS_MAX_TOKENS", 200_000),
            max_calls=_env_int("HARNESS_MAX_CALLS", 50),
            redact_inputs=_env_bool("HARNESS_REDACT_INPUTS", False),
            verify_claims=_env_bool("HARNESS_VERIFY_CLAIMS", True),
            verify_passes=_env_int("HARNESS_VERIFY_PASSES", 0) or 0,
            verify_models=_env_list("HARNESS_VERIFY_MODELS"),
            google_client_id=os.getenv("HARNESS_GOOGLE_CLIENT_ID"),
            jwt_secret=os.getenv("HARNESS_JWT_SECRET"),
            jwt_ttl_seconds=_env_int("HARNESS_JWT_TTL_SECONDS", 60 * 60 * 12) or 60 * 60 * 12,
            admin_emails=_env_list("HARNESS_ADMIN_EMAILS"),
            auth_required=_env_bool("HARNESS_AUTH_REQUIRED", False),
            cors_origins=_env_list("HARNESS_CORS_ORIGINS"),
            gcp_project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            documents_bucket=os.getenv("HARNESS_DOCUMENTS_BUCKET"),
        )

    def validate(self) -> list[str]:
        """Return the problems that would bite in production, without raising."""
        problems: list[str] = []
        if self.auth_required and not self.google_client_id:
            problems.append("HARNESS_AUTH_REQUIRED is on but HARNESS_GOOGLE_CLIENT_ID is unset")
        if self.auth_required and not self.jwt_secret:
            problems.append("HARNESS_AUTH_REQUIRED is on but HARNESS_JWT_SECRET is unset")
        if self.storage in {"gcp", "firestore", "google"} and not self.documents_bucket:
            problems.append("HARNESS_STORAGE is gcp but HARNESS_DOCUMENTS_BUCKET is unset")
        if self.max_cost_usd is None and self.max_tokens is None and self.max_calls is None:
            problems.append("No budget ceiling is set, so a run can consume without limit")
        if self.verify_passes > 0 and not self.verify_claims:
            problems.append(
                "HARNESS_VERIFY_PASSES is set but HARNESS_VERIFY_CLAIMS is off, "
                "so no verification runs at all"
            )
        if self.verify_passes > 1 and len(self.verify_models) < 2:
            problems.append(
                "Cross-checking runs several passes on one model. Set HARNESS_VERIFY_MODELS "
                "to two or more models, or agreement between passes means little"
            )
        if self.verify_passes > 0 and self.verify_passes % 2 == 0:
            problems.append(
                f"HARNESS_VERIFY_PASSES={self.verify_passes} is even, so a tie is possible "
                "and ties resolve as inconclusive. An odd number is usually wanted"
            )
        return problems


__all__ = ["UNLIMITED", "HarnessConfig"]
