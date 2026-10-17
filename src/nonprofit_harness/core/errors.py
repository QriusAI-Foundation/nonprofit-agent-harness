from __future__ import annotations

from nonprofit_harness.core.usage import Usage


class HarnessError(Exception):
    """Base class for every error the harness raises deliberately."""

    status_code = 500
    code = "harness_error"


class NotFound(HarnessError):
    status_code = 404
    code = "not_found"


class InvalidRequest(HarnessError):
    status_code = 400
    code = "invalid_request"


class Unauthorized(HarnessError):
    status_code = 401
    code = "unauthorized"


class Forbidden(HarnessError):
    status_code = 403
    code = "forbidden"


class BudgetExceeded(HarnessError):
    """A run tried to spend past its ceiling.

    Grant funding is fixed, so this stops the run rather than letting cost drift.
    """

    status_code = 402
    code = "budget_exceeded"

    def __init__(
        self, spent: float, ceiling: float, kind: str = "cost", *, message: str | None = None
    ) -> None:
        if kind == "cost":
            detail = f"${spent:.4f} of ${ceiling:.4f}"
        else:
            detail = f"{spent:,.0f} of {ceiling:,.0f}"
        super().__init__(message or f"Run would exceed its {kind} ceiling: {detail}")
        self.spent = spent
        self.ceiling = ceiling
        self.kind = kind


class ReviewRequired(HarnessError):
    """Something tried to release an artifact that no human has approved."""

    status_code = 409
    code = "review_required"


class Conflict(HarnessError):
    """A write lost a race with another write to the same record."""

    status_code = 409
    code = "conflict"


class StaleRun(Conflict):
    """A whole-run save was based on a copy that someone else has since changed.

    Saving it anyway would silently undo their change, which is how two reviewers used
    to erase each other's decisions.
    """

    code = "stale_run"

    def __init__(self, run_id: str, expected: int, found: int) -> None:
        super().__init__(
            f"Run {run_id!r} changed since it was read (read version {expected}, "
            f"stored version {found}). Read it again and retry."
        )
        self.details = {"run_id": run_id, "read_version": expected, "stored_version": found}


class ReviewConflict(Conflict):
    """A decision disagrees with one already recorded for the same artifact.

    The recorded decision stands. The details say who made it, so the second reviewer
    can talk to the first instead of retrying.
    """

    code = "review_conflict"

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(message)
        self.details = details


class AgentFailed(HarnessError):
    status_code = 500
    code = "agent_failed"


class ProviderError(HarnessError):
    status_code = 502
    code = "provider_error"

    def __init__(self, message: str = "", *, usage: Usage | None = None) -> None:
        super().__init__(message)
        #: What the failed call was billed, when the provider's response said. The
        #: budget wrapper banks it before the error travels on, so a refused or broken
        #: response still shows up in the run's spend.
        self.usage = usage


class StorageError(HarnessError):
    """The storage backend refused a request, for a reason the deployer can fix."""

    status_code = 500
    code = "storage_error"


class DataSourceError(HarnessError):
    """An external dataset could not be read: missing key, rate limit, bad response."""

    status_code = 502
    code = "datasource_error"


__all__ = [
    "AgentFailed",
    "BudgetExceeded",
    "Conflict",
    "DataSourceError",
    "Forbidden",
    "HarnessError",
    "InvalidRequest",
    "NotFound",
    "ProviderError",
    "ReviewConflict",
    "ReviewRequired",
    "StaleRun",
    "StorageError",
    "Unauthorized",
]
