"""Deterministic calculations over results data.

No model calls. These are the sector's arithmetic, and the point of writing them down
is that each one has a way of being silently wrong:

- A ratio of actual to target scores a descending indicator backwards, so beating a
  target on disease cases reads as a shortfall.
- Progress measured from zero rather than from the baseline credits a programme with
  everything that was already true before it started.
- Summing across indicators quietly adds percentages together, or adds disaggregated
  slices to the total they are part of.
- Comparing figures for different populations, such as one district's actual against
  the programme's target, or a women-only baseline against an overall result.

Every function reports how it reached its answer rather than returning a bare number,
because a figure in a funder report needs to be explicable.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from nonprofit_harness.results.model import (
    Dimension,
    Indicator,
    Measure,
    Measurement,
    Period,
    Result,
    _headline,
)


class Basis(StrEnum):
    """How an achievement figure was arrived at."""

    FROM_BASELINE = "from_baseline"
    AGAINST_TARGET = "against_target"
    INVERTED_RATIO = "inverted_ratio"


class NotCalculable(StrEnum):
    NO_TARGET = "no_target"
    NO_ACTUAL = "no_actual"
    NOT_NUMERIC = "not_numeric"
    TARGET_EQUALS_BASELINE = "target_equals_baseline"
    ZERO_TARGET = "zero_target"
    #: Figures exist, but only for slices or locations, so there is no overall one.
    NO_TOTAL = "no_total"
    #: More than one overall figure, with different values.
    CONFLICTING_TOTALS = "conflicting_totals"
    #: The baseline describes a different population from the target and actual.
    BASELINE_SCOPE_MISMATCH = "baseline_scope_mismatch"
    NOMINAL_LABELS = "nominal_labels"
    ORDINAL_SCALE = "ordinal_scale"
    UNKNOWN_MEASURE = "unknown_measure"


@dataclass(slots=True)
class Achievement:
    """How far an indicator got, and how that was worked out."""

    indicator: str
    ratio: float | None = None
    basis: Basis | None = None
    reason: NotCalculable | None = None
    target: float | None = None
    actual: float | None = None
    baseline: float | None = None
    period: str = ""
    ascending: bool = True
    #: Why, in words, when `reason` alone does not say which figures were involved.
    detail: str = ""

    @property
    def met(self) -> bool:
        return self.ratio is not None and self.ratio >= 1.0

    @property
    def percent(self) -> float | None:
        return None if self.ratio is None else round(self.ratio * 100, 2)

    def explain(self) -> str:
        """A sentence a programme officer could put in front of a funder."""
        if self.ratio is None:
            why = (self.reason or "").replace("_", " ")
            tail = f": {self.detail}" if self.detail else ""
            return f"{self.indicator}: not calculable ({why}){tail}"
        direction = "lower is better" if not self.ascending else "higher is better"
        if self.basis is Basis.FROM_BASELINE:
            how = f"from a baseline of {_n(self.baseline)} towards {_n(self.target)}"
        elif self.basis is Basis.INVERTED_RATIO:
            how = f"against a target of {_n(self.target)}, {direction}"
        else:
            how = f"against a target of {_n(self.target)}"
        return f"{self.indicator}: {self.percent}% ({_n(self.actual)} {how})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicator": self.indicator,
            "ratio": self.ratio,
            "percent": self.percent,
            "met": self.met,
            "basis": str(self.basis) if self.basis else None,
            "reason": str(self.reason) if self.reason else None,
            "target": self.target,
            "actual": self.actual,
            "baseline": self.baseline,
            "period": self.period,
            "detail": self.detail,
        }


def achievement(indicator: Indicator, period: Period | None = None) -> Achievement:
    """How far this indicator got in a period, respecting direction and measure.

    Where a baseline exists, progress is measured from it: `(actual - baseline) /
    (target - baseline)`. That formula needs no special case for direction, because a
    descending indicator has a target below its baseline and both differences turn
    negative together. It is also the honest one, since a programme should be credited
    with the distance it moved rather than with where it started.
    """
    window = period or indicator.latest_period
    label = window.label() if window else ""
    base = Achievement(
        indicator=indicator.title, period=label, ascending=indicator.ascending
    )

    refusal = _measure_refusal(indicator.measure)
    if refusal is not None:
        base.reason, base.detail = refusal
        return base
    if window is None:
        base.reason = NotCalculable.NO_TARGET
        return base

    target, reason, detail = _total(window.targets, "target", NotCalculable.NO_TARGET)
    if target is None:
        base.reason, base.detail = reason, detail
        return base
    base.target = target
    actual, reason, detail = _total(window.actuals, "actual", NotCalculable.NO_ACTUAL)
    if actual is None:
        base.reason, base.detail = reason, detail
        return base
    base.actual = actual

    # Both are overall figures, so they describe the same population. The baseline is
    # the one figure that can still describe another, and measuring progress from it
    # would then compare two different groups of people.
    stated = indicator.baseline
    baseline = stated.value if stated else None
    base.baseline = baseline
    if stated is not None and baseline is not None and not stated.scope.is_total:
        base.reason = NotCalculable.BASELINE_SCOPE_MISMATCH
        base.detail = f"the baseline is for {stated.scope}, but the target and actual are overall"
        return base

    if baseline is not None:
        span = target - baseline
        if span == 0:
            base.reason = NotCalculable.TARGET_EQUALS_BASELINE
            return base
        base.ratio = round((actual - baseline) / span, 6)
        base.basis = Basis.FROM_BASELINE
        return base

    if target == 0:
        base.reason = NotCalculable.ZERO_TARGET
        return base

    if indicator.ascending:
        base.ratio = round(actual / target, 6)
        base.basis = Basis.AGAINST_TARGET
        return base

    # Descending, with no baseline to measure from. Inverting the ratio at least
    # points the right way: coming in under a target counts as beating it. It is a
    # convention rather than a derivation, which is why the basis says so.
    if actual == 0:
        base.ratio = None
        base.reason = NotCalculable.ZERO_TARGET
        return base
    base.ratio = round(target / actual, 6)
    base.basis = Basis.INVERTED_RATIO
    return base


def _measure_refusal(measure: Measure) -> tuple[NotCalculable, str] | None:
    """Why this measure admits no achievement ratio, or None when it does."""
    if measure.permits_ratio:
        return None
    return {
        Measure.QUALITATIVE: (NotCalculable.NOT_NUMERIC, "qualitative indicators carry no value"),
        Measure.NOMINAL: (
            NotCalculable.NOMINAL_LABELS,
            "nominal values are category labels, so a ratio of them means nothing",
        ),
        Measure.ORDINAL: (
            NotCalculable.ORDINAL_SCALE,
            "ordinal values are ranks with no fixed distance between them, so no "
            "percentage of the way to target can be stated",
        ),
    }.get(
        measure,
        (
            NotCalculable.UNKNOWN_MEASURE,
            "the publisher's measure code is not recognised, so no arithmetic is assumed",
        ),
    )


def _total(
    measurements: list[Measurement], role: str, missing: NotCalculable
) -> tuple[float | None, NotCalculable | None, str]:
    """The overall figure for one role, or why there is not one.

    Selection is by scope alone, so reordering the input never changes which
    population is reported.
    """
    chosen = _headline(measurements)
    if chosen is not None:
        return chosen.value, None, ""
    valued = [m for m in measurements if m.value is not None]
    if not valued:
        return None, missing, ""
    totals = [m for m in valued if not m.is_disaggregated]
    if totals:
        values = ", ".join(_n(v) for v in sorted({m.value for m in totals}))  # type: ignore[type-var]
        return None, NotCalculable.CONFLICTING_TOTALS, (
            f"the {role} has more than one overall figure ({values})"
        )
    scopes = "; ".join(sorted({str(m.scope) for m in valued}))
    return None, NotCalculable.NO_TOTAL, (
        f"the {role} is reported only for {scopes}, with no overall figure"
    )


def achievements(result: Result) -> list[Achievement]:
    return [achievement(indicator) for indicator in result.indicators]


@dataclass(slots=True)
class Total:
    value: float | None = None
    counted: int = 0
    refused: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.value is not None and not self.refused


def total_actual(indicators: list[Indicator], *, period: Period | None = None) -> Total:
    """Add up the latest actuals, refusing where addition would not mean anything.

    Refuses rather than filtering silently. A total that quietly dropped three of five
    indicators is more dangerous than no total, because it looks complete.
    """
    running = 0.0
    counted = 0
    refused: list[str] = []

    for indicator in indicators:
        if indicator.measure is Measure.UNKNOWN:
            refused.append(
                f"{indicator.title}: measure is unknown, so its values are not assumed "
                "to add up"
            )
            continue
        if not indicator.measure.is_summable:
            refused.append(f"{indicator.title}: {indicator.measure} values do not add up")
            continue
        if not indicator.aggregatable:
            refused.append(f"{indicator.title}: publisher marked it not aggregatable")
            continue
        window = period or indicator.latest_period
        actual, _, detail = _total(
            window.actuals if window else [], "actual", NotCalculable.NO_ACTUAL
        )
        if actual is None:
            refused.append(f"{indicator.title}: {detail or 'no reported actual'}")
            continue
        running += actual
        counted += 1

    return Total(value=running if counted else None, counted=counted, refused=refused)


def disaggregate(
    measurements: list[Measurement], by: str
) -> dict[str, list[Measurement]]:
    """Group slices by one dimension, such as sex or age.

    Measurements not carrying that dimension are left out rather than bucketed as
    unknown, because an undisaggregated total is a different thing from a slice and
    mixing them produces a group that double counts.
    """
    grouped: dict[str, list[Measurement]] = defaultdict(list)
    for measurement in measurements:
        for dimension in measurement.dimensions:
            if dimension.name == by:
                grouped[dimension.value].append(measurement)
    return dict(grouped)


def dimension_totals(measurements: list[Measurement], by: str) -> dict[str, float]:
    """Sum each slice of one dimension. Only meaningful for countable measures."""
    return {
        value: sum(m.value for m in group if m.value is not None)
        for value, group in disaggregate(measurements, by).items()
    }


def coverage(measurements: list[Measurement], by: str) -> float | None:
    """What share of the undisaggregated total the slices account for.

    Well below 1.0 usually means the disaggregation is partial. Above 1.0 means the
    slices overlap, or one of them is itself a total. Either is worth seeing before a
    breakdown goes into a report.
    """
    total = _headline(measurements)
    headline = total.value if total is not None else None
    if headline is None or headline == 0:
        return None
    sliced = sum(dimension_totals(measurements, by).values())
    return round(sliced / headline, 6)


@dataclass(slots=True)
class Utilisation:
    """Spend against budget, and what it bought."""

    spent: float
    budget: float
    ratio: float
    currency: str = ""
    cost_per_unit: float | None = None

    @property
    def overspent(self) -> bool:
        return self.ratio > 1.0

    def explain(self) -> str:
        money = f"{self.currency} " if self.currency else ""
        share = round(self.ratio * 100, 1)
        line = f"{money}{_n(self.spent)} of {money}{_n(self.budget)} ({share}%)"
        if self.cost_per_unit is not None:
            line += f", {money}{_n(self.cost_per_unit)} per unit delivered"
        return line


def utilisation(
    *, spent: float, budget: float, delivered: float | None = None, currency: str = ""
) -> Utilisation:
    """Budget utilisation, and unit cost where something countable was delivered.

    Unit cost is left out rather than reported as infinity when nothing was delivered,
    since "infinite cost per beneficiary" is not a finding anyone can act on.
    """
    if budget <= 0:
        raise ValueError("budget must be positive to compute utilisation")
    return Utilisation(
        spent=spent,
        budget=budget,
        ratio=round(spent / budget, 6),
        currency=currency,
        cost_per_unit=(
            round(spent / delivered, 6) if delivered not in (None, 0) else None
        ),
    )


def _n(value: float | None) -> str:
    if value is None:
        return "unknown"
    return str(int(value)) if float(value).is_integer() else f"{value:,.2f}"


__all__ = [
    "Achievement",
    "Basis",
    "Dimension",
    "NotCalculable",
    "Total",
    "Utilisation",
    "achievement",
    "achievements",
    "coverage",
    "dimension_totals",
    "disaggregate",
    "total_actual",
    "utilisation",
]
