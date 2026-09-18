from __future__ import annotations


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

    def __init__(self, spent: float, ceiling: float, kind: str = "cost") -> None:
        if kind == "cost":
            detail = f"${spent:.4f} of ${ceiling:.4f}"
        else:
            detail = f"{spent:,.0f} of {ceiling:,.0f}"
        super().__init__(f"Run would exceed its {kind} ceiling: {detail}")
        self.spent = spent
        self.ceiling = ceiling
        self.kind = kind


class ReviewRequired(HarnessError):
    """Something tried to release an artifact that no human has approved."""

    status_code = 409
    code = "review_required"


class AgentFailed(HarnessError):
    status_code = 500
    code = "agent_failed"


class ProviderError(HarnessError):
    status_code = 502
    code = "provider_error"


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
    "DataSourceError",
    "Forbidden",
    "HarnessError",
    "InvalidRequest",
    "NotFound",
    "ProviderError",
    "ReviewRequired",
    "StorageError",
    "Unauthorized",
]
