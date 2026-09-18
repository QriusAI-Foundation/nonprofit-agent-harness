from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


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


@dataclass(slots=True)
class Artifact:
    """Something an agent produced. Nothing leaves the harness until a human approves it."""

    kind: str
    content: str
    title: str = ""
    id: str = field(default_factory=lambda: _new_id("art"))
    status: ArtifactStatus = ArtifactStatus.DRAFT
    review: Review | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_released(self) -> bool:
        return self.status == ArtifactStatus.APPROVED


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0

    def add(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=round(self.cost_usd + other.cost_usd, 8),
            calls=self.calls + other.calls,
        )


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
