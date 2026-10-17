"""Results, indicators, baselines and periods, as the IATI Standard defines them.

Deliberately not invented. This sector already has a specified model for what a
programme set out to change and whether it did, and publishers report against it. The
structure here mirrors the standard's `result` element so that data read from IATI maps
across without translation, and so that an organisation not publishing to IATI still
ends up with a shape it can publish later.

Three attributes carry most of the meaning and are easy to skip past:

`measure`   what kind of number this is. You cannot add percentages together, a
            qualitative indicator has no number at all, and a code nobody recognises
            stays UNKNOWN rather than being read as a count.
`ascending` which direction is good. Clinics built improves upward; cases of a disease
            improves downward, and a naive ratio scores a success as a shortfall.
`aggregatable` the publisher's own statement about whether these values may be summed.

A fourth is easy to miss because it is spread across fields: a figure's scope, its
dimensions and its location. Only figures with equal scopes may be compared.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any


class ResultType(StrEnum):
    """IATI ResultType. Outputs are what you did, outcomes what changed."""

    OUTPUT = "output"
    OUTCOME = "outcome"
    IMPACT = "impact"
    OTHER = "other"

    @classmethod
    def from_code(cls, code: str | int) -> ResultType:
        return {
            "1": cls.OUTPUT,
            "2": cls.OUTCOME,
            "3": cls.IMPACT,
            "9": cls.OTHER,
        }.get(str(code), cls.OTHER)


class Measure(StrEnum):
    """IATI IndicatorMeasure. Determines what arithmetic is legitimate.

    `UNKNOWN` is not an IATI code. It records that a publisher sent a code this does
    not recognise, or none at all, so that the doubt survives into the arithmetic
    instead of being resolved by assuming the value is a count.
    """

    UNIT = "unit"
    PERCENTAGE = "percentage"
    NOMINAL = "nominal"
    ORDINAL = "ordinal"
    QUALITATIVE = "qualitative"
    UNKNOWN = "unknown"

    @classmethod
    def from_code(cls, code: str | int | None) -> Measure:
        return {
            "1": cls.UNIT,
            "2": cls.PERCENTAGE,
            "3": cls.NOMINAL,
            "4": cls.ORDINAL,
            "5": cls.QUALITATIVE,
        }.get(str(code).strip() if code is not None else "", cls.UNKNOWN)

    @property
    def is_numeric(self) -> bool:
        """Whether a value is written as a number at all.

        Qualitative indicators carry no value; the standard says so explicitly. An
        unknown measure might be qualitative, so it is not assumed to be numeric. Being
        numeric does not make a ratio meaningful; see `permits_ratio`.
        """
        return self not in (Measure.QUALITATIVE, Measure.UNKNOWN)

    @property
    def permits_ratio(self) -> bool:
        """Whether actual over target, or progress from a baseline, means anything.

        Nominal values are labels, so 2 against 4 is not halfway. Ordinal values are
        ranks with no fixed distance between them, so moving from rank 2 to rank 3 is not
        a known fraction of moving from 2 to 4. Both are refused rather than scored.
        """
        return self in (Measure.UNIT, Measure.PERCENTAGE)

    @property
    def is_summable(self) -> bool:
        """Only counts add up.

        Summing percentages is meaningless, and nominal and ordinal codes are labels
        that happen to be written as numbers. An unknown measure might be any of these.
        """
        return self is Measure.UNIT


@dataclass(frozen=True, slots=True)
class Dimension:
    """A disaggregation, such as sex=female or age=adult."""

    name: str
    value: str

    def __str__(self) -> str:
        return f"{self.name}={self.value}"


@dataclass(frozen=True, slots=True)
class Scope:
    """Which population a figure describes: its dimensions and its location.

    Two figures may only be compared when their scopes are equal. An empty scope is the
    whole programme, which is the only thing a headline total can describe.
    """

    dimensions: frozenset[Dimension] = frozenset()
    location: str = ""

    @property
    def is_total(self) -> bool:
        return not self.dimensions and not self.location

    def __str__(self) -> str:
        if self.is_total:
            return "overall"
        parts = sorted(str(dimension) for dimension in self.dimensions)
        if self.location:
            parts.insert(0, f"location {self.location}")
        return ", ".join(parts)


@dataclass(slots=True)
class Measurement:
    """One reported number: a target, an actual, or a baseline.

    `dimensions` and `location` are what make a measurement a slice rather than a
    total. An indicator reporting separately for women and men, or for two districts,
    has several measurements per period, and adding them to the undisaggregated total
    would double count.
    """

    value: float | None = None
    dimensions: tuple[Dimension, ...] = ()
    location: str = ""
    comment: str = ""

    @property
    def scope(self) -> Scope:
        return Scope(frozenset(self.dimensions), self.location)

    @property
    def is_disaggregated(self) -> bool:
        """True for a slice by dimension or by location.

        A figure for one district is not the programme's total, even with no
        dimensions, and treating it as one reports a part as the whole.
        """
        return not self.scope.is_total

    def matches(self, **dimensions: str) -> bool:
        wanted = {Dimension(name, value) for name, value in dimensions.items()}
        return wanted.issubset(set(self.dimensions))


@dataclass(slots=True)
class Baseline:
    """Where things stood before the work started, for the population in `scope`."""

    value: float | None = None
    year: int | None = None
    iso_date: date | None = None
    dimensions: tuple[Dimension, ...] = ()
    comment: str = ""
    location: str = ""

    @property
    def scope(self) -> Scope:
        return Scope(frozenset(self.dimensions), self.location)


@dataclass(slots=True)
class Period:
    """A window with what was aimed for and what happened."""

    start: date | None = None
    end: date | None = None
    targets: list[Measurement] = field(default_factory=list)
    actuals: list[Measurement] = field(default_factory=list)

    @property
    def target(self) -> Measurement | None:
        """The undisaggregated target, which is the one to compare a total against."""
        return _headline(self.targets)

    @property
    def actual(self) -> Measurement | None:
        return _headline(self.actuals)

    def label(self) -> str:
        if self.start and self.end:
            return f"{self.start.isoformat()} to {self.end.isoformat()}"
        if self.end:
            return f"to {self.end.isoformat()}"
        return "unspecified period"


@dataclass(slots=True)
class Indicator:
    """What is being measured, and how it should be read."""

    title: str
    measure: Measure = Measure.UNIT
    #: True when a larger number is better. False for things you want less of.
    ascending: bool = True
    #: The publisher's statement about whether these values may be summed.
    aggregatable: bool = True
    description: str = ""
    baseline: Baseline | None = None
    periods: list[Period] = field(default_factory=list)
    reference: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def latest_period(self) -> Period | None:
        dated = [p for p in self.periods if p.end]
        if dated:
            return max(dated, key=lambda p: p.end)  # type: ignore[arg-type,return-value]
        return self.periods[-1] if self.periods else None


@dataclass(slots=True)
class Result:
    """One thing the programme set out to change."""

    title: str
    type: ResultType = ResultType.OUTPUT
    description: str = ""
    indicators: list[Indicator] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _headline(measurements: list[Measurement]) -> Measurement | None:
    """The total, chosen by scope and never by position.

    A publisher reporting only slices has no stated total, and inventing one by adding
    them would assume the slices are exhaustive and non-overlapping. Neither is
    guaranteed, so this returns nothing and leaves the decision to the caller. Two
    totals that disagree also return nothing, because picking the first would let input
    order decide the reported figure.
    """
    totals = _totals(measurements)
    if len({m.value for m in totals}) != 1:
        return None
    return totals[0]


def _totals(measurements: list[Measurement]) -> list[Measurement]:
    return [m for m in measurements if not m.is_disaggregated and m.value is not None]


__all__ = [
    "Baseline",
    "Dimension",
    "Indicator",
    "Measure",
    "Measurement",
    "Period",
    "Result",
    "ResultType",
    "Scope",
]
