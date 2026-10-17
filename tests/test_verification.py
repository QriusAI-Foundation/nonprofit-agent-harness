from __future__ import annotations

import pytest

from nonprofit_harness.verification import (
    SUPPORTED,
    UNSUPPORTED,
    UNSURE,
    Citation,
    Claim,
    GroundingVerifier,
    Outcome,
    SourceIndex,
    is_grounded,
)
from nonprofit_harness.verification.grounding import max_edits
from nonprofit_harness.verification.verifier import VOTE_MAX_OUTPUT_TOKENS, parse_vote

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
        self.output_caps: list[int | None] = []

    def generate(self, prompt, *, system=None, model=None, **kwargs):
        from nonprofit_harness.core.types import Usage
        from nonprofit_harness.providers.base import ModelResponse

        self.models_used.append(model)
        self.output_caps.append(kwargs.get("max_output_tokens"))
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


# --- quotation integrity (audit F07) -----------------------------------------------
#
# Each test is named after the altered quotation it stops from showing as grounded.

FIGURES = (
    "Enrolment rose to 50 learners, and costs fell by 5.5% to 5,000 rupees. "
    "The programme did not reach the northern villages. "
    "The ministry funded the district office. "
    "The clinic never reached its targets."
)


def lookup(span: str, source: str = FIGURES):
    return SourceIndex({"report": source}).lookup(span)


def test_5_cannot_match_50_by_containment():
    assert not is_grounded("rose to 5", FIGURES)
    assert not is_grounded("reached 5", "The programme reached 50 villages.")
    assert is_grounded("rose to 50", FIGURES)


def test_a_number_cannot_match_inside_a_decimal_a_thousand_or_a_percentage():
    assert not is_grounded("fell by 5", FIGURES)
    assert not is_grounded("by 5.5 to 5 rupees", FIGURES)
    assert not is_grounded("costs fell by 5.5 to", FIGURES)
    assert is_grounded("costs fell by 5.5% to 5,000 rupees", FIGURES)


def test_a_changed_sign_or_currency_is_a_changed_number():
    assert not is_grounded("It raised \u20ac5 million.", "It raised $5 million.")
    assert not is_grounded("Temperatures reached 5 degrees", "Temperatures reached -5 degrees.")
    assert not is_grounded("5 degrees", "Temperatures reached -5 degrees.")


def test_a_number_cut_from_a_range_ratio_or_scale_is_flagged_for_a_human():
    for quote, source in [
        ("The score was 5.", "The score was 5-10."),
        ("Cost was 5", "Cost was 5/10 points."),
        ("The fund raised 5", "The fund raised 5 million dollars."),
    ]:
        result = lookup(quote, source)
        assert result.hit is not None and result.hit.mode == "uncertain", quote
        assert "continues" in result.hit.note


def test_a_number_the_source_qualifies_is_flagged_for_a_human():
    result = lookup("5 attended", "Fewer than 5 attended.")

    assert result.hit is not None
    assert result.hit.mode == "uncertain"


def test_a_word_cannot_match_inside_its_negative_contraction():
    source = "Staff can't reach the eastern district."

    assert not is_grounded("Staff can reach the eastern district", source)


def test_added_negation_cannot_pass():
    result = lookup("The ministry did not fund the district office")

    assert result.hit is None
    assert not is_grounded("The clinic did not reach its targets", FIGURES)


def test_removed_negation_cannot_pass():
    result = lookup("The programme did reach the northern villages")

    assert result.hit is None
    assert "negation" in result.refused
    assert not is_grounded("The clinic reached its targets", FIGURES)


def test_a_contracted_negation_is_the_same_quote():
    hit = SourceIndex({"report": FIGURES}).find("The programme didn't reach the northern villages")

    assert hit is not None
    assert hit.mode == "fuzzy"


def test_a_changed_quantity_stays_rejected_with_its_reason():
    result = lookup("Enrolment rose to 40 learners")

    assert result.hit is None
    assert "number" in result.refused


def test_reversed_content_word_order_is_rejected():
    result = lookup("The district office funded the ministry")

    assert result.hit is None
    assert "order" in result.refused


def test_swapped_prepositions_are_rejected_as_reordering():
    source = "Funds went from the state to the district office last year."

    result = lookup("Funds went to the state from the district office last year", source)

    assert result.hit is None
    assert "order" in result.refused


