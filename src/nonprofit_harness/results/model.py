"""Results, indicators, baselines and periods, as the IATI Standard defines them.

Deliberately not invented. This sector already has a specified model for what a
programme set out to change and whether it did, and publishers report against it. The
structure here mirrors the standard's `result` element so that data read from IATI maps
across without translation, and so that an organisation not publishing to IATI still
ends up with a shape it can publish later.

Three attributes carry most of the meaning and are easy to skip past:

`measure`   what kind of number this is. You cannot add percentages together, and a
            qualitative indicator has no number at all.
`ascending` which direction is good. Clinics built improves upward; cases of a disease
            improves downward, and a naive ratio scores a success as a shortfall.
`aggregatable` the publisher's own statement about whether these values may be summed.
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
    """IATI IndicatorMeasure. Determines what arithmetic is legitimate."""

    UNIT = "unit"
    PERCENTAGE = "percentage"
    NOMINAL = "nominal"
    ORDINAL = "ordinal"
    QUALITATIVE = "qualitative"

    @classmethod
    def from_code(cls, code: str | int) -> Measure:
        return {
            "1": cls.UNIT,
            "2": cls.PERCENTAGE,
            "3": cls.NOMINAL,
            "4": cls.ORDINAL,
            "5": cls.QUALITATIVE,
        }.get(str(code), cls.UNIT)

    @property
    def is_numeric(self) -> bool:
        """Qualitative indicators carry no value; the standard says so explicitly."""
        return self is not Measure.QUALITATIVE

    @property
    def is_summable(self) -> bool:
        """Only counts add up.

        Summing percentages is meaningless, and nominal and ordinal codes are labels
        that happen to be written as numbers.
        """
        return self is Measure.UNIT


@dataclass(frozen=True, slots=True)
class Dimension:
    """A disaggregation, such as sex=female or age=adult."""

    name: str
    value: str

    def __str__(self) -> str:
        return f"{self.name}={self.value}"


@dataclass(slots=True)
class Measurement:
    """One reported number: a target, an actual, or a baseline.

    `dimensions` is what makes a measurement a slice rather than a total. An indicator
    reporting separately for women and men has two measurements per period, and adding
    them to the undisaggregated total would double count.
    """

    value: float | None = None
    dimensions: tuple[Dimension, ...] = ()
    location: str = ""
    comment: str = ""

    @property
    def is_disaggregated(self) -> bool:
        return bool(self.dimensions)

    def matches(self, **dimensions: str) -> bool:
        wanted = {Dimension(name, value) for name, value in dimensions.items()}
        return wanted.issubset(set(self.dimensions))


@dataclass(slots=True)
class Baseline:
    """Where things stood before the work started."""

    value: float | None = None
    year: int | None = None
    iso_date: date | None = None
    dimensions: tuple[Dimension, ...] = ()
    comment: str = ""


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
    """Prefer the undisaggregated figure, since slices are not the whole.

    A publisher reporting only slices has no stated total, and inventing one by adding
    them would assume the slices are exhaustive and non-overlapping. Neither is
    guaranteed, so this returns nothing and leaves the decision to the caller.
    """
    for measurement in measurements:
        if not measurement.is_disaggregated and measurement.value is not None:
            return measurement
    return None


__all__ = [
    "Baseline",
    "Dimension",
    "Indicator",
    "Measure",
    "Measurement",
    "Period",
    "Result",
    "ResultType",
]
