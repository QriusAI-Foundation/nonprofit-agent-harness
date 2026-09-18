from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from nonprofit_harness.core.errors import InvalidRequest
from nonprofit_harness.readiness.instrument import Instrument, Question

#: Floor applied before taking logarithms. A single genuine zero would otherwise
#: collapse the whole index to zero, which reports a real weakness as a total
#: absence of capability.
ZERO_FLOOR = 0.01


@dataclass(frozen=True, slots=True)
class QuestionScore:
    question_id: str
    dimension: str
    score: float | None
    excluded: bool = False
    reason: str = ""


@dataclass(slots=True)
class ReadinessScore:
    overall: float
    tier: str
    dimension_scores: dict[str, float]
    question_scores: list[QuestionScore] = field(default_factory=list)
    excluded_questions: list[str] = field(default_factory=list)
    unanswered_questions: list[str] = field(default_factory=list)
    instrument_id: str = ""
    instrument_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "tier": self.tier,
            "dimension_scores": self.dimension_scores,
            "excluded_questions": self.excluded_questions,
            "unanswered_questions": self.unanswered_questions,
            "instrument": {"id": self.instrument_id, "version": self.instrument_version},
            "question_scores": [
                {
                    "question_id": q.question_id,
                    "dimension": q.dimension,
                    "score": q.score,
                    "excluded": q.excluded,
                    "reason": q.reason,
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
        chosen = []
        for value in values:
            option = question.option(str(value))
            if option is None:
                raise InvalidRequest(f"Question {question.id!r} has no option {value!r}")
            chosen.append(option)

        if chosen and all(o.excluded for o in chosen):
            return QuestionScore(
                question.id,
                question.dimension,
                None,
                excluded=True,
                reason="every selected option is excluded from scoring",
            )
        counted = [o for o in chosen if not o.excluded]
        scoreable = [o for o in question.options if not o.excluded]
        if not scoreable:
            return QuestionScore(
                question.id, question.dimension, None, excluded=True, reason="no scoreable options"
            )
        total = sum(o.score for o in counted)
        ceiling = sum(o.score for o in scoreable)
        normalised = 0.0 if ceiling == 0 else min(1.0, total / ceiling)
        return QuestionScore(question.id, question.dimension, normalised)

    raise InvalidRequest(f"Unknown question type {question.type!r}")


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

    overall = _geometric_mean(list(dimension_scores.values()), zero_floor=zero_floor)

    return ReadinessScore(
        overall=overall,
        tier=instrument.tier_for(overall),
        dimension_scores=dimension_scores,
        question_scores=question_scores,
        excluded_questions=[q.question_id for q in question_scores if q.excluded],
        unanswered_questions=[
            q.question_id for q in question_scores if q.score is None and not q.excluded
        ],
        instrument_id=instrument.id,
        instrument_version=instrument.version,
    )


def _geometric_mean(values: list[float], *, zero_floor: float) -> float:
    if not values:
        return 0.0
    floored = [max(value, zero_floor) for value in values]
    return round(math.exp(sum(math.log(v) for v in floored) / len(floored)), 6)


__all__ = ["ZERO_FLOOR", "QuestionScore", "ReadinessScore", "score", "score_question"]
