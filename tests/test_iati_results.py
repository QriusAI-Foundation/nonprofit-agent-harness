"""Reconstructing indicators from the Datastore's flattened arrays.

Fixtures mirror shapes observed live, including the one that matters most: an activity
whose result-level fields are a different length from its indicator-level fields, which
is what makes the hierarchy unrecoverable.
"""

from __future__ import annotations

from datetime import date

from nonprofit_harness.datasources.iati_results import results_from_record
from nonprofit_harness.results import Measure, achievement

# Two indicators, two periods each. All indicator fields share one length, which is the
# case where reconstruction is safe.
ALIGNED = {
    "iati_identifier": "XX-1",
    "result_type": ["1", "1"],
    "result_title_narrative": ["Improved schooling", "Improved schooling"],
    "result_indicator_title_narrative": ["Enrolment", "Enrolment", "Dropouts", "Dropouts"],
    "result_indicator_description_narrative": ["Pupils enrolled"] * 2 + ["Pupils leaving"] * 2,
    "result_indicator_measure": ["1", "1", "1", "1"],
    "result_indicator_ascending": [True, True, False, False],
    "result_indicator_aggregation_status": [True, True, True, True],
    "result_indicator_reference_code": ["", "", "", ""],
    "result_indicator_baseline_value": ["60", "60", "100", "100"],
    "result_indicator_baseline_year": [2024, 2024, 2024, 2024],
    "result_indicator_period_period_start_iso_date": [
        "2025-01-01", "2026-01-01", "2025-01-01", "2026-01-01",
    ],
    "result_indicator_period_period_end_iso_date": [
        "2025-12-31", "2026-12-31", "2025-12-31", "2026-12-31",
    ],
    "result_indicator_period_target_value": ["70", "80", "80", "50"],
    "result_indicator_period_actual_value": ["65", "70", "90", "75"],
}


def test_indicators_are_rebuilt_with_their_periods():
    parsed = results_from_record(ALIGNED)

    assert [i.title for i in parsed.indicators] == ["Enrolment", "Dropouts"]
    assert all(len(i.periods) == 2 for i in parsed.indicators)
    assert parsed.rows == 4


def test_direction_survives_the_round_trip():
    """The whole point. Without it, beating a dropout target reads as a miss."""
    parsed = results_from_record(ALIGNED)
    enrolment, dropouts = parsed.indicators

    assert enrolment.ascending is True
    assert dropouts.ascending is False


def test_the_rebuilt_indicators_compute_correctly():
    parsed = results_from_record(ALIGNED)
    enrolment, dropouts = parsed.indicators

    # Enrolment: baseline 60, target 80, actual 70 in the latest period.
    assert achievement(enrolment).percent == 50.0
    # Dropouts: baseline 100, target 50, actual 75. Downward, so also halfway.
    assert achievement(dropouts).percent == 50.0


def test_periods_and_baselines_are_typed():
    indicator = results_from_record(ALIGNED).indicators[0]

    assert indicator.periods[0].start == date(2025, 1, 1)
    assert indicator.periods[1].end == date(2026, 12, 31)
    assert indicator.baseline.value == 60
    assert indicator.baseline.year == 2024
    assert indicator.measure is Measure.UNIT


def test_results_are_reported_but_never_attached():
    """Observed live: 16 result titles against 301 indicator rows, nothing relating them."""
    parsed = results_from_record(ALIGNED)

    assert parsed.result_titles == ("Improved schooling",)
    assert any("cannot be matched" in w for w in parsed.warnings)
    assert not parsed.ok


def test_a_misaligned_field_is_dropped_and_named():
    """Sparse optional fields come back compacted, so using them positionally misattributes."""
    record = {**ALIGNED, "result_indicator_period_target_comment_narrative": ["only one"]}

    parsed = results_from_record(record)

    assert any("target_comment_narrative has 1 entries" in w for w in parsed.warnings)
    assert len(parsed.indicators) == 2  # the rest still parses


def test_missing_direction_is_warned_about_not_silently_assumed():
    record = {k: v for k, v in ALIGNED.items() if k != "result_indicator_ascending"}

    parsed = results_from_record(record)

    assert any("direction is unknown" in w for w in parsed.warnings)
    assert parsed.indicators[0].ascending is True  # assumed, and said so


def test_a_record_with_no_results_yields_nothing_quietly():
    parsed = results_from_record({"iati_identifier": "XX-2"})

    assert parsed.indicators == []
    assert parsed.warnings == []
    assert parsed.rows == 0


def test_qualitative_indicators_carry_no_value():
    """The standard says so, so an absent value is correct rather than missing data."""
    record = {
        "result_indicator_title_narrative": ["Community perception"],
        "result_indicator_measure": ["5"],
        "result_indicator_period_period_end_iso_date": ["2026-12-31"],
    }

    indicator = results_from_record(record).indicators[0]

    assert indicator.measure is Measure.QUALITATIVE
    assert achievement(indicator).ratio is None


