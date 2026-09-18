from __future__ import annotations

from datetime import datetime
from typing import Any

from nonprofit_harness.core.types import (
    Artifact,
    ArtifactStatus,
    Document,
    Review,
    ReviewDecision,
    Run,
    RunStatus,
    Usage,
)
from nonprofit_harness.verification.types import Citation, Claim, VerificationReport


def run_to_dict(run: Run) -> dict[str, Any]:
    return {
        "id": run.id,
        "agent": run.agent,
        "org_id": run.org_id,
        "status": str(run.status),
        "inputs": [
            {
                "id": d.id,
                "name": d.name,
                "media_type": d.media_type,
                "text": d.text,
                "metadata": d.metadata,
            }
            for d in run.inputs
        ],
        "artifacts": [artifact_to_dict(a) for a in run.artifacts],
        "usage": {
            "input_tokens": run.usage.input_tokens,
            "output_tokens": run.usage.output_tokens,
            "cost_usd": run.usage.cost_usd,
            "calls": run.usage.calls,
        },
        "summary": run.summary,
        "error": run.error,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "metadata": run.metadata,
    }


def artifact_to_dict(artifact: Artifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "kind": artifact.kind,
        "title": artifact.title,
        "content": artifact.content,
        "status": str(artifact.status),
        "metadata": artifact.metadata,
        "claims": [
            {
                "id": claim.id,
                "statement": claim.statement,
                "choices": claim.choices,
                "expected": claim.expected,
                "metadata": claim.metadata,
                "citations": [
                    {"text": c.text, "document": c.document, "locator": c.locator}
                    for c in claim.citations
                ],
            }
            for claim in artifact.claims
        ],
        "verification": artifact.verification.to_dict() if artifact.verification else None,
        "review": (
            {
                "decision": str(artifact.review.decision),
                "reviewer": artifact.review.reviewer,
                "note": artifact.review.note,
                "at": artifact.review.at,
            }
            if artifact.review
            else None
        ),
    }


def run_from_dict(data: dict[str, Any]) -> Run:
    run = Run(
        agent=data["agent"],
        org_id=data["org_id"],
        id=data["id"],
        status=RunStatus(data["status"]),
        summary=data.get("summary", ""),
        error=data.get("error", ""),
        metadata=data.get("metadata", {}) or {},
    )
    run.inputs = [
        Document(
            text=d.get("text", ""),
            name=d.get("name", "untitled"),
            media_type=d.get("media_type", "text/plain"),
            id=d["id"],
            metadata=d.get("metadata", {}) or {},
        )
        for d in data.get("inputs", [])
    ]
    run.artifacts = [artifact_from_dict(a) for a in data.get("artifacts", [])]
    usage = data.get("usage") or {}
    run.usage = Usage(
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cost_usd=usage.get("cost_usd", 0.0),
        calls=usage.get("calls", 0),
    )
    run.created_at = _as_datetime(data.get("created_at")) or run.created_at
    run.updated_at = _as_datetime(data.get("updated_at")) or run.updated_at
    return run


def artifact_from_dict(data: dict[str, Any]) -> Artifact:
    review_data = data.get("review")
    verification_data = data.get("verification")
    return Artifact(
        kind=data["kind"],
        content=data.get("content", ""),
        title=data.get("title", ""),
        id=data["id"],
        status=ArtifactStatus(data.get("status", "draft")),
        metadata=data.get("metadata", {}) or {},
        claims=[
            Claim(
                statement=c["statement"],
                id=c["id"],
                choices=c.get("choices"),
                expected=c.get("expected"),
                metadata=c.get("metadata", {}) or {},
                citations=[
                    Citation(
                        text=cit["text"],
                        document=cit.get("document", ""),
                        locator=cit.get("locator", ""),
                    )
                    for cit in c.get("citations", [])
                ],
            )
            for c in data.get("claims", [])
        ],
        verification=(
            VerificationReport.from_dict(verification_data) if verification_data else None
        ),
        review=(
            Review(
                decision=ReviewDecision(review_data["decision"]),
                reviewer=review_data["reviewer"],
                note=review_data.get("note", ""),
                at=_as_datetime(review_data.get("at")) or datetime.now(),
            )
            if review_data
            else None
        ),
    )


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    to_datetime = getattr(value, "timestamp", None)
    return value if to_datetime is None else value


__all__ = ["artifact_from_dict", "artifact_to_dict", "run_from_dict", "run_to_dict"]
