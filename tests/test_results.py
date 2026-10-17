from __future__ import annotations

from datetime import date

import pytest

from nonprofit_harness.results import (
    Baseline,
    Basis,
    Dimension,
    Indicator,
    Measure,
    Measurement,
    NotCalculable,
    Period,
    Result,
    ResultType,
    achievement,
    achievements,
    coverage,
    dimension_totals,
    disaggregate,
    total_actual,
    utilisation,
)


def period(target=None, actual=None, *, end=date(2026, 12, 31), extra=()):
    return Period(
        start=date(2026, 1, 1),
        end=end,
        targets=[Measurement(value=target)] if target is not None else [],
        actuals=([Measurement(value=actual)] if actual is not None else []) + list(extra),
    )


# --- direction ----------------------------------------------------------------------


def test_an_ascending_indicator_reads_straightforwardly():
    indicator = Indicator(title="Clinics built", periods=[period(target=100, actual=75)])

    got = achievement(indicator)

    assert got.percent == 75.0
    assert got.basis is Basis.AGAINST_TARGET
    assert not got.met


def test_beating_a_descending_target_is_not_scored_as_a_shortfall():
    """The failure this exists to prevent.

    Target 50 cases, 40 actual. Fewer is better, so the target was beaten. A plain
    actual-over-target ratio would report 80% and read as a miss.
    """
    indicator = Indicator(
        title="Cases of disease", ascending=False, periods=[period(target=50, actual=40)]
    )

    got = achievement(indicator)

    assert got.met
    assert got.percent == 125.0
    assert got.basis is Basis.INVERTED_RATIO


def test_missing_a_descending_target_still_reads_as_a_miss():
    indicator = Indicator(
        title="Cases of disease", ascending=False, periods=[period(target=50, actual=100)]
    )

    assert achievement(indicator).percent == 50.0
    assert not achievement(indicator).met


# --- baselines ----------------------------------------------------------------------


def test_progress_is_measured_from_the_baseline_not_from_zero():
    """Otherwise a programme is credited with what was already true before it began."""
    indicator = Indicator(
        title="Enrolment rate",
        baseline=Baseline(value=60, year=2025),
        periods=[period(target=80, actual=70)],
    )

    got = achievement(indicator)

    assert got.basis is Basis.FROM_BASELINE
    assert got.percent == 50.0  # halfway from 60 to 80, not 70/80 = 87.5%


def test_the_baseline_formula_needs_no_special_case_for_direction():
    """A descending indicator has a target below its baseline, so both spans go negative."""
    indicator = Indicator(
        title="Dropout rate",
        ascending=False,
        baseline=Baseline(value=100),
        periods=[period(target=50, actual=75)],
    )

    assert achievement(indicator).percent == 50.0


def test_exceeding_a_baseline_target_goes_past_one_hundred():
    indicator = Indicator(
        title="Enrolment", baseline=Baseline(value=60), periods=[period(target=80, actual=90)]
    )

    assert achievement(indicator).percent == 150.0


def test_a_target_equal_to_the_baseline_is_refused_not_divided_by_zero():
    indicator = Indicator(
        title="Flat", baseline=Baseline(value=50), periods=[period(target=50, actual=60)]
    )

    got = achievement(indicator)

    assert got.ratio is None
    assert got.reason is NotCalculable.TARGET_EQUALS_BASELINE


# --- what cannot be calculated ------------------------------------------------------


def test_a_qualitative_indicator_has_no_number_to_compute():
    indicator = Indicator(
        title="Community perception",
        measure=Measure.QUALITATIVE,
        periods=[period(target=1, actual=1)],
    )

    assert achievement(indicator).reason is NotCalculable.NOT_NUMERIC


def test_a_missing_actual_is_reported_rather_than_treated_as_zero():
    indicator = Indicator(title="Wells dug", periods=[period(target=10)])

    got = achievement(indicator)

    assert got.ratio is None
    assert got.reason is NotCalculable.NO_ACTUAL
    assert got.target == 10  # still worth showing what was aimed for


