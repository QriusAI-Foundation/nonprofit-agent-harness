from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from nonprofit_harness.core.errors import InvalidRequest
from nonprofit_harness.readiness.instrument import Instrument, Option, Question

#: Floor applied before taking logarithms. A single genuine zero would otherwise
#: collapse the whole index to zero, which reports a real weakness as a total
#: absence of capability.
ZERO_FLOOR = 0.01

#: An overall index is a geometric mean across dimensions. Dropping a dimension that
#: has no scored answer changes what the index measures, so one answer in one
#: dimension used to come back as a confident overall tier.
COMPLETE = "complete"
PARTIAL = "partial"
INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class QuestionScore:
    question_id: str
    dimension: str
    score: float | None
    excluded: bool = False
    reason: str = ""
    #: Repeated multi-select values that were ignored, so a repeat never counts twice.
    duplicates_dropped: tuple[str, ...] = ()

    @property
    def answered(self) -> bool:
        return self.score is not None or self.excluded


@dataclass(frozen=True, slots=True)
class DimensionCoverage:
    """How much of one dimension the answers actually reached.

    `excluded` and `unanswered` stay separate: "don't know" is a deliberate answer
    that removes a question from scoring, while a blank is missing information.
    """

    dimension: str
    questions: int
    scored: int
    excluded: int
    unanswered: int

    @property
    def answered(self) -> int:
        return self.scored + self.excluded

    def to_dict(self) -> dict[str, Any]:
        return {
            "questions": self.questions,
            "answered": self.answered,
            "scored": self.scored,
            "excluded": self.excluded,
            "unanswered": self.unanswered,
        }


@dataclass(slots=True)
class ReadinessScore:
    #: None when the result is incomplete: no overall index is issued without a
    #: scored answer in every dimension.
    overall: float | None
    #: Empty when the result is incomplete.
    tier: str
    dimension_scores: dict[str, float]
    question_scores: list[QuestionScore] = field(default_factory=list)
    excluded_questions: list[str] = field(default_factory=list)
    unanswered_questions: list[str] = field(default_factory=list)
    instrument_id: str = ""
    instrument_version: str = ""
    status: str = INCOMPLETE
    coverage: list[DimensionCoverage] = field(default_factory=list)
    missing_dimensions: list[str] = field(default_factory=list)
    duplicates_dropped: dict[str, list[str]] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return self.status == COMPLETE

    def status_note(self) -> str:
        if self.status == INCOMPLETE:
            return (
                "Incomplete: no overall score or tier is issued until every dimension has "
                "at least one scored answer. Dimensions with no scored answer: "
                + ", ".join(self.missing_dimensions)
            )
        if self.status == PARTIAL:
            return (
                f"Partial: {len(self.unanswered_questions)} question(s) unanswered. The overall "
                "score uses only the questions that were answered."
            )
        return "Complete: every question was answered or deliberately excluded."

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "tier": self.tier,
            "status": self.status,
            "status_note": self.status_note(),
            "dimension_scores": self.dimension_scores,
            "missing_dimensions": self.missing_dimensions,
            "coverage": {
                "overall": _total_coverage(self.coverage).to_dict(),
                "dimensions": {c.dimension: c.to_dict() for c in self.coverage},
            },
            "excluded_questions": self.excluded_questions,
            "unanswered_questions": self.unanswered_questions,
            "duplicates_dropped": self.duplicates_dropped,
            "instrument": {"id": self.instrument_id, "version": self.instrument_version},
            "question_scores": [
                {
                    "question_id": q.question_id,
                    "dimension": q.dimension,
                    "score": q.score,
                    "excluded": q.excluded,
                    "reason": q.reason,
                    "duplicates_dropped": list(q.duplicates_dropped),
                }
                for q in self.question_scores
            ],
        }


def score_question(question: Question, answer: Any) -> QuestionScore:
    """Normalise one answer onto 0..1, or mark it out of scope.

    Direction is never inferred from the order options happen to appear in. Each
    option carries its own score, because a list-position rule silently inverts
    every question whose options run the other way.
    """
    if answer is None or answer == "" or answer == []:
        return QuestionScore(question.id, question.dimension, None, reason="unanswered")

    if question.type == "scale":
        try:
            value = float(answer)
        except (TypeError, ValueError):
            raise InvalidRequest(
                f"Question {question.id!r} is a scale but got {answer!r}"
            ) from None
        span = question.scale_max - question.scale_min
        clamped = min(max(value, question.scale_min), question.scale_max)
        return QuestionScore(question.id, question.dimension, (clamped - question.scale_min) / span)

    if question.type == "single_choice":
        option = question.option(str(answer))
        if option is None:
            raise InvalidRequest(f"Question {question.id!r} has no option {answer!r}")
        if option.excluded:
            return QuestionScore(
                question.id,
                question.dimension,
                None,
                excluded=True,
                reason=f"option {option.value!r} is excluded from scoring",
            )
        return QuestionScore(question.id, question.dimension, option.score)

    if question.type == "multi_select":
        values = answer if isinstance(answer, list | tuple | set) else [answer]
        chosen, duplicates = _distinct_options(question, values)

        if chosen and all(o.excluded for o in chosen):
            return QuestionScore(
                question.id,
                question.dimension,
                None,
                excluded=True,
                reason="every selected option is excluded from scoring",
                duplicates_dropped=duplicates,
            )
        counted = [o for o in chosen if not o.excluded]
        scoreable = [o for o in question.options if not o.excluded]
        if not scoreable:
            return QuestionScore(
                question.id,
                question.dimension,
                None,
                excluded=True,
                reason="no scoreable options",
                duplicates_dropped=duplicates,
            )
        total = sum(o.score for o in counted)
        ceiling = sum(o.score for o in scoreable)
        normalised = 0.0 if ceiling == 0 else min(1.0, total / ceiling)
        return QuestionScore(
            question.id, question.dimension, normalised, duplicates_dropped=duplicates
        )

    raise InvalidRequest(f"Unknown question type {question.type!r}")


