from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from nonprofit_harness.core.errors import InvalidRequest

QuestionType = Literal["single_choice", "multi_select", "scale"]


@dataclass(frozen=True, slots=True)
class Option:
    value: str
    score: float = 0.0
    #: An excluded option drops its question from scoring instead of scoring it zero.
    #: "Don't know" is usually a sign of a thin back office, not of low capability,
    #: so scoring it as zero would systematically mark down the smallest organisations.
    excluded: bool = False


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    dimension: str
    type: QuestionType = "single_choice"
    text: str = ""
    options: tuple[Option, ...] = ()
    scale_min: float = 0.0
    scale_max: float = 1.0
    weight: float = 1.0

    def option(self, value: str) -> Option | None:
        return next((o for o in self.options if o.value == value), None)


@dataclass(frozen=True, slots=True)
class TierBand:
    name: str
    min_score: float
    max_score: float

    def contains(self, score: float) -> bool:
        return self.min_score <= score <= self.max_score


@dataclass(frozen=True, slots=True)
class Instrument:
    """A readiness questionnaire plus the rules for turning answers into a score.

    The engine is deliberately empty of any particular index. Bring your own
    questions, weights, and tier bands; the maths below stays the same.
    """

    id: str
    name: str
    dimensions: tuple[str, ...]
    questions: tuple[Question, ...]
    tiers: tuple[TierBand, ...] = ()
    version: str = "1.0"
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def questions_for(self, dimension: str) -> list[Question]:
        return [q for q in self.questions if q.dimension == dimension]

    def question(self, question_id: str) -> Question | None:
        return next((q for q in self.questions if q.id == question_id), None)

    def tier_for(self, score: float) -> str:
        for band in self.tiers:
            if band.contains(score):
                return band.name
        return ""

    def validate(self) -> list[str]:
        problems: list[str] = []
        seen: set[str] = set()
        for question in self.questions:
            if question.id in seen:
                problems.append(f"Duplicate question id {question.id!r}")
            seen.add(question.id)
            if question.dimension not in self.dimensions:
                problems.append(
                    f"Question {question.id!r} names dimension {question.dimension!r}, "
                    "which is not declared"
                )
            if question.type in {"single_choice", "multi_select"} and not question.options:
                problems.append(f"Question {question.id!r} is {question.type} but has no options")
            for option in question.options:
                if not option.excluded and not 0.0 <= option.score <= 1.0:
                    problems.append(
                        f"Option {option.value!r} on {question.id!r} scores {option.score}, "
                        "outside 0..1"
                    )
            if question.type == "scale" and question.scale_max <= question.scale_min:
                problems.append(f"Question {question.id!r} has an empty scale range")
        for dimension in self.dimensions:
            if not self.questions_for(dimension):
                problems.append(f"Dimension {dimension!r} has no questions")
        return problems

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Instrument:
        try:
            instrument = cls(
                id=data["id"],
                name=data["name"],
                version=data.get("version", "1.0"),
                description=data.get("description", ""),
                dimensions=tuple(data["dimensions"]),
                questions=tuple(_question(q) for q in data["questions"]),
                tiers=tuple(
                    TierBand(t["name"], float(t["min_score"]), float(t["max_score"]))
                    for t in data.get("tiers", [])
                ),
                metadata=data.get("metadata", {}) or {},
            )
        except KeyError as exc:
            raise InvalidRequest(f"Instrument is missing required field {exc}") from None

        problems = instrument.validate()
        if problems:
            raise InvalidRequest("Invalid instrument: " + "; ".join(problems))
        return instrument

    @classmethod
    def from_json(cls, path: str | Path) -> Instrument:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "dimensions": list(self.dimensions),
            "tiers": [
                {"name": t.name, "min_score": t.min_score, "max_score": t.max_score}
                for t in self.tiers
            ],
            "questions": [
                {
                    "id": q.id,
                    "dimension": q.dimension,
                    "type": q.type,
                    "text": q.text,
                    "weight": q.weight,
                    "scale_min": q.scale_min,
                    "scale_max": q.scale_max,
                    "options": [
                        {"value": o.value, "score": o.score, "excluded": o.excluded}
                        for o in q.options
                    ],
                }
                for q in self.questions
            ],
            "metadata": self.metadata,
        }


def _question(data: dict[str, Any]) -> Question:
    return Question(
        id=data["id"],
        dimension=data["dimension"],
        type=data.get("type", "single_choice"),
        text=data.get("text", ""),
        weight=float(data.get("weight", 1.0)),
        scale_min=float(data.get("scale_min", 0.0)),
        scale_max=float(data.get("scale_max", 1.0)),
        options=tuple(
            Option(
                value=o["value"],
                score=float(o.get("score", 0.0)),
                excluded=bool(o.get("excluded", False)),
            )
            for o in data.get("options", [])
        ),
    )


def example_instrument() -> Instrument:
    """A deliberately small demonstration instrument.

    Six questions across two dimensions, with placeholder tier names. It exists so
    the engine and the API have something to run against. It is not a real
    readiness index and should not be used as one.
    """
    path = Path(__file__).parent / "instruments" / "example.json"
    return Instrument.from_json(path)


__all__ = ["Instrument", "Option", "Question", "TierBand", "example_instrument"]
