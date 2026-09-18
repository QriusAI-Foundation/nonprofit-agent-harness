from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from nonprofit_harness.core.types import Artifact, Run


class DocumentIn(BaseModel):
    text: str = ""
    name: str = "untitled"
    media_type: str = "text/plain"
    blob_id: str | None = Field(
        default=None, description="Use a previously uploaded file instead of inline text"
    )


class RunCreate(BaseModel):
    agent: str
    inputs: list[DocumentIn] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    org_id: str | None = None
    sync: bool = Field(default=False, description="Run inline and return the finished run")


class ReviewDecisionIn(BaseModel):
    note: str = ""
    reviewer: str | None = Field(
        default=None, description="Ignored when the request is authenticated"
    )


class ReadinessScoreIn(BaseModel):
    answers: dict[str, Any]
    instrument_id: str | None = None


class GoogleSignIn(BaseModel):
    credential: str = Field(description="The ID token from Google Sign-In")
    org_id: str | None = None


class UsageOut(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float
    calls: int


class ReviewOut(BaseModel):
    decision: str
    reviewer: str
    note: str
    at: datetime


class CitationOut(BaseModel):
    text: str
    document: str = ""
    locator: str = ""


class ClaimOut(BaseModel):
    id: str
    statement: str
    citations: list[CitationOut]
    expected: str | None = None


class ArtifactOut(BaseModel):
    id: str
    kind: str
    title: str
    content: str
    status: str
    metadata: dict[str, Any]
    review: ReviewOut | None = None
    claims: list[ClaimOut] = Field(default_factory=list)
    verification: dict[str, Any] | None = Field(
        default=None, description="Grounding verdicts, when the artifact made claims"
    )

    @classmethod
    def of(cls, artifact: Artifact) -> ArtifactOut:
        return cls(
            id=artifact.id,
            kind=artifact.kind,
            title=artifact.title,
            content=artifact.content,
            status=str(artifact.status),
            metadata=artifact.metadata,
            claims=[
                ClaimOut(
                    id=claim.id,
                    statement=claim.statement,
                    expected=claim.expected,
                    citations=[
                        CitationOut(text=c.text, document=c.document, locator=c.locator)
                        for c in claim.citations
                    ],
                )
                for claim in artifact.claims
            ],
            verification=(
                artifact.verification.to_dict() if artifact.verification else None
            ),
            review=(
                ReviewOut(
                    decision=str(artifact.review.decision),
                    reviewer=artifact.review.reviewer,
                    note=artifact.review.note,
                    at=artifact.review.at,
                )
                if artifact.review
                else None
            ),
        )


class RunOut(BaseModel):
    id: str
    agent: str
    org_id: str
    status: str
    summary: str
    error: str
    usage: UsageOut
    artifacts: list[ArtifactOut]
    pending_review: int
    failed_verification: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, run: Run) -> RunOut:
        return cls(
            id=run.id,
            agent=run.agent,
            org_id=run.org_id,
            status=str(run.status),
            summary=run.summary,
            error=run.error,
            usage=UsageOut(
                input_tokens=run.usage.input_tokens,
                output_tokens=run.usage.output_tokens,
                cost_usd=run.usage.cost_usd,
                calls=run.usage.calls,
            ),
            artifacts=[ArtifactOut.of(a) for a in run.artifacts],
            pending_review=len(run.pending_review),
            failed_verification=len(run.unverified),
            created_at=run.created_at,
            updated_at=run.updated_at,
        )


class AgentOut(BaseModel):
    name: str
    description: str
    version: str
    requires_review: bool
    budget_usd: float | None = None


class BlobOut(BaseModel):
    id: str
    name: str
    media_type: str
    size: int
    characters: int


class ErrorOut(BaseModel):
    error: str
    code: str


__all__ = [
    "AgentOut",
    "ArtifactOut",
    "BlobOut",
    "CitationOut",
    "ClaimOut",
    "DocumentIn",
    "ErrorOut",
    "GoogleSignIn",
    "ReadinessScoreIn",
    "ReviewDecisionIn",
    "ReviewOut",
    "RunCreate",
    "RunOut",
    "UsageOut",
]