def test_an_indicator_with_no_periods_is_not_calculable():
    assert achievement(Indicator(title="Nothing reported")).reason is NotCalculable.NO_TARGET


def test_a_zero_target_is_refused():
    indicator = Indicator(title="Zero target", periods=[period(target=0, actual=5)])

    assert achievement(indicator).reason is NotCalculable.ZERO_TARGET


# --- periods ------------------------------------------------------------------------


def test_the_latest_period_is_used_by_default():
    indicator = Indicator(
        title="Trained",
        periods=[
            period(target=10, actual=5, end=date(2025, 12, 31)),
            period(target=20, actual=20, end=date(2026, 12, 31)),
        ],
    )

    assert achievement(indicator).percent == 100.0


def test_an_explicit_period_can_be_chosen():
    earlier = period(target=10, actual=5, end=date(2025, 12, 31))
    indicator = Indicator(
        title="Trained", periods=[earlier, period(target=20, actual=20)]
    )

    assert achievement(indicator, earlier).percent == 50.0


# --- aggregation --------------------------------------------------------------------


def test_countable_indicators_add_up():
    indicators = [
        Indicator(title="Wells", periods=[period(target=10, actual=8)]),
        Indicator(title="Clinics", periods=[period(target=5, actual=4)]),
    ]

    got = total_actual(indicators)

    assert got.value == 12
    assert got.ok


def test_percentages_are_refused_rather_than_added():
    indicators = [
        Indicator(title="Wells", periods=[period(target=10, actual=8)]),
        Indicator(
            title="Attendance rate",
            measure=Measure.PERCENTAGE,
            periods=[period(target=90, actual=85)],
        ),
    ]

    got = total_actual(indicators)

    assert got.value == 8
    assert got.counted == 1
    assert not got.ok
    assert "do not add up" in got.refused[0]


def test_the_publishers_own_do_not_aggregate_flag_is_honoured():
    indicators = [
        Indicator(title="A", aggregatable=False, periods=[period(target=10, actual=8)])
    ]

    got = total_actual(indicators)

    assert got.value is None
    assert "not aggregatable" in got.refused[0]


def test_a_refusal_is_reported_rather_than_filtered_away():
    """A total that silently dropped half its inputs looks complete and is not."""
    indicators = [
        Indicator(title="A", periods=[period(target=10, actual=8)]),
        Indicator(title="B", periods=[period(target=10)]),
    ]

    got = total_actual(indicators)

    assert got.value == 8
    assert not got.ok
    assert "no reported actual" in got.refused[0]


# --- disaggregation -----------------------------------------------------------------


def women_and_men():
    return [
        Measurement(value=100),
        Measurement(value=60, dimensions=(Dimension("sex", "female"),)),
        Measurement(value=40, dimensions=(Dimension("sex", "male"),)),
    ]


def test_slices_group_by_dimension():
    grouped = disaggregate(women_and_men(), "sex")

    assert set(grouped) == {"female", "male"}
    assert dimension_totals(women_and_men(), "sex") == {"female": 60, "male": 40}


def test_the_undisaggregated_total_is_not_bucketed_as_a_slice():
    """Including it would double count, since it already contains every slice."""
    assert sum(dimension_totals(women_and_men(), "sex").values()) == 100


def test_coverage_shows_when_a_breakdown_accounts_for_the_whole():
    assert coverage(women_and_men(), "sex") == 1.0


def test_partial_coverage_is_visible():
    partial = [
        Measurement(value=100),
        Measurement(value=60, dimensions=(Dimension("sex", "female"),)),
    ]

    assert coverage(partial, "sex") == 0.6


def test_overlapping_slices_show_above_one():
    overlapping = [
        Measurement(value=100),
        Measurement(value=80, dimensions=(Dimension("sex", "female"),)),
        Measurement(value=70, dimensions=(Dimension("sex", "male"),)),
    ]

    assert coverage(overlapping, "sex") == 1.5


