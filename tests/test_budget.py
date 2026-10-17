from __future__ import annotations

import os

import pytest

from nonprofit_harness import cli
from nonprofit_harness.config import HarnessConfig
from nonprofit_harness.core.errors import BudgetExceeded, ProviderError
from nonprofit_harness.core.runner import AgentRunner
from nonprofit_harness.core.types import Document, Run, RunStatus, Usage
from nonprofit_harness.guardrails.budget import (
    BudgetCutOff,
    BudgetedProvider,
    BudgetGuard,
    ReservationRefused,
    UnpricedModel,
)
from nonprofit_harness.providers.base import ModelRate, ModelResponse, PriceBook
from nonprofit_harness.providers.echo import EchoProvider
from nonprofit_harness.providers.openai_compatible import OpenAIProvider
from nonprofit_harness.storage.serde import run_from_dict, run_to_dict


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


# --- F04: the three parts of the budget contract -------------------------------------


class MeteredFake:
    """A provider that reports whatever usage a test hands it and records what was sent."""

    name = "fake"
    default_model = "fake-1"

    def __init__(
        self,
        usage: Usage | None = None,
        *,
        answered: str | None = None,
        prices: PriceBook | None = None,
        default_max_output_tokens: int | None = None,
        error: Exception | None = None,
    ) -> None:
        self.usage = usage or Usage(input_tokens=10, output_tokens=10, calls=1)
        self.answered = answered
        self.prices = prices
        self.default_max_output_tokens = default_max_output_tokens
        self.error = error
        self.sent: list[dict] = []

    def generate(self, prompt, *, system=None, model=None, max_output_tokens=None, **_):
        self.sent.append({"prompt": prompt, "model": model, "max_output_tokens": max_output_tokens})
        if self.error is not None:
            raise self.error
        used = self.answered or model or self.default_model
        return ModelResponse(text="ok", model=used, usage=self.usage)


def test_an_exhausted_call_allowance_prevents_dispatch():
    inner = MeteredFake()
    guard = BudgetGuard(max_calls=2, spent=Usage(calls=2))

    with pytest.raises(BudgetExceeded, match="call ceiling"):
        BudgetedProvider(inner, guard).generate("one more")

    assert inner.sent == []


def test_a_response_that_overshoots_is_fully_recorded():
    inner = MeteredFake(Usage(input_tokens=40, output_tokens=900, calls=1))
    guard = BudgetGuard(max_tokens=100)

    with pytest.raises(BudgetExceeded, match="token ceiling"):
        BudgetedProvider(inner, guard).generate("short")

    # Add-then-check: every token the provider reported is on the books, not just the
    # part that fitted under the ceiling.
    assert guard.spent.total_tokens == 940
    assert guard.spent.calls == 1


def test_the_output_cap_respects_the_remaining_allowance():
    inner = MeteredFake(default_max_output_tokens=4096)
    guard = BudgetGuard(max_tokens=1000, spent=Usage(input_tokens=500, output_tokens=300))
    prompt = "x" * 60  # estimated at 10 tokens

    BudgetedProvider(inner, guard).generate(prompt)

    assert inner.sent[0]["max_output_tokens"] == 1000 - 800 - 10


def test_a_smaller_requested_output_limit_is_kept():
    inner = MeteredFake(default_max_output_tokens=4096)
    BudgetedProvider(inner, BudgetGuard(max_tokens=10_000)).generate("x", max_output_tokens=50)

    assert inner.sent[0]["max_output_tokens"] == 50


def test_the_output_cap_respects_the_remaining_dollars():
    prices = PriceBook().set("fake-1", input_per_1m=0.0, output_per_1m=10.0)
    inner = MeteredFake(Usage(calls=1), prices=prices, default_max_output_tokens=4096)
    guard = BudgetGuard(max_cost_usd=0.01)

    BudgetedProvider(inner, guard).generate("x")

    # $0.01 at $10 per million output tokens buys 1,000 of them.
    assert inner.sent[0]["max_output_tokens"] == 1000