def test_case_and_whitespace_normalisation_still_match_exactly():
    hit = SourceIndex({"report": FIGURES}).find("THE MINISTRY\n   funded  the District office")

    assert hit is not None
    assert hit.mode == "exact"


def test_surrounding_quotation_marks_and_typographic_apostrophes_are_ignored():
    assert SourceIndex({"report": SOURCE}).find('"reached twelve villages,"').mode == "exact"
    assert is_grounded("Staff can\u2019t reach the district", "Staff can't reach the district.")


def test_a_quote_with_only_punctuation_drift_still_matches_approximately():
    hit = SourceIndex({"report": SOURCE}).find(
        "Average attendance, was thirty four learners per session"
    )

    assert hit is not None
    assert hit.mode == "fuzzy"
    assert hit.score == 1.0
    assert "punctuation" in hit.note


def test_a_dropped_article_is_a_bounded_approximation():
    hit = SourceIndex({"report": FIGURES}).find("The ministry funded district office")

    assert hit is not None
    assert hit.mode == "fuzzy"


def test_approximate_edits_are_bounded():
    assert max_edits(4) == 1
    assert max_edits(10) == 2
    assert max_edits(40) == 3
    # Two harmless swaps in a five-word quote exceed its budget of one.
    result = lookup("Two facilitators resigned during an August", SOURCE)

    assert result.hit is not None
    assert result.hit.mode == "uncertain"


def test_a_quote_the_rules_cannot_decide_is_flagged_for_a_human_not_verified():
    result = lookup("The ministry paid the district office")

    assert result.hit is not None
    assert result.hit.mode == "uncertain"
    assert not result.resolved
    assert not is_grounded("The ministry paid the district office", FIGURES)


def test_a_verbatim_fragment_of_a_negated_sentence_is_flagged_for_a_human():
    result = lookup("reached its targets")

    assert result.hit is not None
    assert result.hit.mode == "uncertain"
    assert "never" in result.hit.note
    for source in [
        "We did not even reach the targets.",
        "We failed to reach the targets.",
    ]:
        assert lookup("reach the targets", source).hit.mode == "uncertain", source


def test_a_long_source_is_searched_in_reasonable_time():
    import time

    filler = "the programme reached villages and funding for staff in the district " * 4000
    index = SourceIndex({"long": filler + SOURCE})
    started = time.perf_counter()

    assert index.find("Two facilitators resigned during August") is not None
    assert time.perf_counter() - started < 5


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


def test_without_a_cross_check_a_verdict_says_support_was_not_checked():
    claim = Claim(
        statement="The programme reached twelve villages.",
        citations=[Citation(text="reached twelve villages")],
    )

    verdict = GroundingVerifier().verify(claim, {"report": SOURCE})

    assert not verdict.support_checked
    assert verdict.label == "resolved (support not checked)"
    assert "support not checked" in verdict.reason


def test_an_uncertain_citation_holds_the_claim_for_a_person():
    claim = Claim(
        statement="The ministry paid for the office.",
        citations=[Citation(text="The ministry paid the district office")],
    )

    verdict = GroundingVerifier().verify(claim, {"report": FIGURES})

    assert verdict.outcome == Outcome.CITATION_UNCERTAIN
    assert not verdict.ok
    assert verdict.uncertain == ["The ministry paid the district office"]
    assert "compare them by hand" in verdict.reason


def test_a_refused_citation_says_why_the_closest_passage_was_refused():
    claim = Claim(
        statement="The programme reached the north.",
        citations=[Citation(text="The programme did reach the northern villages")],
    )

    verdict = GroundingVerifier().verify(claim, {"report": FIGURES})

    assert verdict.outcome == Outcome.CITATION_NOT_FOUND
    assert "negation" in verdict.reason


def test_an_uncertain_citation_never_reaches_the_model():
    provider = ScriptedProvider([SUPPORTED] * 3)
    claim = Claim(
        statement="Paid.", citations=[Citation(text="The ministry paid the district office")]
    )

    verdict = GroundingVerifier(provider=provider, passes=3).verify(claim, {"report": FIGURES})

    assert verdict.outcome == Outcome.CITATION_UNCERTAIN
    assert provider.models_used == []


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