def test_an_unknown_dimension_yields_nothing():
    assert disaggregate(women_and_men(), "age") == {}


def test_a_measurement_can_be_matched_on_its_dimensions():
    m = Measurement(value=10, dimensions=(Dimension("sex", "female"), Dimension("age", "adult")))

    assert m.matches(sex="female")
    assert m.matches(sex="female", age="adult")
    assert not m.matches(sex="male")


def test_a_headline_figure_is_preferred_over_slices():
    p = Period(targets=women_and_men(), actuals=women_and_men())

    assert p.target.value == 100
    assert p.actual.value == 100


def test_slices_alone_produce_no_headline():
    """Adding them would assume they are exhaustive and do not overlap."""
    p = Period(actuals=[Measurement(value=60, dimensions=(Dimension("sex", "female"),))])

    assert p.actual is None


# --- money --------------------------------------------------------------------------


def test_utilisation_and_unit_cost():
    got = utilisation(spent=75_000, budget=100_000, delivered=500, currency="USD")

    assert got.ratio == 0.75
    assert got.cost_per_unit == 150
    assert not got.overspent
    assert "USD 150 per unit delivered" in got.explain()


def test_overspend_is_flagged():
    assert utilisation(spent=120, budget=100).overspent


def test_nothing_delivered_gives_no_unit_cost_rather_than_infinity():
    assert utilisation(spent=1000, budget=2000, delivered=0).cost_per_unit is None


def test_a_zero_budget_is_rejected():
    with pytest.raises(ValueError, match="must be positive"):
        utilisation(spent=10, budget=0)


# --- codes and explanations ---------------------------------------------------------


def test_iati_codes_map_to_readable_types():
    assert ResultType.from_code("1") is ResultType.OUTPUT
    assert ResultType.from_code(2) is ResultType.OUTCOME
    assert ResultType.from_code("9") is ResultType.OTHER
    assert Measure.from_code("2") is Measure.PERCENTAGE
    assert Measure.from_code("5") is Measure.QUALITATIVE


def test_an_achievement_explains_itself():
    indicator = Indicator(
        title="Enrolment", baseline=Baseline(value=60), periods=[period(target=80, actual=70)]
    )

    line = achievement(indicator).explain()

    assert "Enrolment: 50.0%" in line
    assert "from a baseline of 60 towards 80" in line


def test_an_uncalculable_achievement_says_why():
    indicator = Indicator(title="Perception", measure=Measure.QUALITATIVE)

    assert "not calculable" in achievement(indicator).explain()


def test_a_result_reports_every_indicator():
    result = Result(
        title="Improved schooling",
        type=ResultType.OUTCOME,
        indicators=[
            Indicator(title="Enrolment", periods=[period(target=100, actual=90)]),
            Indicator(title="Perception", measure=Measure.QUALITATIVE),
        ],
    )

    got = achievements(result)

    assert len(got) == 2
    assert got[0].percent == 90.0
    assert got[1].ratio is None


# --- scope: dimensions and location (audit F09, F10) -------------------------------


def at(value, location="", **dimensions):
    return Measurement(
        value=value,
        location=location,
        dimensions=tuple(Dimension(name, v) for name, v in dimensions.items()),
    )


def test_a_location_only_value_does_not_become_the_total():
    """Two districts and no dimensions: neither district is the programme."""
    p = Period(targets=[at(100)], actuals=[at(30, "KE-01"), at(50, "KE-02")])

    got = achievement(Indicator(title="Wells", periods=[p]))

    assert p.actual is None
    assert got.ratio is None
    assert got.reason is NotCalculable.NO_TOTAL


