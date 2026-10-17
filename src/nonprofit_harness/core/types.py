from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from nonprofit_harness.core.usage import Usage
from nonprofit_harness.verification.types import Claim, VerificationReport


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"


class ArtifactStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class Document:
    """One unit of input text. The harness never passes raw bytes to an agent."""

    text: str
    name: str = "untitled"
    media_type: str = "text/plain"
    id: str = field(default_factory=lambda: _new_id("doc"))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Review:
    decision: ReviewDecision
    reviewer: str
    note: str = ""
    at: datetime = field(default_factory=_now)

    @property
    def is_attributed(self) -> bool:
        return bool(self.reviewer.strip()) and self.at is not None


# The record a decided status must carry. A status alone is a field that anything
# holding the object can set; the record is what says who decided and when.
_DECISION_FOR_STATUS = {
    ArtifactStatus.APPROVED: ReviewDecision.APPROVE,
    ArtifactStatus.REJECTED: ReviewDecision.REJECT,
}


@dataclass(slots=True)
class Artifact:
    """Something an agent produced. Nothing leaves the harness until a human approves it."""

    kind: str
    content: str
    title: str = ""
    id: str = field(default_factory=lambda: _new_id("art"))
    status: ArtifactStatus = ArtifactStatus.DRAFT
    review: Review | None = None
    claims: list[Claim] = field(default_factory=list)
    verification: VerificationReport | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_released(self) -> bool:
        return self.status == ArtifactStatus.APPROVED and self.decision_is_coherent

    @property
    def decision_is_coherent(self) -> bool:
        """Whether the status and the review record tell the same story."""
        expected = _DECISION_FOR_STATUS.get(self.status)
        if expected is None:
            return self.review is None
        return (
            self.review is not None
            and self.review.decision == expected
            and self.review.is_attributed
        )

    @property
    def failed_verification(self) -> bool:
        return self.verification is not None and not self.verification.ok


@dataclass(slots=True)
class AgentResult:
    artifacts: list[Artifact] = field(default_factory=list)
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Run:
    agent: str
    org_id: str
    id: str = field(default_factory=lambda: _new_id("run"))
    status: RunStatus = RunStatus.QUEUED
    inputs: list[Document] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    summary: str = ""
    error: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Bumped by the store on every write. A save from a copy read at an older version
    # is refused, so one writer cannot silently undo another's change.
    version: int = 0

    def touch(self) -> None:
        self.updated_at = _now()

    def artifact(self, artifact_id: str) -> Artifact | None:
        return next((a for a in self.artifacts if a.id == artifact_id), None)

    @property
    def pending_review(self) -> list[Artifact]:
        return [a for a in self.artifacts if a.status == ArtifactStatus.PENDING_REVIEW]

    @property
    def released(self) -> list[Artifact]:
        return [a for a in self.artifacts if a.is_released]

    @property
    def incoherent(self) -> list[Artifact]:
        return [a for a in self.artifacts if not a.decision_is_coherent]

    @property
    def unverified(self) -> list[Artifact]:
        return [a for a in self.artifacts if a.failed_verification]


__all__ = [
    "AgentResult",
    "Artifact",
    "ArtifactStatus",
    "Document",
    "Review",
    "ReviewDecision",
    "Run",
    "RunStatus",
    "Usage",
]
