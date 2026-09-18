from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nonprofit_harness.core.errors import BudgetExceeded
from nonprofit_harness.core.types import Usage
from nonprofit_harness.providers.base import ModelProvider, ModelResponse


@dataclass
class BudgetGuard:
    """A hard ceiling on what one run may consume.

    Three independent limits, because the useful one depends on what you know.
    Token and call ceilings work with no pricing configured at all, which matters
    for a first-time user who has not set up a price book yet.
    """

    max_cost_usd: float | None = None
    max_tokens: int | None = None
    max_calls: int | None = None
    spent: Usage = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.spent is None:
            self.spent = Usage()

    @property
    def total_tokens(self) -> int:
        return self.spent.input_tokens + self.spent.output_tokens

    def check(self, projected: Usage) -> None:
        after = self.spent.add(projected)
        if self.max_cost_usd is not None and after.cost_usd > self.max_cost_usd:
            raise BudgetExceeded(after.cost_usd, self.max_cost_usd, "cost")
        if self.max_tokens is not None:
            total = after.input_tokens + after.output_tokens
            if total > self.max_tokens:
                raise BudgetExceeded(float(total), float(self.max_tokens), "token")
        if self.max_calls is not None and after.calls > self.max_calls:
            raise BudgetExceeded(float(after.calls), float(self.max_calls), "call")

    def record(self, usage: Usage) -> None:
        """Bank what was actually consumed, then stop the run if that broke a ceiling.

        Deliberately add-then-check rather than check-then-add. The call already
        happened and the money is already gone, so refusing to count it would make
        the harness report less spend than the invoice shows.
        """
        self.spent = self.spent.add(usage)
        self.check(Usage())

    def remaining_usd(self) -> float | None:
        if self.max_cost_usd is None:
            return None
        return max(0.0, round(self.max_cost_usd - self.spent.cost_usd, 8))


class BudgetedProvider:
    """Wraps a provider so every call is metered against a guard.

    The agent sees an ordinary provider. It cannot opt out of the ceiling, because
    the ceiling lives on this side of the seam rather than inside agent code.
    """

    def __init__(self, inner: ModelProvider, guard: BudgetGuard) -> None:
        self._inner = inner
        self.guard = guard

    @property
    def name(self) -> str:
        return getattr(self._inner, "name", "wrapped")

    @property
    def default_model(self) -> str:
        return self._inner.default_model

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> ModelResponse:
        # Refuse on the call count before spending anything, so an exhausted
        # budget fails fast instead of paying for one more response first.
        self.guard.check(Usage(calls=1))
        response = self._inner.generate(
            prompt,
            system=system,
            model=model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            json_schema=json_schema,
        )
        self.guard.record(response.usage)
        return response


__all__ = ["BudgetGuard", "BudgetedProvider"]
