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