def test_an_unstated_output_limit_is_left_to_the_model_when_room_is_large():
    # Sending a 200k limit to a model whose maximum is 64k is an HTTP 400, not a cap.
    inner = MeteredFake()
    BudgetedProvider(inner, BudgetGuard(max_tokens=200_000)).generate("x")

    assert inner.sent[0]["max_output_tokens"] is None


def test_an_unstated_output_limit_is_capped_when_room_is_small():
    inner = MeteredFake()
    BudgetedProvider(inner, BudgetGuard(max_tokens=500)).generate("x")

    assert inner.sent[0]["max_output_tokens"] == 500


def test_an_input_estimated_past_the_remaining_tokens_is_not_sent():
    inner = MeteredFake()
    guard = BudgetGuard(max_tokens=1000, spent=Usage(input_tokens=900))

    with pytest.raises(ReservationRefused, match="estimated .* input tokens"):
        BudgetedProvider(inner, guard).generate("x" * 6 * 200)

    assert inner.sent == []
    assert guard.spent.calls == 0


def test_a_dollar_ceiling_with_an_unpriced_model_refuses_dispatch():
    inner = MeteredFake(prices=PriceBook())
    guard = BudgetGuard(max_cost_usd=5.0)

    with pytest.raises(UnpricedModel) as caught:
        BudgetedProvider(inner, guard).generate("x", model="claude-haiku-5-5")

    message = str(caught.value)
    assert "no price for claude-haiku-5-5" in message
    assert "HARNESS_PRICES='claude-haiku-5-5=<input>/<output>'" in message
    assert inner.sent == []


def test_a_returned_model_that_differs_from_the_priced_one_does_not_cost_zero():
    prices = PriceBook().set("model-x", input_per_1m=1.0, output_per_1m=1.0)

    usage = prices.usage("model-x-2026-10-01", 1000, 1000, requested="model-x")

    assert usage.cost_known is False
    assert usage.unpriced_models == ("model-x-2026-10-01 (requested model-x, which is priced)",)


def test_a_returned_model_change_under_a_dollar_ceiling_stops_the_run_with_spend_banked():
    prices = PriceBook().set("model-x", input_per_1m=1.0, output_per_1m=1.0)
    unpriced = prices.usage("model-x-fallback", 100, 100, requested="model-x")
    inner = MeteredFake(unpriced, prices=prices, answered="model-x-fallback")
    guard = BudgetGuard(max_cost_usd=5.0)

    with pytest.raises(UnpricedModel, match="model-x-fallback"):
        BudgetedProvider(inner, guard).generate("x", model="model-x")

    assert guard.spent.unpriced_calls == 1
    assert guard.spent.total_tokens == 200


def test_a_dollar_ceiling_still_runs_on_the_free_offline_provider():
    guard = BudgetGuard(max_cost_usd=0.01)
    BudgetedProvider(EchoProvider(), guard).generate("x")

    assert guard.spent.calls == 1
    assert guard.spent.cost_known


def test_a_refusals_billed_usage_is_banked():
    billed = Usage(input_tokens=120, output_tokens=45, calls=1)
    inner = MeteredFake(error=ProviderError("Model refused the request", usage=billed))
    guard = BudgetGuard(max_tokens=10_000)

    with pytest.raises(ProviderError, match="refused"):
        BudgetedProvider(inner, guard).generate("x")

    assert guard.spent.calls == 1
    assert guard.spent.total_tokens == 165


def test_a_refusals_billed_usage_reaches_the_failed_run(registry, stores, config):
    billed = Usage(input_tokens=120, output_tokens=45, calls=1)
    provider = MeteredFake(error=ProviderError("Model refused the request", usage=billed))
    runner = AgentRunner(registry=registry, stores=stores, provider=provider, config=config)

    run = runner.start("note", org_id="org_1", inputs=[Document(text="x", name="a.txt")])

    assert run.status == RunStatus.FAILED
    assert run.usage.output_tokens == 45