def test_different_locations_are_never_compared():
    """A's actual against B's target is not a result for anyone."""
    p = Period(targets=[at(100, "KE-01")], actuals=[at(80, "KE-02")])

    got = achievement(Indicator(title="Wells", periods=[p]))

    assert got.ratio is None
    assert got.reason is NotCalculable.NO_TOTAL
    assert "location KE-01" in got.detail


def test_a_genuine_total_still_works_beside_its_slices():
    p = Period(
        targets=[at(40, "KE-01"), at(100), at(60, sex="female")],
        actuals=[at(30, "KE-01"), at(80), at(50, sex="female")],
    )

    got = achievement(Indicator(title="Wells", periods=[p]))

    assert got.percent == 80.0
    assert got.basis is Basis.AGAINST_TARGET


def test_input_order_does_not_change_the_population():
    targets = [at(40, "KE-01"), at(100), at(60, "KE-02")]
    actuals = [at(35, "KE-02"), at(30, "KE-01"), at(80)]

    forwards = Period(targets=targets, actuals=actuals)
    backwards = Period(targets=targets[::-1], actuals=actuals[::-1])

    got = {achievement(Indicator(title="W", periods=[p])).percent for p in (forwards, backwards)}
    assert got == {80.0}


def test_an_absent_total_is_not_calculable_and_names_the_locations():
    p = Period(targets=[at(100)], actuals=[at(50, "KE-02"), at(30, "KE-01")])

    got = achievement(Indicator(title="Wells", periods=[p]))

    assert got.reason is NotCalculable.NO_TOTAL
    assert got.target == 100
    assert got.detail == (
        "the actual is reported only for location KE-01; location KE-02, "
        "with no overall figure"
    )
    assert "location KE-01; location KE-02" in got.explain()


def test_two_disagreeing_totals_are_refused_rather_than_picked_by_position():
    p = Period(targets=[at(100)], actuals=[at(80), at(60)])

    got = achievement(Indicator(title="Wells", periods=[p]))

    assert p.actual is None
    assert got.reason is NotCalculable.CONFLICTING_TOTALS
    assert "60, 80" in got.detail


def test_location_only_actuals_are_refused_from_a_total():
    indicators = [
        Indicator(title="Wells", periods=[period(target=10, actual=8)]),
        Indicator(title="Clinics", periods=[Period(actuals=[at(4, "KE-01")])]),
    ]

    got = total_actual(indicators)

    assert got.value == 8
    assert not got.ok
    assert "location KE-01" in got.refused[0]


def test_coverage_does_not_treat_a_location_figure_as_the_whole():
    measurements = [at(50, "KE-01"), at(60, sex="female"), at(40, sex="male")]

    assert coverage(measurements, "sex") is None


def test_a_scoped_baseline_is_refused_against_an_overall_result():
    """The audit's case: a women-only 60 would otherwise report 50%."""
    indicator = Indicator(
        title="Literacy",
        baseline=Baseline(value=60, dimensions=(Dimension("sex", "female"),)),
        periods=[period(target=100, actual=80)],
    )

    got = achievement(indicator)

    assert got.ratio is None
    assert got.reason is NotCalculable.BASELINE_SCOPE_MISMATCH
    assert got.detail == "the baseline is for sex=female, but the target and actual are overall"
    assert (got.target, got.actual, got.baseline) == (100, 80, 60)


def test_a_baseline_for_one_location_is_refused_against_an_overall_result():
    indicator = Indicator(
        title="Literacy",
        baseline=Baseline(value=60, location="KE-01"),
        periods=[period(target=100, actual=80)],
    )

    got = achievement(indicator)

    assert got.reason is NotCalculable.BASELINE_SCOPE_MISMATCH
    assert "location KE-01" in got.detail


def test_matched_overall_scopes_keep_the_baseline_formula_both_directions():
    upward = Indicator(
        title="Enrolment",
        baseline=Baseline(value=60),
        periods=[Period(targets=[at(80), at(50, "KE-01")], actuals=[at(70), at(40, "KE-01")])],
    )
    downward = Indicator(
        title="Dropouts",
        ascending=False,
        baseline=Baseline(value=100),
        periods=[Period(targets=[at(50)], actuals=[at(75), at(9, sex="female")])],
    )

    assert achievement(upward).percent == 50.0
    assert achievement(upward).basis is Basis.FROM_BASELINE
    assert achievement(downward).percent == 50.0


