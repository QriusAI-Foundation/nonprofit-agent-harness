from __future__ import annotations

import pytest

from nonprofit_harness.core.errors import BudgetExceeded
from nonprofit_harness.core.types import RunStatus, Usage
from nonprofit_harness.guardrails.budget import BudgetedProvider, BudgetGuard
from nonprofit_harness.providers.base import PriceBook
from nonprofit_harness.providers.echo import EchoProvider


def test_call_ceiling_stops_a_runaway_agent(runner, documents):
    runner.config.max_calls = 5
    run = runner.start("chatty", org_id="org_1", inputs=documents)

    assert run.status == RunStatus.FAILED
    assert "budget ceiling" in run.error
    assert run.usage.calls <= 5


def test_token_ceiling_works_without_any_pricing_configured(runner, documents):
    runner.config.max_calls = None
    runner.config.max_tokens = 50
    run = runner.start("chatty", org_id="org_1", inputs=documents)

    assert run.status == RunStatus.FAILED
    # The breaching call is still counted, so the recorded total may sit just past
    # the ceiling. What matters is that it stopped instead of running all 20 calls.
    assert run.usage.calls < 20
    assert run.usage.input_tokens + run.usage.output_tokens > 0


def test_cost_ceiling_uses_the_price_book():
    prices = PriceBook().set("echo-1", input_per_1m=1000.0, output_per_1m=1000.0)
    guard = BudgetGuard(max_cost_usd=0.001)

    class PricedEcho(EchoProvider):
        def generate(self, prompt, **kwargs):
            response = super().generate(prompt, **kwargs)
            usage = response.usage
            usage.cost_usd = prices.cost(response.model, usage.input_tokens, usage.output_tokens)
            return response

    provider = BudgetedProvider(PricedEcho(), guard)
    with pytest.raises(BudgetExceeded):
        for _ in range(50):
            provider.generate("a reasonably long prompt " * 20)

    # Spend from the breaching call is banked rather than discarded.
    assert guard.spent.cost_usd > 0
    assert guard.remaining_usd() == 0.0


def test_agent_level_budget_overrides_the_deployment_default(runner, documents):
    runner.config.max_cost_usd = 100.0
    agent = runner.registry.get("note")
    agent.__class__.budget_usd = 0.5

    guard = runner._guard_for(agent)
    assert guard.max_cost_usd == 0.5

    agent.__class__.budget_usd = None


def test_guard_reports_what_is_left():
    guard = BudgetGuard(max_cost_usd=1.0)
    guard.record(Usage(cost_usd=0.25, calls=1))

    assert guard.remaining_usd() == 0.75
    assert BudgetGuard().remaining_usd() is None


def test_guard_refuses_before_spending_when_calls_are_exhausted():
    guard = BudgetGuard(max_calls=1)
    provider = BudgetedProvider(EchoProvider(), guard)

    provider.generate("first")
    with pytest.raises(BudgetExceeded):
        provider.generate("second")

    assert guard.spent.calls == 1