def test_unparseable_numbers_become_absent_rather_than_zero():
    record = {
        "result_indicator_title_narrative": ["Odd"],
        "result_indicator_measure": ["1"],
        "result_indicator_period_target_value": ["n/a"],
        "result_indicator_period_actual_value": [""],
        "result_indicator_period_period_end_iso_date": ["2026-12-31"],
    }

    indicator = results_from_record(record).indicators[0]

    assert indicator.periods[0].target is None
    assert indicator.periods[0].actual is None


def test_a_malformed_date_does_not_break_the_row():
    record = {
        "result_indicator_title_narrative": ["Odd"],
        "result_indicator_measure": ["1"],
        "result_indicator_period_period_end_iso_date": ["not-a-date"],
        "result_indicator_period_actual_value": ["5"],
    }

    period = results_from_record(record).indicators[0].periods[0]

    assert period.end is None
    assert period.actual.value == 5


def test_timestamps_are_accepted_as_dates():
    record = {
        "result_indicator_title_narrative": ["X"],
        "result_indicator_period_period_end_iso_date": ["2026-12-31T00:00:00Z"],
        "result_indicator_period_actual_value": ["1"],
    }

    assert results_from_record(record).indicators[0].periods[0].end == date(2026, 12, 31)


def test_indicators_sharing_a_title_but_differing_in_reference_stay_separate():
    record = {
        "result_indicator_title_narrative": ["Reach", "Reach"],
        "result_indicator_measure": ["1", "1"],
        "result_indicator_reference_code": ["A1", "B2"],
        "result_indicator_period_actual_value": ["10", "20"],
        "result_indicator_period_period_end_iso_date": ["2026-12-31", "2026-12-31"],
    }

    assert len(results_from_record(record).indicators) == 2


# --- disaggregation -----------------------------------------------------------------

# Shaped like live data from publishers reporting genuine sex and age breakdowns. The
# counts are what make this untrustworthy: two dimensions per measurement here, but a
# different number in the next activity, so a flat array cannot be paired with values.
DISAGGREGATED = {
    "result_indicator_title_narrative": ["Reach", "Reach"],
    "result_indicator_measure": ["1", "1"],
    "result_indicator_period_actual_value": ["87", "88"],
    "result_indicator_period_period_end_iso_date": ["2026-12-31", "2026-12-31"],
    "result_indicator_period_actual_dimension_name": ["sex", "age", "sex", "age"],
    "result_indicator_period_actual_dimension_value": [
        "female", "under 18", "male", "18+",
    ],
}


def test_the_disaggregations_a_programme_uses_are_reported():
    parsed = results_from_record(DISAGGREGATED)

    assert parsed.dimensions_used == {
        "age": ("18+", "under 18"),
        "sex": ("female", "male"),
    }
    assert parsed.disaggregated


def test_slices_are_never_attached_to_numbers():
    """Live data: 26 values against 52 dimensions, 8 against 28, 16 against 21.

    The count per measurement varies inside one activity, so nothing says which
    dimension belongs to which number.
    """
    parsed = results_from_record(DISAGGREGATED)

    for indicator in parsed.indicators:
        for period in indicator.periods:
            assert all(not m.dimensions for m in period.actuals)


def test_the_warning_names_what_was_found_and_why_it_is_unattached():
    parsed = results_from_record(DISAGGREGATED)

    warning = next(w for w in parsed.warnings if "disaggregates by" in w)
    assert "age, sex" in warning
    assert "not recoverable" in warning


def test_placeholder_dimensions_are_not_reported_as_a_breakdown():
    """One real publisher ships every dimension as the literal string TBD."""
    parsed = results_from_record(
        {
            "result_indicator_title_narrative": ["X"],
            "result_indicator_period_actual_dimension_name": ["TBD", "TBD"],
            "result_indicator_period_actual_dimension_value": ["TBD", "TBD"],
        }
    )

    assert parsed.dimensions_used == {}
    assert not parsed.disaggregated


def test_dimension_names_are_normalised_across_publishers():
    """Publishers write Gender, gender and Sex. Casing should not split a breakdown."""
    parsed = results_from_record(
        {
            "result_indicator_title_narrative": ["X"],
            "result_indicator_period_actual_dimension_name": ["Gender", "gender"],
            "result_indicator_period_actual_dimension_value": ["Female", "male"],
        }
    )

    assert set(parsed.dimensions_used) == {"gender"}


def test_target_dimensions_count_too():
    parsed = results_from_record(
        {
            "result_indicator_title_narrative": ["X"],
            "result_indicator_period_target_dimension_name": ["region"],
            "result_indicator_period_target_dimension_value": ["North"],
        }
    )

    assert parsed.dimensions_used == {"region": ("North",)}


def test_unpairable_dimension_arrays_are_ignored():
    parsed = results_from_record(
        {
            "result_indicator_title_narrative": ["X"],
            "result_indicator_period_actual_dimension_name": ["sex", "age"],
            "result_indicator_period_actual_dimension_value": ["female"],
        }
    )

    assert parsed.dimensions_used == {}


def test_no_disaggregation_is_itself_reported():
    """A programme reporting only totals cannot say who it reached."""
    parsed = results_from_record(ALIGNED)

    assert not parsed.disaggregated
    assert not any("disaggregates by" in w for w in parsed.warnings)
