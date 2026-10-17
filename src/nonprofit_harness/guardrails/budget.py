"""Per-run ceilings on calls, tokens, and dollars.

Three separate mechanisms, because each covers a gap the others leave:

1. The call-count check before dispatch (`BudgetGuard.admit`). A call that would
   exceed `max_calls` is never sent.
2. Conservative reservations before dispatch (`BudgetGuard.reserve`). The output limit
   sent to the provider is capped to what the token and dollar allowance has left, and a
   prompt whose estimated size already fills the allowance is not sent.
3. Post-response accounting (`BudgetGuard.record`), the accounting of record. What the
   provider reports is added first and checked second, so spend that broke a ceiling is
   still on the books.

Reservations narrow the overshoot; they cannot close it. The input size is an estimate,
so one call can still pass a ceiling by the amount its real input exceeds the estimate.
The provider's own report decides what is recorded, never the estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nonprofit_harness.core.errors import BudgetExceeded, ProviderError
from nonprofit_harness.core.usage import Usage
from nonprofit_harness.providers.base import ModelProvider, ModelRate, ModelResponse, how_to_price

#: Characters per token for the pre-dispatch input estimate. Ordinary English runs near
#: four, so dividing by six underestimates on purpose: the reservation should refuse a
#: prompt only when it almost certainly does not fit. It is an estimate, not a count.
CHARS_PER_TOKEN_ESTIMATE = 6

#: When neither the caller nor the provider states an output limit, the model's own
#: maximum applies, and some APIs answer a larger one with HTTP 400. Every current
#: model accepts this many, so a reservation below it is sent; above it, the limit is
#: left to the model and the overshoot is bounded by that model's maximum instead.
UNSTATED_OUTPUT_LIMIT = 8192


def estimate_input_tokens(prompt: str, system: str | None = None) -> int:
    """A deliberately low estimate of the prompt's tokens. See CHARS_PER_TOKEN_ESTIMATE."""
    return (len(prompt) + len(system or "")) // CHARS_PER_TOKEN_ESTIMATE


class UnpricedModel(BudgetExceeded):
    """A dollar ceiling is in force on a model with no price.

    Refused rather than costed at zero: a ceiling that sees zero spend never trips, so
    allowing the call would look like protection and be none.
    """

    def __init__(self, models: tuple[str, ...], ceiling: float) -> None:
        named = ", ".join(models)
        # A note can carry "(requested ...)"; the fix needs the bare model name.
        first = models[0].split(" (", 1)[0] if models else "<model>"
        super().__init__(
            0.0,
            ceiling,
            "cost",
            message=f"A ${ceiling:.4f} cost ceiling is set but there is no price for "
            f"{named}, so its spend cannot be measured. {how_to_price(first)}",
        )
        self.models = models


class ReservationRefused(BudgetExceeded):
    """The estimated input alone leaves no room under a ceiling, so nothing was sent."""

    def __init__(self, kind: str, estimate: float, remaining: float, ceiling: float) -> None:
        if kind == "cost":
            detail = (
                f"the estimated input costs ${estimate:.4f} with ${remaining:.4f} "
                f"of ${ceiling:.4f} left"
            )
        else:
            detail = (
                f"an estimated {estimate:,.0f} input tokens (prompt characters / "
                f"{CHARS_PER_TOKEN_ESTIMATE}) with {remaining:,.0f} of {ceiling:,.0f} left"
            )
        super().__init__(
            estimate, ceiling, kind, message=f"Run would exceed its {kind} ceiling: {detail}"
        )


class BudgetCutOff(BudgetExceeded):
    """A response used every output token the budget had left, so it was cut short."""

    def __init__(self, cap: int) -> None:
        super().__init__(
            float(cap),
            float(cap),
            "token",
            message=f"The response was cut off at the {cap:,} output tokens the budget had "
            "left, so it is incomplete. Its usage is recorded",
        )