def test_an_unknown_cost_is_never_shown_as_zero():
    usage = Usage(calls=2, cost_usd=0.5).add(
        PriceBook().usage("mystery-model", 10, 10)
    )

    assert usage.describe_cost() == (
        "cost: unknown (no price for mystery-model; $0.5000 from priced calls)"
    )
    assert Usage(calls=1, cost_usd=0.25).describe_cost() == "$0.2500"


def test_the_cli_prints_unknown_cost_rather_than_zero(monkeypatch, tmp_path, capsys):
    for key in [k for k in os.environ if k.startswith("HARNESS_")]:
        monkeypatch.delenv(key)
    unpriced = PriceBook().usage("mystery-model", 50, 20)
    monkeypatch.setattr(cli, "load_provider", lambda *_: MeteredFake(unpriced))
    brief = tmp_path / "brief.txt"
    brief.write_text("A short programme brief.\n")

    assert cli.main(["run", "examples.summarizer:SummarizerAgent", str(brief)]) == 0

    out = capsys.readouterr().out
    assert "cost: unknown (no price for mystery-model)" in out
    assert "$0.0000" not in out


def test_validate_warns_on_a_dollar_ceiling_without_prices():
    problems = HarnessConfig(max_cost_usd=1.0).validate()

    assert any("HARNESS_PRICES is not" in problem for problem in problems)
    assert not any("HARNESS_PRICES" in p for p in HarnessConfig(max_cost_usd=None).validate())


def test_validate_warns_when_the_configured_model_has_no_price():
    config = HarnessConfig(max_cost_usd=1.0, model="model-y", prices="model-x=1/2")

    assert any("no price for model-y" in problem for problem in config.validate())


def test_validate_reports_a_malformed_price_entry():
    problems = HarnessConfig(prices="model-x=1.0").validate()

    assert any("is not model=input/output" in problem for problem in problems)


def test_prices_parse_model_names_that_carry_slashes_and_colons():
    book = PriceBook.parse("meta-llama/llama-4=0.10/0.30, llama3:8b=0/0")

    assert book.rate_for("meta-llama/llama-4") == ModelRate(0.10, 0.30)
    assert book.knows("llama3:8b")


def test_providers_read_prices_from_the_environment(monkeypatch):
    monkeypatch.setenv("HARNESS_PRICES", "gpt-test=1000/2000")
    provider = OpenAIProvider(model="gpt-test", api_key="sk-test-key-value", client=object())

    assert provider.prices.knows("gpt-test")


def test_unpriced_usage_survives_storage():
    run = Run(agent="note", org_id="org_1")
    run.usage = PriceBook().usage("mystery-model", 1, 1)

    restored = run_from_dict(run_to_dict(run))

    assert restored.usage.unpriced_calls == 1
    assert restored.usage.unpriced_models == ("mystery-model",)


def test_an_answer_cut_short_by_the_budget_cap_stops_the_run():
    # Input estimated at 100 tokens, so 900 are reserved for output; all 900 come back,
    # which lands exactly on the ceiling and so would not trip the after-call check.
    inner = MeteredFake(Usage(input_tokens=100, output_tokens=900, calls=1))
    guard = BudgetGuard(max_tokens=1000)

    with pytest.raises(BudgetCutOff, match="cut off at the 900 output tokens"):
        BudgetedProvider(inner, guard).generate("x" * 600)

    assert guard.spent.total_tokens == 1000


def test_an_answer_at_the_agents_own_limit_is_not_a_budget_cut():
    inner = MeteredFake(Usage(input_tokens=5, output_tokens=50, calls=1))

    response = BudgetedProvider(inner, BudgetGuard(max_tokens=10_000)).generate(
        "x", max_output_tokens=50
    )

    assert response.text == "ok"
