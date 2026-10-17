from __future__ import annotations

import math

import pytest

from nonprofit_harness.core.errors import InvalidRequest
from nonprofit_harness.readiness import example_instrument, score
from nonprofit_harness.readiness.instrument import Instrument
from nonprofit_harness.readiness.scoring import ZERO_FLOOR


@pytest.fixture
def instrument() -> Instrument:
    return example_instrument()


def test_the_bundled_example_instrument_is_valid(instrument):
    assert instrument.validate() == []
    assert len(instrument.questions) == 6
    assert set(instrument.dimensions) == {"Data & Systems", "People & Skills"}


def test_a_perfect_set_of_answers_scores_one(instrument):
    result = score(
        instrument,
        {
            "d1": "integrated_system",
            "d2": "adopted",
            "d3": 5,
            "p1": ["writes_reports", "manages_spreadsheets", "builds_dashboards"],
            "p2": "regularly",
            "p3": "planned_annually",
        },
    )

    assert result.overall == pytest.approx(1.0)
    assert result.tier == "High"


def test_a_floor_set_of_answers_scores_at_the_zero_floor(instrument):
    result = score(
        instrument,
        {"d1": "paper_only", "d2": "no", "d3": 1, "p1": [], "p2": "never", "p3": "none"},
    )

    assert result.overall == pytest.approx(ZERO_FLOOR)
    assert result.tier == "Low"


def test_dont_know_drops_the_question_instead_of_scoring_it_zero(instrument):
    answers = {"d1": "integrated_system", "d2": "adopted", "d3": 5}

    with_dont_know = score(instrument, {**answers, "d2": "dont_know"})
    assert "d2" in with_dont_know.excluded_questions
    assert with_dont_know.dimension_scores["Data & Systems"] == pytest.approx(1.0)

    scored_as_worst = score(instrument, {**answers, "d2": "no"})
    assert scored_as_worst.dimension_scores["Data & Systems"] < 1.0


def test_geometric_mean_refuses_to_average_away_a_weak_dimension(instrument):
    lopsided = score(
        instrument,
        {
            "d1": "integrated_system",
            "d2": "adopted",
            "d3": 5,
            "p1": [],
            "p2": "never",
            "p3": "none",
        },
    )
    arithmetic = sum(lopsided.dimension_scores.values()) / len(lopsided.dimension_scores)

    assert lopsided.overall < arithmetic
    assert lopsided.overall == pytest.approx(math.sqrt(1.0 * ZERO_FLOOR), rel=1e-3)


def test_weights_are_applied_within_a_dimension(instrument):
    # p3 carries weight 0.5, so moving it alone shifts the dimension less than
    # moving an equally-sized full-weight question would.
    base = {"p1": [], "p2": "never", "p3": "none"}
    lifted_half = score(instrument, {**base, "p3": "planned_annually"})
    lifted_full = score(instrument, {**base, "p2": "regularly"})

    assert lifted_half.dimension_scores["People & Skills"] < (
        lifted_full.dimension_scores["People & Skills"]
    )


def test_unanswered_questions_are_reported_not_guessed(instrument):
    result = score(instrument, {"d1": "spreadsheets"})

    assert "d2" in result.unanswered_questions
    assert "p1" in result.unanswered_questions
    assert "People & Skills" not in result.dimension_scores


def test_an_unknown_option_is_rejected(instrument):
    with pytest.raises(InvalidRequest, match="no option"):
        score(instrument, {"d1": "carrier_pigeon"})


def test_a_scale_answer_is_clamped_to_its_range(instrument):
    assert score(instrument, {"d3": 99}).dimension_scores["Data & Systems"] == pytest.approx(1.0)
    assert score(instrument, {"d3": -5}).dimension_scores["Data & Systems"] == pytest.approx(0.0)


def test_an_instrument_declaring_an_unknown_dimension_is_rejected():
    with pytest.raises(InvalidRequest, match="not declared"):
        Instrument.from_dict(
            {
                "id": "bad",
                "name": "Bad",
                "dimensions": ["A"],
                "questions": [
                    {
                        "id": "q1",
                        "dimension": "B",
                        "options": [{"value": "x", "score": 1.0}],
                    }
                ],
            }
        )