# --- measure semantics (audit F11) --------------------------------------------------


def test_nominal_labels_produce_no_percentage():
    """Category 2 against category 4 is not halfway to anything."""
    indicator = Indicator(
        title="Delivery model", measure=Measure.NOMINAL, periods=[period(target=4, actual=2)]
    )

    got = achievement(indicator)

    assert got.ratio is None
    assert got.reason is NotCalculable.NOMINAL_LABELS
    assert "labels" in got.explain()


def test_ordinal_ranks_produce_no_percentage():
    """Rank 3 of a target 4 from 2 is not a known fraction of the way."""
    indicator = Indicator(
        title="Capacity rating",
        measure=Measure.ORDINAL,
        baseline=Baseline(value=2),
        periods=[period(target=4, actual=3)],
    )

    got = achievement(indicator)

    assert got.ratio is None
    assert got.reason is NotCalculable.ORDINAL_SCALE


def test_an_unknown_measure_produces_no_percentage():
    indicator = Indicator(
        title="Mystery", measure=Measure.UNKNOWN, periods=[period(target=4, actual=2)]
    )

    got = achievement(indicator)

    assert got.ratio is None
    assert got.reason is NotCalculable.UNKNOWN_MEASURE


def test_unknown_codes_are_not_summable():
    indicators = [
        Indicator(title="Wells", periods=[period(target=10, actual=8)]),
        Indicator(title="Mystery", measure=Measure.from_code("9"), periods=[period(actual=5)]),
    ]

    got = total_actual(indicators)

    assert got.value == 8
    assert not got.ok
    assert "measure is unknown" in got.refused[0]


def test_nominal_and_ordinal_values_are_not_summed():
    indicators = [
        Indicator(title="Model", measure=Measure.NOMINAL, periods=[period(actual=2)]),
        Indicator(title="Rating", measure=Measure.ORDINAL, periods=[period(actual=3)]),
    ]

    got = total_actual(indicators)

    assert got.value is None
    assert len(got.refused) == 2


def test_an_unrecognised_code_is_kept_unknown_rather_than_read_as_a_count():
    assert Measure.from_code("9") is Measure.UNKNOWN
    assert Measure.from_code("") is Measure.UNKNOWN
    assert Measure.from_code(None) is Measure.UNKNOWN
    assert Measure.from_code(1) is Measure.UNIT
    assert not Measure.UNKNOWN.is_summable
    assert not Measure.UNKNOWN.permits_ratio


@pytest.mark.parametrize(
    ("measure", "reason"),
    [
        (Measure.QUALITATIVE, NotCalculable.NOT_NUMERIC),
        (Measure.NOMINAL, NotCalculable.NOMINAL_LABELS),
        (Measure.ORDINAL, NotCalculable.ORDINAL_SCALE),
        (Measure.UNKNOWN, NotCalculable.UNKNOWN_MEASURE),
    ],
)
def test_every_unsupported_calculation_returns_a_reason(measure, reason):
    got = achievement(Indicator(title="X", measure=measure, periods=[period(4, 2)]))

    assert got.reason is reason
    assert got.detail
    assert got.to_dict()["detail"] == got.detail


def test_valid_counts_and_percentages_stay_correct():
    count = Indicator(title="Wells", periods=[period(target=10, actual=8)])
    share = Indicator(
        title="Attendance rate",
        measure=Measure.PERCENTAGE,
        baseline=Baseline(value=70),
        periods=[period(target=90, actual=85)],
    )

    assert achievement(count).percent == 80.0
    assert achievement(share).percent == 75.0
    assert total_actual([count]).value == 8
