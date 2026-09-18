from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


@dataclass(slots=True)
class Citation:
    """A span of source text an agent says supports a claim.

    `locator` is free text for wherever the span came from — a page number, a
    section heading, a row id. The harness never parses it; it exists so a human
    reviewer can find the passage without searching for it.
    """

    text: str
    document: str = ""
    locator: str = ""


@dataclass(slots=True)
class Claim:
    """Something an artifact asserts, together with what it says backs that up.

    `choices` and `expected` are optional. Without them, verification asks whether
    the evidence supports the statement. With them, reviewers pick a label and the
    result is cross-checked against the one the agent committed to, which catches an
    agent that cited real evidence and then drew the wrong conclusion from it.
    """

    statement: str
    citations: list[Citation] = field(default_factory=list)
    id: str = field(default_factory=lambda: f"clm_{uuid.uuid4().hex[:12]}")
    choices: dict[str, str] | None = None
    expected: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GroundingHit:
    """Where a citation was found, and how convincingly."""

    document: str
    mode: Literal["exact", "fuzzy"]
    score: float


class Outcome(StrEnum):
    VERIFIED = "verified"
    UNCITED = "uncited"
    CITATION_NOT_FOUND = "citation_not_found"
    DISPUTED = "disputed"
    INCONCLUSIVE = "inconclusive"


@dataclass(slots=True)
class Verdict:
    claim_id: str
    outcome: Outcome
    reason: str = ""
    grounded: list[GroundingHit] = field(default_factory=list)
    ungrounded: list[str] = field(default_factory=list)
    votes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.outcome == Outcome.VERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "outcome": str(self.outcome),
            "reason": self.reason,
            "grounded": [
                {"document": g.document, "mode": g.mode, "score": g.score} for g in self.grounded
            ],
            "ungrounded": list(self.ungrounded),
            "votes": list(self.votes),
        }


@dataclass(slots=True)
class VerificationReport:
    verdicts: list[Verdict] = field(default_factory=list)

    @property
    def verified(self) -> list[Verdict]:
        return [v for v in self.verdicts if v.ok]

    @property
    def failed(self) -> list[Verdict]:
        return [v for v in self.verdicts if not v.ok]

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        """One line a reviewer can read without opening anything."""
        total = len(self.verdicts)
        if total == 0:
            return "no claims to verify"
        if self.ok:
            return f"{total} claim(s), all verified"
        reasons: dict[str, int] = {}
        for verdict in self.failed:
            reasons[str(verdict.outcome)] = reasons.get(str(verdict.outcome), 0) + 1
        detail = ", ".join(f"{count} {name.replace('_', ' ')}" for name, count in reasons.items())
        return f"{total} claim(s), {len(self.verified)} verified, {detail}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary(),
            "verified": len(self.verified),
            "failed": len(self.failed),
            "verdicts": [v.to_dict() for v in self.verdicts],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerificationReport:
        return cls(
            verdicts=[
                Verdict(
                    claim_id=v["claim_id"],
                    outcome=Outcome(v["outcome"]),
                    reason=v.get("reason", ""),
                    grounded=[
                        GroundingHit(g["document"], g["mode"], g["score"])
                        for g in v.get("grounded", [])
                    ],
                    ungrounded=list(v.get("ungrounded", [])),
                    votes=list(v.get("votes", [])),
                )
                for v in data.get("verdicts", [])
            ]
        )


__all__ = [
    "Citation",
    "Claim",
    "GroundingHit",
    "Outcome",
    "VerificationReport",
    "Verdict",
]
