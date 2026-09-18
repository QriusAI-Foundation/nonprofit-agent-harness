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
    cost_usd: float = 0.0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=round(self.cost_usd + other.cost_usd, 8),
            calls=self.calls + other.calls,
        )


__all__ = ["Usage"]
