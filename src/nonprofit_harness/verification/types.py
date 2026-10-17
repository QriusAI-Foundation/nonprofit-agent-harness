from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


@dataclass(slots=True)
class Citation:
    """A span of source text an agent says supports a claim.

    `locator` is free text for wherever the span came from: a page number, a
    section heading, a row id. The harness never parses it. It exists so a human
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
    """Where a citation was found, and how convincingly.

    `mode` is "exact" for a verbatim quote, "fuzzy" for one inside the bounded
    approximate rules in `grounding.py`, and "uncertain" for one a person has to
    compare. `note` says what differs, for the reviewer.
    """

    document: str
    mode: Literal["exact", "fuzzy", "uncertain"]
    score: float
    note: str = ""


class Outcome(StrEnum):
    """How a claim fared.

    VERIFIED means the citations resolved. Whether the source also supports the
    statement is known only when `Verdict.support_checked` is true, which needs the
    opt-in cross-check. A reviewer reads the two apart through `Verdict.label`.
    """

    VERIFIED = "verified"
    UNCITED = "uncited"
    CITATION_NOT_FOUND = "citation_not_found"
    CITATION_UNCERTAIN = "citation_uncertain"
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
    #: Citations that resemble the source but differ in ways the free check
    #: cannot judge. They hold the claim back for a person, like a missing one.
    uncertain: list[str] = field(default_factory=list)
    #: True once reviewers re-derived the claim from its evidence. Without that, a
    #: resolved citation says the quote is real, not that it backs the statement.
    support_checked: bool = False

    @property
    def ok(self) -> bool:
        return self.outcome == Outcome.VERIFIED

    @property
    def label(self) -> str:
        """The outcome in words that do not overstate what was checked."""
        if self.outcome == Outcome.VERIFIED:
            return "supported" if self.support_checked else "resolved (support not checked)"
        return str(self.outcome).replace("_", " ")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "outcome": str(self.outcome),
            "label": self.label,
            "support_checked": self.support_checked,
            "reason": self.reason,
            "grounded": [
                {"document": g.document, "mode": g.mode, "score": g.score, "note": g.note}
                for g in self.grounded
            ],
            "ungrounded": list(self.ungrounded),
            "uncertain": list(self.uncertain),
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
        """One line a reviewer can read without opening anything.

        Claims whose citations resolved but whose support nobody checked are counted
        apart from supported ones, so "found in the source" is never read as "true".
        """
        total = len(self.verdicts)
        if total == 0:
            return "no claims to verify"
        labels = Counter(verdict.label for verdict in self.verdicts)
        detail = ", ".join(f"{count} {label}" for label, count in labels.items())
        return f"{total} claim(s): {detail}"

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
                        GroundingHit(g["document"], g["mode"], g["score"], g.get("note", ""))
                        for g in v.get("grounded", [])
                    ],
                    ungrounded=list(v.get("ungrounded", [])),
                    votes=list(v.get("votes", [])),
                    uncertain=list(v.get("uncertain", [])),
                    support_checked=bool(v.get("support_checked", False)),
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