def _distinct_options(question: Question, values: Any) -> tuple[list[Option], tuple[str, ...]]:
    """Resolve selected values to options, each at most once.

    Without this, three copies of one value scored like three distinct capabilities.
    """
    chosen: list[Option] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        option = question.option(str(value))
        if option is None:
            raise InvalidRequest(f"Question {question.id!r} has no option {value!r}")
        if option.value in seen:
            duplicates.append(option.value)
            continue
        seen.add(option.value)
        chosen.append(option)
    return chosen, tuple(duplicates)


def score(
    instrument: Instrument,
    answers: dict[str, Any],
    *,
    zero_floor: float = ZERO_FLOOR,
) -> ReadinessScore:
    """Turn a set of answers into a dimension profile and one overall index.

    Dimensions are averaged, then combined with a geometric mean rather than an
    arithmetic one. A geometric mean refuses to let a strong dimension paper over a
    weak one, which is the behaviour you want from a readiness index: an
    organisation with excellent tooling and no data governance is not "average",
    it is blocked on data governance.

    Coverage rule: an overall score and tier are issued only when every dimension has
    at least one scored answer. Otherwise the result is `incomplete`, `overall` is
    None and `tier` is empty, and `missing_dimensions` says what is missing. With
    every dimension covered but some questions blank, the result is `partial`.
    """
    question_scores: list[QuestionScore] = []
    for question in instrument.questions:
        question_scores.append(score_question(question, answers.get(question.id)))

    dimension_scores: dict[str, float] = {}
    for dimension in instrument.dimensions:
        scored = [
            (q, instrument.question(q.question_id))
            for q in question_scores
            if q.dimension == dimension and q.score is not None
        ]
        if not scored:
            continue
        weight_total = sum(question.weight for _, question in scored if question)
        if weight_total == 0:
            continue
        weighted = sum(
            result.score * question.weight for result, question in scored if question
        )
        dimension_scores[dimension] = round(weighted / weight_total, 6)

    coverage = [_coverage(dimension, question_scores) for dimension in instrument.dimensions]
    missing = [d for d in instrument.dimensions if d not in dimension_scores]
    status = _status(missing, coverage)
    overall = (
        None
        if status == INCOMPLETE
        else _geometric_mean(list(dimension_scores.values()), zero_floor=zero_floor)
    )

    return ReadinessScore(
        overall=overall,
        tier="" if overall is None else instrument.tier_for(overall),
        dimension_scores=dimension_scores,
        question_scores=question_scores,
        excluded_questions=[q.question_id for q in question_scores if q.excluded],
        unanswered_questions=[
            q.question_id for q in question_scores if q.score is None and not q.excluded
        ],
        instrument_id=instrument.id,
        instrument_version=instrument.version,
        status=status,
        coverage=coverage,
        missing_dimensions=missing,
        duplicates_dropped={
            q.question_id: list(q.duplicates_dropped)
            for q in question_scores
            if q.duplicates_dropped
        },
    )


def _coverage(dimension: str, question_scores: list[QuestionScore]) -> DimensionCoverage:
    mine = [q for q in question_scores if q.dimension == dimension]
    return DimensionCoverage(
        dimension=dimension,
        questions=len(mine),
        scored=sum(1 for q in mine if q.score is not None),
        excluded=sum(1 for q in mine if q.excluded),
        unanswered=sum(1 for q in mine if not q.answered),
    )


def _total_coverage(coverage: list[DimensionCoverage]) -> DimensionCoverage:
    return DimensionCoverage(
        dimension="",
        questions=sum(c.questions for c in coverage),
        scored=sum(c.scored for c in coverage),
        excluded=sum(c.excluded for c in coverage),
        unanswered=sum(c.unanswered for c in coverage),
    )


def _status(missing: list[str], coverage: list[DimensionCoverage]) -> str:
    # A dimension with only zero-weight scored questions has no dimension score
    # either, so `missing` is the test, not the counts.
    if missing or not coverage:
        return INCOMPLETE
    if any(c.unanswered for c in coverage):
        return PARTIAL
    return COMPLETE


def _geometric_mean(values: list[float], *, zero_floor: float) -> float:
    if not values:
        return 0.0
    floored = [max(value, zero_floor) for value in values]
    return round(math.exp(sum(math.log(v) for v in floored) / len(floored)), 6)


__all__ = [
    "COMPLETE",
    "INCOMPLETE",
    "PARTIAL",
    "ZERO_FLOOR",
    "DimensionCoverage",
    "QuestionScore",
    "ReadinessScore",
    "score",
    "score_question",
]