def _cut_off_by_budget(stated: int | None, cap: int | None, usage: Usage) -> bool:
    lowered = cap is not None and (stated is None or cap < stated)
    return lowered and usage.output_tokens >= (cap or 0)


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
        if self.max_cost_usd is not None and after.unpriced_calls:
            raise UnpricedModel(after.unpriced_models, self.max_cost_usd)
        if self.max_cost_usd is not None and after.cost_usd > self.max_cost_usd:
            raise BudgetExceeded(after.cost_usd, self.max_cost_usd, "cost")
        if self.max_tokens is not None:
            total = after.input_tokens + after.output_tokens
            if total > self.max_tokens:
                raise BudgetExceeded(float(total), float(self.max_tokens), "token")
        if self.max_calls is not None and after.calls > self.max_calls:
            raise BudgetExceeded(float(after.calls), float(self.max_calls), "call")

    def admit(self) -> None:
        """The call-count check before dispatch.

        Also re-checks every other ceiling against what is already spent, so an agent
        that caught a BudgetExceeded and tried again is still refused.
        """
        self.check(Usage(calls=1))

    def reserve(
        self,
        *,
        estimated_input_tokens: int,
        max_output_tokens: int | None,
        rate: ModelRate | None = None,
    ) -> int | None:
        """Reserve room for one call and return the output limit to send.

        Returns `max_output_tokens` lowered to what the token allowance, and the dollar
        allowance when the model's rate is known, has left after the estimated input.
        Refuses when that leaves nothing.
        """
        cap = max_output_tokens
        if self.max_tokens is not None:
            remaining = self.max_tokens - self.total_tokens
            room = remaining - estimated_input_tokens
            if room <= 0:
                raise ReservationRefused(
                    "token", estimated_input_tokens, max(0, remaining), self.max_tokens
                )
            cap = room if cap is None else min(cap, room)
        if self.max_cost_usd is not None and rate is not None:
            cap = self._reserve_dollars(estimated_input_tokens, rate, cap)
        return cap

    def _reserve_dollars(
        self, estimated_input_tokens: int, rate: ModelRate, cap: int | None
    ) -> int | None:
        remaining = self.remaining_usd() or 0.0
        input_cost = rate.cost(estimated_input_tokens, 0)
        affordable = None
        if rate.output_per_1m > 0:
            affordable = int((remaining - input_cost) / rate.output_per_1m * 1_000_000)
        if input_cost >= remaining or (affordable is not None and affordable <= 0):
            raise ReservationRefused("cost", input_cost, remaining, self.max_cost_usd or 0.0)
        if affordable is None:
            return cap
        return affordable if cap is None else min(cap, affordable)

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
        self.guard.admit()
        rate = self._rate_for(model or self._inner.default_model)
        stated = max_output_tokens or getattr(self._inner, "default_max_output_tokens", None)
        cap = self._output_limit(prompt, system, stated, rate)
        try:
            response = self._inner.generate(
                prompt,
                system=system,
                model=model,
                temperature=temperature,
                max_output_tokens=cap,
                json_schema=json_schema,
            )
        except ProviderError as exc:
            # A refused or truncated call can still be billed. Banked before the error
            # moves on, so the run's spend matches the invoice. If banking it breaks a
            # ceiling, that error wins, with this one attached as its context.
            if exc.usage is not None:
                self.guard.record(exc.usage)
            raise
        self.guard.record(response.usage)
        if _cut_off_by_budget(stated, cap, response.usage):
            # The answer stopped at the limit the budget imposed, so it is incomplete.
            # Handing it back would let a fragment reach an artifact as a full answer.
            raise BudgetCutOff(cap or 0)
        return response

    def _rate_for(self, model: str) -> ModelRate | None:
        """The rate the dollar reservation needs, refusing an unpriced model up front.

        A provider with no `prices` attribute makes no claim either way (the offline
        echo provider is free). Its response's own usage says whether the call was
        priced, and `record` refuses after the fact if it was not.
        """
        prices = getattr(self._inner, "prices", None)
        if self.guard.max_cost_usd is None or prices is None or not model:
            return None
        rate = prices.rate_for(model)
        if rate is None:
            raise UnpricedModel((model,), self.guard.max_cost_usd)
        return rate

    def _output_limit(
        self,
        prompt: str,
        system: str | None,
        stated: int | None,
        rate: ModelRate | None,
    ) -> int | None:
        cap = self.guard.reserve(
            estimated_input_tokens=estimate_input_tokens(prompt, system),
            max_output_tokens=stated,
            rate=rate,
        )
        if stated is None and cap is not None and cap >= UNSTATED_OUTPUT_LIMIT:
            return None
        return cap


__all__ = [
    "CHARS_PER_TOKEN_ESTIMATE",
    "UNSTATED_OUTPUT_LIMIT",
    "BudgetCutOff",
    "BudgetGuard",
    "BudgetedProvider",
    "ReservationRefused",
    "UnpricedModel",
    "estimate_input_tokens",
]
