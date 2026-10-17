from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from nonprofit_harness.providers.base import ModelProvider
from nonprofit_harness.verification.grounding import SourceIndex
from nonprofit_harness.verification.types import (
    Claim,
    GroundingHit,
    Outcome,
    Verdict,
    VerificationReport,
)

UNSURE = "UNSURE"
SUPPORTED = "SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"

#: Output-token ceiling for one vote. The vote is one word, but on models where
#: thinking is always on (Claude Sonnet 5.5 and Opus 5.5) the reasoning spends the
#: same ceiling. At 16 they used all of it thinking and returned empty text, so
#: every vote abstained and every cross-checked claim came back inconclusive.
#: Observed replies take about 160 to 230 tokens; 1024 leaves room for a long one.
VOTE_MAX_OUTPUT_TOKENS = 1024

_VOTE_WORD = re.compile(r"[A-Z0-9_]+")
_DENIALS = frozenset(["NOT", "NO", "NEVER"])

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
       It establishes that a citation *resolved*, not that the claim is *supported*.
    2. **Independent re-derivation.** Optional, and it costs model calls. Several
       reviewers re-decide the claim from its evidence alone and have to agree.
       This is the only layer that speaks to support.

    Leave `passes` at zero and you get layer one on its own, which is a real check
    that any deployment can afford. Its verdicts say "support not checked".
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

        grounded: list[GroundingHit] = []
        ungrounded: list[str] = []
        uncertain: list[str] = []
        refusals: list[str] = []
        notes: list[str] = []
        for citation in claim.citations:
            lookup = index.lookup(citation.text, fuzzy_threshold=self.fuzzy_threshold)
            if lookup.resolved:
                grounded.append(lookup.hit)  # type: ignore[arg-type]
            elif lookup.hit is not None:
                uncertain.append(citation.text)
                notes.append(f"{lookup.hit.document}: {lookup.hit.note}")
            else:
                ungrounded.append(citation.text)
                if lookup.refused:
                    refusals.append(lookup.refused)

        total = len(claim.citations)
        held = self._held(grounded, ungrounded, uncertain)
        if held is not None:
            if held == Outcome.CITATION_NOT_FOUND:
                reason = f"{len(ungrounded)} of {total} citation(s) were not found in the source"
                if refusals:
                    refused = "; ".join(dict.fromkeys(refusals))
                    reason += f"; the closest passage was refused: {refused}"
            else:
                reason = (
                    f"{len(uncertain)} of {total} citation(s) resemble the source but differ in "
                    f"ways the free check cannot judge, compare them by hand ({'; '.join(notes)})"
                )
            return Verdict(
                claim_id=claim.id,
                outcome=held,
                reason=reason,
                grounded=grounded,
                ungrounded=ungrounded,
                uncertain=uncertain,
            )

        if self.passes <= 0:
            modes = {hit.mode for hit in grounded}
            detail = "citations resolved, every one quoted exactly"
            if "fuzzy" in modes:
                detail = "citations resolved, some only approximately"
            return Verdict(
                claim_id=claim.id,
                outcome=Outcome.VERIFIED,
                reason=f"{detail}; claim support not checked, the free check only finds quotes",
                grounded=grounded,
                ungrounded=ungrounded,
                uncertain=uncertain,
            )

        verdict = self._cross_check(claim, grounded, ungrounded)
        # With require_all_citations off, a claim can pass on one citation while
        # another only resembled the source. The reviewer still sees which.
        verdict.uncertain = uncertain
        return verdict

    def _held(self, grounded: list, ungrounded: list, uncertain: list) -> Outcome | None:
        """Why the citations keep this claim from a person's sign-off, if they do.

        A missing citation outranks an uncertain one: it is the stronger signal.
        """
        if self.require_all_citations:
            if ungrounded:
                return Outcome.CITATION_NOT_FOUND
            return Outcome.CITATION_UNCERTAIN if uncertain else None
        if grounded:
            return None
        return Outcome.CITATION_UNCERTAIN if uncertain else Outcome.CITATION_NOT_FOUND

    def _cross_check(self, claim: Claim, grounded, ungrounded) -> Verdict:
        allowed = set(claim.choices) if claim.choices else {SUPPORTED, UNSUPPORTED}
        replies = [self._one_pass(claim, index) for index in range(self.passes)]
        votes = [parse_vote(reply, allowed) for reply in replies]
        verdict = self._decide(claim, grounded, ungrounded, votes)

        empty = sum(1 for reply in replies if not reply.strip())
        if empty:
            # An empty reply is an abstention, but a reviewer needs to know it was
            # the cap and not the evidence: the fix is configuration, not the claim.
            verdict.reason += (
                f"; {empty} of {self.passes} reviewer(s) returned no text, which usually "
                f"means reasoning used the whole {VOTE_MAX_OUTPUT_TOKENS}-token output cap"
            )
        return verdict

    def _decide(self, claim: Claim, grounded, ungrounded, votes: list[str]) -> Verdict:
        tally = Counter(vote for vote in votes if vote != UNSURE)

        if not tally:
            return Verdict(
                claim_id=claim.id,
                outcome=Outcome.INCONCLUSIVE,
                reason="no reviewer could decide from the evidence alone",
                grounded=grounded,
                ungrounded=ungrounded,
                votes=votes,
                support_checked=True,
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
                support_checked=True,
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
                support_checked=True,
            )

        return Verdict(
            claim_id=claim.id,
            outcome=Outcome.VERIFIED,
            reason=f"citations resolved; claim supported by {count} of {self.passes} reviewers",
            grounded=grounded,
            ungrounded=ungrounded,
            votes=votes,
            support_checked=True,
        )

    def _one_pass(self, claim: Claim, index: int) -> str:
        """One reviewer's raw reply. Parsing happens in `parse_vote`."""
        evidence = "\n".join(f"- {citation.text!r}" for citation in claim.citations)

        if claim.choices:
            options = "\n".join(f"{key}: {value}" for key, value in claim.choices.items())
            instruction = (
                f"Reply with one label only, or {UNSURE}.\n\n"
                f"Statement: {claim.statement}\n\nOptions:\n{options}"
            )
        else:
            instruction = (
                f"Reply with {SUPPORTED}, {UNSUPPORTED}, or {UNSURE} and nothing else.\n\n"
                f"Statement: {claim.statement}"
            )

        response = self.provider.generate(  # type: ignore[union-attr]
            f"{instruction}\n\nEvidence:\n{evidence}",
            system=self._systems[index % len(self._systems)],
            model=self._model_for(index),
            temperature=0.0,
            max_output_tokens=VOTE_MAX_OUTPUT_TOKENS,
        )
        return response.text or ""

    def _model_for(self, index: int) -> str | None:
        if not self.models:
            return None
        return self.models[index % len(self.models)]


def parse_vote(reply: str, allowed: set[str]) -> str:
    """The vote in a reviewer's reply, or UNSURE.

    Models that reason aloud put text before the answer, so the last line is read
    first, then the last whole-word label anywhere in the reply. An empty reply is
    as inconclusive as one that says so: an abstention, never retried or counted.
    """
    labels = {label.upper(): label for label in allowed} | {UNSURE: UNSURE}
    lines = [line.strip().strip(".:,'\"*` ").upper() for line in reply.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return UNSURE
    if lines[-1] in labels:
        return labels[lines[-1]]

    words = _VOTE_WORD.findall(reply.upper())
    for position in range(len(words) - 1, -1, -1):
        word = words[position]
        # A one-letter choice label is read only from the last line: in prose, "A"
        # is the article far more often than the answer.
        if word not in labels or len(word) == 1:
            continue
        # "the evidence does not show it is SUPPORTED" is not a vote for it.
        if position and words[position - 1] in _DENIALS:
            return UNSURE
        return labels[word]
    return UNSURE


__all__ = [
    "SUPPORTED",
    "UNSUPPORTED",
    "UNSURE",
    "VOTE_MAX_OUTPUT_TOKENS",
    "GroundingVerifier",
    "parse_vote",
]