def test_an_uncertain_citation_stays_visible_when_one_citation_is_enough():
    claim = Claim(
        statement="Mixed claim.",
        citations=[
            Citation(text="reached twelve villages"),
            Citation(text="the literacy programme served twelve villages"),
        ],
    )

    verdict = GroundingVerifier(require_all_citations=False).verify(claim, {"report": SOURCE})

    assert verdict.outcome == Outcome.VERIFIED
    assert verdict.uncertain == ["the literacy programme served twelve villages"]


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
    assert verdict.support_checked
    assert verdict.label == "supported"


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


def test_an_empty_reply_says_the_token_cap_is_the_likely_cause():
    provider = ScriptedProvider(["", "", ""])

    verdict = GroundingVerifier(provider=provider, passes=3).verify(
        grounded_claim(), {"report": SOURCE}
    )

    assert verdict.outcome == Outcome.INCONCLUSIVE
    assert verdict.votes == [UNSURE] * 3
    assert f"{VOTE_MAX_OUTPUT_TOKENS}-token output cap" in verdict.reason


def test_a_vote_after_reasoning_text_is_still_counted():
    reasoning = (
        "The evidence says the programme reached twelve villages. "
        "That is what the statement says, so it is not UNSUPPORTED.\n\n**SUPPORTED**"
    )
    provider = ScriptedProvider([reasoning, "Answer: SUPPORTED", UNSUPPORTED])

    verdict = GroundingVerifier(provider=provider, passes=3).verify(
        grounded_claim(), {"report": SOURCE}
    )

    assert verdict.votes == [SUPPORTED, SUPPORTED, UNSUPPORTED]
    assert verdict.outcome == Outcome.VERIFIED


def test_a_denied_label_in_prose_is_not_a_vote_for_it():
    assert parse_vote("On balance the claim is not SUPPORTED.", {SUPPORTED, UNSUPPORTED}) == UNSURE
    assert parse_vote("This is a fair reading.", {"A", "B"}) == UNSURE
    assert parse_vote("Reading the options.\nB", {"A", "B"}) == "B"


def test_votes_ask_for_room_to_reason():
    # Thinking shares the output ceiling on some models; 16 tokens left no text.
    provider = ScriptedProvider([SUPPORTED] * 3)

    GroundingVerifier(provider=provider, passes=3).verify(grounded_claim(), {"report": SOURCE})

    assert provider.output_caps == [VOTE_MAX_OUTPUT_TOKENS] * 3
    assert VOTE_MAX_OUTPUT_TOKENS >= 1024


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
    assert report.summary() == (
        "3 claim(s): 2 resolved (support not checked), 1 citation not found"
    )


def test_an_all_clear_report_says_so():
    report = GroundingVerifier().verify_all(
        [Claim(statement="ok", citations=[Citation(text="reached twelve villages")])],
        {"report": SOURCE},
    )

    assert report.ok
    assert report.summary() == "1 claim(s): 1 resolved (support not checked)"


def test_the_report_distinguishes_resolved_from_supported():
    claim = Claim(statement="ok", citations=[Citation(text="reached twelve villages")])
    sources = {"report": SOURCE}

    free = GroundingVerifier().verify_all([claim], sources)
    checked = GroundingVerifier(provider=ScriptedProvider([SUPPORTED] * 3), passes=3).verify_all(
        [claim], sources
    )

    assert free.summary() == "1 claim(s): 1 resolved (support not checked)"
    assert checked.summary() == "1 claim(s): 1 supported"
    assert free.to_dict()["verdicts"][0]["support_checked"] is False
    assert checked.to_dict()["verdicts"][0]["support_checked"] is True


def test_a_report_written_before_support_was_recorded_reads_as_not_checked():
    from nonprofit_harness.verification.types import VerificationReport

    old = {"verdicts": [{"claim_id": "c1", "outcome": "verified", "grounded": []}]}

    report = VerificationReport.from_dict(old)

    assert report.verdicts[0].label == "resolved (support not checked)"


def test_a_report_round_trips_through_a_dict():
    from nonprofit_harness.verification.types import VerificationReport

    original = GroundingVerifier().verify_all(
        [
            Claim(statement="ok", citations=[Citation(text="reached twelve villages")]),
            Claim(statement="bad", citations=[Citation(text="not in there at all")]),
            Claim(
                statement="unsure",
                citations=[Citation(text="the literacy programme served twelve villages")],
            ),
        ],
        {"report": SOURCE},
    )

    restored = VerificationReport.from_dict(original.to_dict())

    assert restored.to_dict() == original.to_dict()
    assert restored.summary() == original.summary()
