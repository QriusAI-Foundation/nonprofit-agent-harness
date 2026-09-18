from __future__ import annotations

import pytest

from nonprofit_harness.verification import (
    SUPPORTED,
    UNSUPPORTED,
    Citation,
    Claim,
    GroundingVerifier,
    Outcome,
    SourceIndex,
    is_grounded,
)

SOURCE = (
    "The literacy programme reached twelve villages during the third quarter. "
    "Average attendance was thirty-four learners per session. "
    "Two facilitators resigned in August and have not yet been replaced. "
    "Current funding is committed through March of next year."
)


class ScriptedProvider:
    """Returns a fixed sequence of replies, so a vote can be set up exactly."""

    name = "scripted"
    default_model = "scripted-1"

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.models_used: list[str | None] = []

    def generate(self, prompt, *, system=None, model=None, **kwargs):
        from nonprofit_harness.core.types import Usage
        from nonprofit_harness.providers.base import ModelResponse

        self.models_used.append(model)
        text = self._replies.pop(0) if self._replies else ""
        return ModelResponse(text=text, model=model or self.default_model, usage=Usage(calls=1))


# --- grounding, which costs nothing ------------------------------------------------


def test_an_exact_quote_is_found():
    hit = SourceIndex({"report": SOURCE}).find("reached twelve villages")

    assert hit is not None
    assert hit.mode == "exact"
    assert hit.document == "report"


def test_matching_ignores_whitespace_and_case():
    assert is_grounded("REACHED    Twelve\n  Villages", SOURCE)


def test_an_invented_quote_is_not_found():
    assert not is_grounded("reached ninety villages in the first quarter", SOURCE)


def test_a_lightly_edited_quote_still_resolves_but_only_as_fuzzy():
    hit = SourceIndex({"report": SOURCE}).find("two facilitators resigned during August")

    assert hit is not None
    assert hit.mode == "fuzzy"
    assert hit.score < 1.0


def test_scattered_words_do_not_count_as_a_quote():
    """The check is against a passage, not the document's whole vocabulary.

    Every word below appears somewhere in the source. Matching on that alone would
    pass almost any sentence against a long document.
    """
    assert not is_grounded("funding reached thirty-four facilitators per village", SOURCE)


def test_a_swapped_number_is_not_an_approximate_quote():
    """The failure this check exists for.

    "reached ninety villages" shares two words in three with "reached twelve
    villages", so plain token overlap accepts it. Changing the figure is the most
    damaging thing a citation can do, so a missing quantity rejects the match.
    """
    assert not is_grounded("reached ninety villages", SOURCE)
    assert not is_grounded("reached 90 villages", SOURCE)
    assert not is_grounded("Three facilitators resigned in August", SOURCE)


def test_a_digit_swap_is_caught_too():
    source = "Average attendance was 34 learners per session."

    assert is_grounded("attendance was 34 learners", source)
    assert not is_grounded("attendance was 84 learners", source)


def test_a_wording_change_that_touches_no_number_is_still_tolerated():
    assert is_grounded("Two facilitators resigned during August", SOURCE)


def test_an_empty_span_is_never_grounded():
    assert not is_grounded("", SOURCE)
    assert not is_grounded("   ", SOURCE)


def test_the_matching_document_is_reported():
    index = SourceIndex({"a.txt": "budget notes for the quarter", "b.txt": SOURCE})

    assert index.find("thirty-four learners").document == "b.txt"


# --- verdicts without a model ------------------------------------------------------


def test_a_claim_with_real_citations_is_verified():
    verifier = GroundingVerifier()
    claim = Claim(
        statement="The programme reached twelve villages.",
        citations=[Citation(text="reached twelve villages")],
    )

    verdict = verifier.verify(claim, {"report": SOURCE})

    assert verdict.outcome == Outcome.VERIFIED
    assert verdict.ok


def test_a_claim_citing_nothing_is_flagged():
    claim = Claim(statement="Attendance was excellent.")
    verdict = GroundingVerifier().verify(claim, {"report": SOURCE})

    assert verdict.outcome == Outcome.UNCITED
    assert not verdict.ok


def test_a_fabricated_citation_is_caught():
    claim = Claim(
        statement="The programme reached ninety villages.",
        citations=[Citation(text="reached ninety villages")],
    )

    verdict = GroundingVerifier().verify(claim, {"report": SOURCE})

    assert verdict.outcome == Outcome.CITATION_NOT_FOUND
    assert verdict.ungrounded == ["reached ninety villages"]


def test_one_bad_citation_among_good_ones_still_fails():
    claim = Claim(
        statement="Mixed claim.",
        citations=[
            Citation(text="reached twelve villages"),
            Citation(text="the minister opened the new building"),
        ],
    )

    verdict = GroundingVerifier().verify(claim, {"report": SOURCE})

    assert verdict.outcome == Outcome.CITATION_NOT_FOUND
    assert len(verdict.grounded) == 1
    assert len(verdict.ungrounded) == 1


def test_requiring_only_one_citation_can_be_opted_into():
    claim = Claim(
        statement="Mixed claim.",
        citations=[
            Citation(text="reached twelve villages"),
            Citation(text="the minister opened the new building"),
        ],
    )

    verdict = GroundingVerifier(require_all_citations=False).verify(claim, {"report": SOURCE})

    assert verdict.outcome == Outcome.VERIFIED


def test_cross_checking_without_a_provider_is_refused_at_construction():
    with pytest.raises(ValueError, match="needs a provider"):
        GroundingVerifier(passes=3)


