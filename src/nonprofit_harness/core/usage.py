"""What a run consumed.

Deliberately a leaf module that imports nothing from this package. Providers,
guardrails, and core all need it, so if it lived alongside the richer core types it
would drag them into every low-level module and close an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    #: The cost of the priced calls only. When `unpriced_calls` is above zero this is a
    #: lower bound, not the bill, so never show it alone as the run's cost.
    cost_usd: float = 0.0
    calls: int = 0
    #: Calls on a model the price book had no rate for. Counted rather than costed at
    #: zero, because a zero that means "unknown" reads as "free" in a grant report.
    unpriced_calls: int = 0
    unpriced_models: tuple[str, ...] = ()

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_known(self) -> bool:
        return self.unpriced_calls == 0

    def add(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=round(self.cost_usd + other.cost_usd, 8),
            calls=self.calls + other.calls,
            unpriced_calls=self.unpriced_calls + other.unpriced_calls,
            unpriced_models=self.unpriced_models
            + tuple(m for m in other.unpriced_models if m not in self.unpriced_models),
        )

    def describe_cost(self) -> str:
        """The cost as a person should read it: a figure only when every call was priced."""
        if self.cost_known:
            return f"${self.cost_usd:.4f}"
        models = ", ".join(self.unpriced_models) or "an unpriced model"
        priced = f"; ${self.cost_usd:.4f} from priced calls" if self.cost_usd else ""
        return f"cost: unknown (no price for {models}{priced})"


__all__ = ["Usage"]
