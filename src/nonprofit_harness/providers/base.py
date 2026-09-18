from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from nonprofit_harness.core.types import Usage


@dataclass(frozen=True, slots=True)
class ModelResponse:
    text: str
    model: str
    usage: Usage
    raw: Any = None


@dataclass(frozen=True, slots=True)
class ModelRate:
    """Price per one million tokens, in USD."""

    input_per_1m: float
    output_per_1m: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return round(
            (input_tokens / 1_000_000) * self.input_per_1m
            + (output_tokens / 1_000_000) * self.output_per_1m,
            8,
        )


@dataclass
class PriceBook:
    """Model pricing, supplied by the deployer.

    Deliberately empty by default. Published rates move often enough that a
    hardcoded table goes stale silently, and a wrong number here becomes a wrong
    number in somebody's grant report. Unpriced calls cost 0.0 and still count
    against token and call ceilings, so budget control works before any rate is set.
    """

    rates: dict[str, ModelRate] = field(default_factory=dict)

    def set(self, model: str, input_per_1m: float, output_per_1m: float) -> PriceBook:
        self.rates[model] = ModelRate(input_per_1m, output_per_1m)
        return self

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        rate = self.rates.get(model)
        return rate.cost(input_tokens, output_tokens) if rate else 0.0

    def knows(self, model: str) -> bool:
        return model in self.rates


@runtime_checkable
class ModelProvider(Protocol):
    """The one seam every model call goes through.

    Swapping Gemini for another model, or for a local one, means writing one class
    that satisfies this protocol. No agent changes.
    """

    name: str
    default_model: str

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> ModelResponse: ...


__all__ = ["ModelProvider", "ModelRate", "ModelResponse", "PriceBook"]