# --- cross-checking ----------------------------------------------------------------


def grounded_claim(**kwargs) -> Claim:
    return Claim(
        statement="The programme reached twelve villages.",
        citations=[Citation(text="reached twelve villages")],
        **kwargs,
    )


def test_agreeing_reviewers_verify_a_claim():
    provider = ScriptedProvider([SUPPORTED, SUPPORTED, SUPPORTED])
    verifier = GroundingVerifier(provider=provider, passes=3)

    verdict = verifier.verify(grounded_claim(), {"report": SOURCE})

    assert verdict.outcome == Outcome.VERIFIED
    assert verdict.votes == [SUPPORTED] * 3


def test_a_majority_is_enough():
    provider = ScriptedProvider([SUPPORTED, UNSUPPORTED, SUPPORTED])

    verdict = GroundingVerifier(provider=provider, passes=3).verify(
        grounded_claim(), {"report": SOURCE}
    )

    assert verdict.outcome == Outcome.VERIFIED


def test_reviewers_who_disagree_with_the_claim_dispute_it():
    provider = ScriptedProvider([UNSUPPORTED, UNSUPPORTED, SUPPORTED])

    verdict = GroundingVerifier(provider=provider, passes=3).verify(
        grounded_claim(), {"report": SOURCE}
    )

    assert verdict.outcome == Outcome.DISPUTED
    assert "UNSUPPORTED" in verdict.reason


def test_all_reviewers_abstaining_is_inconclusive_not_a_pass():
    provider = ScriptedProvider(["UNSURE", "UNSURE", "UNSURE"])

    verdict = GroundingVerifier(provider=provider, passes=3).verify(
        grounded_claim(), {"report": SOURCE}
    )

    assert verdict.outcome == Outcome.INCONCLUSIVE
    assert not verdict.ok


def test_an_empty_reply_counts_as_an_abstention():
    provider = ScriptedProvider(["", "", SUPPORTED])

    verdict = GroundingVerifier(provider=provider, passes=3).verify(
        grounded_claim(), {"report": SOURCE}
    )

    # One real vote out of three does not reach a quorum of two.
    assert verdict.outcome == Outcome.INCONCLUSIVE
    assert verdict.votes == ["UNSURE", "UNSURE", SUPPORTED]


def test_unparseable_replies_do_not_become_votes():
    provider = ScriptedProvider(["probably yes?", "I think so", "definitely"])

    verdict = GroundingVerifier(provider=provider, passes=3).verify(
        grounded_claim(), {"report": SOURCE}
    )

    assert verdict.outcome == Outcome.INCONCLUSIVE


def test_the_answer_an_agent_committed_to_is_cross_checked():
    claim = grounded_claim(choices={"A": "twelve", "B": "ninety"}, expected="B")
    provider = ScriptedProvider(["A", "A", "A"])

    verdict = GroundingVerifier(provider=provider, passes=3).verify(claim, {"report": SOURCE})

    assert verdict.outcome == Outcome.DISPUTED
    assert "'A'" in verdict.reason and "'B'" in verdict.reason


def test_a_correct_committed_answer_passes():
    claim = grounded_claim(choices={"A": "twelve", "B": "ninety"}, expected="A")
    provider = ScriptedProvider(["A", "A", "B"])

    verdict = GroundingVerifier(provider=provider, passes=3).verify(claim, {"report": SOURCE})

    assert verdict.outcome == Outcome.VERIFIED


def test_passes_rotate_across_the_configured_models():
    provider = ScriptedProvider([SUPPORTED] * 3)
    verifier = GroundingVerifier(provider=provider, passes=3, models=["m1", "m2", "m3"])

    verifier.verify(grounded_claim(), {"report": SOURCE})

    assert provider.models_used == ["m1", "m2", "m3"]


def test_an_ungrounded_claim_never_reaches_the_model():
    provider = ScriptedProvider([SUPPORTED] * 3)
    claim = Claim(statement="Invented.", citations=[Citation(text="a fact not in the source")])

    GroundingVerifier(provider=provider, passes=3).verify(claim, {"report": SOURCE})

    assert provider.models_used == []


# --- reports -----------------------------------------------------------------------


def test_a_report_summarises_itself_for_a_reviewer():
    verifier = GroundingVerifier()
    claims = [
        Claim(statement="ok", citations=[Citation(text="reached twelve villages")]),
        Claim(statement="ok", citations=[Citation(text="thirty-four learners per session")]),
        Claim(statement="bad", citations=[Citation(text="a fact not in the source")]),
    ]

    report = verifier.verify_all(claims, {"report": SOURCE})

    assert not report.ok
    assert len(report.verified) == 2
    assert report.summary() == "3 claim(s), 2 verified, 1 citation not found"


def test_an_all_clear_report_says_so():
    report = GroundingVerifier().verify_all(
        [Claim(statement="ok", citations=[Citation(text="reached twelve villages")])],
        {"report": SOURCE},
    )

    assert report.ok
    assert report.summary() == "1 claim(s), all verified"


def test_a_report_round_trips_through_a_dict():
    from nonprofit_harness.verification.types import VerificationReport

    original = GroundingVerifier().verify_all(
        [
            Claim(statement="ok", citations=[Citation(text="reached twelve villages")]),
            Claim(statement="bad", citations=[Citation(text="not in there at all")]),
        ],
        {"report": SOURCE},
    )

    restored = VerificationReport.from_dict(original.to_dict())

    assert restored.to_dict() == original.to_dict()
    assert restored.summary() == original.summary()