def test_an_instrument_round_trips_through_a_dict(instrument):
    assert Instrument.from_dict(instrument.to_dict()).to_dict() == instrument.to_dict()


COMPLETE_ANSWERS = {
    "d1": "integrated_system",
    "d2": "adopted",
    "d3": 5,
    "p1": ["writes_reports", "manages_spreadsheets", "builds_dashboards"],
    "p2": "regularly",
    "p3": "planned_annually",
}


def test_duplicate_selections_do_not_raise_a_score(instrument):
    once = score(instrument, {**COMPLETE_ANSWERS, "p1": ["writes_reports"]})
    repeated = score(instrument, {**COMPLETE_ANSWERS, "p1": ["writes_reports"] * 3})

    assert repeated.dimension_scores == once.dimension_scores
    assert repeated.overall == once.overall
    assert repeated.duplicates_dropped == {"p1": ["writes_reports", "writes_reports"]}
    assert repeated.to_dict()["duplicates_dropped"] == {"p1": ["writes_reports"] * 2}


def test_one_answered_question_gets_no_unqualified_tier(instrument):
    result = score(instrument, {"d1": "integrated_system"})

    assert result.status == "incomplete"
    assert result.overall is None
    assert result.tier == ""
    assert result.missing_dimensions == ["People & Skills"]
    # The dimension that was answered still shows, so the work is not thrown away.
    assert result.dimension_scores == {"Data & Systems": pytest.approx(1.0)}
    assert "Incomplete" in result.to_dict()["status_note"]


def test_an_empty_submission_is_explicitly_incomplete(instrument):
    result = score(instrument, {})

    assert result.status == "incomplete"
    assert result.overall is None
    assert result.tier == ""
    assert result.missing_dimensions == list(instrument.dimensions)
    body = result.to_dict()
    assert body["coverage"]["overall"] == {
        "questions": 6,
        "answered": 0,
        "scored": 0,
        "excluded": 0,
        "unanswered": 6,
    }


def test_excluded_and_unanswered_stay_distinct(instrument):
    result = score(instrument, {"d1": "dont_know", "d2": "adopted", "p2": "dont_know"})

    assert result.excluded_questions == ["d1", "p2"]
    assert result.unanswered_questions == ["d3", "p1", "p3"]
    dimensions = result.to_dict()["coverage"]["dimensions"]
    assert dimensions["Data & Systems"] == {
        "questions": 3,
        "answered": 2,
        "scored": 1,
        "excluded": 1,
        "unanswered": 1,
    }
    assert dimensions["People & Skills"] == {
        "questions": 3,
        "answered": 1,
        "scored": 0,
        "excluded": 1,
        "unanswered": 2,
    }
    # Answering "don't know" to everything in a dimension still leaves nothing to
    # score there, so no overall tier.
    assert result.status == "incomplete"
    assert result.missing_dimensions == ["People & Skills"]


def test_a_complete_questionnaire_scores_as_before(instrument):
    result = score(instrument, COMPLETE_ANSWERS)

    assert result.status == "complete"
    assert result.complete
    assert result.overall == pytest.approx(1.0)
    assert result.tier == "High"
    assert result.missing_dimensions == []
    assert result.to_dict()["coverage"]["overall"]["unanswered"] == 0


def test_dont_know_counts_as_answered_for_completeness(instrument):
    result = score(instrument, {**COMPLETE_ANSWERS, "d2": "dont_know"})

    assert result.status == "complete"
    assert result.tier == "High"


def test_partial_coverage_issues_a_tier_but_says_it_is_partial(instrument):
    result = score(instrument, {"d1": "integrated_system", "p2": "regularly"})

    assert result.status == "partial"
    assert result.overall == pytest.approx(1.0)
    assert result.tier == "High"
    assert "Partial" in result.to_dict()["status_note"]


def test_the_result_keeps_its_existing_keys(instrument):
    body = score(instrument, COMPLETE_ANSWERS).to_dict()

    assert set(body) >= {
        "overall",
        "tier",
        "dimension_scores",
        "excluded_questions",
        "unanswered_questions",
        "instrument",
        "question_scores",
    }
