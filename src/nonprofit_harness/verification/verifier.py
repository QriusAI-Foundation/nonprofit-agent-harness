from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from nonprofit_harness.providers.base import ModelProvider
from nonprofit_harness.verification.grounding import SourceIndex
from nonprofit_harness.verification.types import (
    Claim,
    Outcome,
    Verdict,
    VerificationReport,
)

UNSURE = "UNSURE"
SUPPORTED = "SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"

#: Three different framings, not three runs of the same one. Reviewers that share a
#: framing tend to share its blind spots, which makes agreement between them much
#: weaker evidence than it looks.
_PASS_SYSTEMS = (
    "Answer using only the quoted evidence below. Ignore anything you know from "
    f"elsewhere. If the evidence does not settle it, reply {UNSURE}.",
    "You are checking whether a statement is overstated relative to the evidence "
    f"quoted for it. Judge only from that evidence. If it is ambiguous, reply {UNSURE}.",
    "Read the evidence first, then the statement. Decide what the evidence alone "
    f"establishes. Reply {UNSURE} rather than guessing.",
)


@dataclass
class GroundingVerifier:
    """Checks that an artifact's claims are actually supported by its sources.

    Two layers, and the first one is free:

    1. **Citation check.** Every quoted span must really appear in a source document.
       This costs no model calls, runs offline, and is what catches an invented
       citation, which is both the most common failure and the most damaging one.
    2. **Independent re-derivation.** Optional, and it costs model calls. Several
       reviewers re-decide the claim from its evidence alone and have to agree.

    Leave `passes` at zero and you get layer one on its own, which is a real check
    that any deployment can afford.
    """

    provider: ModelProvider | None = None
    passes: int = 0
    models: Sequence[str] = ()
    fuzzy_threshold: float = 0.6
    #: Every citation must resolve, not merely one of them. A single fabricated
    #: citation alongside two real ones is exactly what a reviewer needs to see.
    require_all_citations: bool = True
    _systems: tuple[str, ...] = field(default=_PASS_SYSTEMS, repr=False)

    def __post_init__(self) -> None:
        if self.passes > 0 and self.provider is None:
            raise ValueError("Cross-checking needs a provider; set passes=0 to skip it")

    def verify_all(self, claims: Sequence[Claim], sources: Mapping[str, str]) -> VerificationReport:
        index = SourceIndex(sources)
        return VerificationReport(verdicts=[self._verify(claim, index) for claim in claims])

    def verify(self, claim: Claim, sources: Mapping[str, str]) -> Verdict:
        return self._verify(claim, SourceIndex(sources))

    def _verify(self, claim: Claim, index: SourceIndex) -> Verdict:
        if not claim.citations:
            return Verdict(
                claim_id=claim.id,
                outcome=Outcome.UNCITED,
                reason="the claim cites nothing",
            )

        grounded = []
        ungrounded = []
        for citation in claim.citations:
            hit = index.find(citation.text, fuzzy_threshold=self.fuzzy_threshold)
            if hit is None:
                ungrounded.append(citation.text)
            else:
                grounded.append(hit)

        missing = bool(ungrounded) if self.require_all_citations else not grounded
        if missing:
            return Verdict(
                claim_id=claim.id,
                outcome=Outcome.CITATION_NOT_FOUND,
                reason=f"{len(ungrounded)} of {len(claim.citations)} citation(s) "
                "were not found in the source",
                grounded=grounded,
                ungrounded=ungrounded,
            )

        if self.passes <= 0:
            modes = {hit.mode for hit in grounded}
            detail = "every citation quotes the source exactly"
            if "fuzzy" in modes:
                detail = "citations resolve, some only approximately"
            return Verdict(
                claim_id=claim.id,
                outcome=Outcome.VERIFIED,
                reason=detail,
                grounded=grounded,
            )

        return self._cross_check(claim, grounded, ungrounded)

    def _cross_check(self, claim: Claim, grounded, ungrounded) -> Verdict:
        votes = [self._one_pass(claim, index) for index in range(self.passes)]
        tally = Counter(vote for vote in votes if vote != UNSURE)

        if not tally:
            return Verdict(
                claim_id=claim.id,
                outcome=Outcome.INCONCLUSIVE,
                reason="no reviewer could decide from the evidence alone",
                grounded=grounded,
                ungrounded=ungrounded,
                votes=votes,
            )

        winner, count = tally.most_common(1)[0]
        quorum = (self.passes // 2) + 1
        if count < quorum:
            return Verdict(
                claim_id=claim.id,
                outcome=Outcome.INCONCLUSIVE,
                reason=f"reviewers split {dict(tally)}, no majority of {quorum}",
                grounded=grounded,
                ungrounded=ungrounded,
                votes=votes,
            )

        target = claim.expected if claim.expected is not None else SUPPORTED
        if winner != target:
            return Verdict(
                claim_id=claim.id,
                outcome=Outcome.DISPUTED,
                reason=f"reviewers concluded {winner!r}, the claim asserts {target!r}",
                grounded=grounded,
                ungrounded=ungrounded,
                votes=votes,
            )

        return Verdict(
            claim_id=claim.id,
            outcome=Outcome.VERIFIED,
            reason=f"{count} of {self.passes} reviewers agreed, citations resolve",
            grounded=grounded,
            ungrounded=ungrounded,
            votes=votes,
        )

    def _one_pass(self, claim: Claim, index: int) -> str:
        evidence = "\n".join(f"- {citation.text!r}" for citation in claim.citations)

        if claim.choices:
            options = "\n".join(f"{key}: {value}" for key, value in claim.choices.items())
            instruction = (
                f"Reply with one label only, or {UNSURE}.\n\n"
                f"Statement: {claim.statement}\n\nOptions:\n{options}"
            )
            allowed = set(claim.choices)
        else:
            instruction = (
                f"Reply with {SUPPORTED}, {UNSUPPORTED}, or {UNSURE} and nothing else.\n\n"
                f"Statement: {claim.statement}"
            )
            allowed = {SUPPORTED, UNSUPPORTED}

        response = self.provider.generate(  # type: ignore[union-attr]
            f"{instruction}\n\nEvidence:\n{evidence}",
            system=self._systems[index % len(self._systems)],
            model=self._model_for(index),
            temperature=0.0,
            max_output_tokens=16,
        )

        # An empty reply is exactly as inconclusive as one that says so, so it is
        # treated as an abstention rather than being retried or counted as a vote.
        reply = (response.text or "").strip().upper().strip(".:,'\" ")
        return reply if reply in allowed else UNSURE

    def _model_for(self, index: int) -> str | None:
        if not self.models:
            return None
        return self.models[index % len(self.models)]


__all__ = ["SUPPORTED", "UNSUPPORTED", "UNSURE", "GroundingVerifier"]
