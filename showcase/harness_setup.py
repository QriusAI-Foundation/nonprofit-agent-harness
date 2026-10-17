"""What a deployer wires up around the harness for the showcase runs.

Everything here is deployment code, not package code: the dated price book, the Claude
provider, the ceilings, and a ledger that records each run's own usage accounting. Every
model call in the showcase goes through `AgentRunner` and the budget guard, so the
receipts are the harness's numbers, not a separate tally.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nonprofit_harness.config import HarnessConfig
from nonprofit_harness.core.registry import AgentRegistry
from nonprofit_harness.core.runner import AgentRunner
from nonprofit_harness.core.types import Run
from nonprofit_harness.providers.anthropic import AnthropicProvider
from nonprofit_harness.providers.base import PriceBook
from nonprofit_harness.storage.memory import memory_stores

HERE = Path(__file__).resolve().parent
PRICE_FILE = HERE / "prices-2026-10-17.json"
LEDGER = HERE / "ledger.jsonl"
SPEND = HERE / "SPEND.md"

#: Stop starting new work once the ledger reaches this. The credit is USD 100 and the
#: plan keeps a margin under it.
SPEND_CAP_USD = 95.0

#: Whole training manuals run to 230,000 tokens, past the harness's 200,000 default.
#: Raised here as the deployer's decision, with the cost ceiling still in force.
MAX_TOKENS_PER_RUN = 600_000

#: Long documents on Opus take minutes, well past the provider's 60 second default.
TIMEOUT_SECONDS = 900.0


@dataclass
class TieredPriceBook(PriceBook):
    """A price book that knows one model charges more for long prompts.

    The package's `PriceBook` is flat, which is right for a default. Haiku 5.5 bills a
    whole request at a higher rate once its input passes a threshold, and a flat rate
    would under-report exactly the long-document runs this showcase makes.
    """

    long_prompt: dict[str, tuple[int, float, float]] = field(default_factory=dict)

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        tier = self.long_prompt.get(model)
        if tier and input_tokens > tier[0]:
            _, input_rate, output_rate = tier
            return round(
                input_tokens / 1_000_000 * input_rate + output_tokens / 1_000_000 * output_rate,
                8,
            )
        return super().cost(model, input_tokens, output_tokens)


def load_prices(path: Path = PRICE_FILE) -> TieredPriceBook:
    data = json.loads(path.read_text(encoding="utf-8"))
    book = TieredPriceBook()
    for model, rate in data["models"].items():
        book.set(model, rate["input"], rate["output"])
        if "long_prompt" in rate:
            tier = rate["long_prompt"]
            book.long_prompt[model] = (tier["above_input_tokens"], tier["input"], tier["output"])
    return book


def provider(model: str, *, effort: str | None = None) -> AnthropicProvider:
    return AnthropicProvider(
        model=model, effort=effort, prices=load_prices(), timeout=TIMEOUT_SECONDS
    )


def runner(agent, model: str, *, effort: str | None = None, **config: Any) -> AgentRunner:
    registry = AgentRegistry()
    registry.register(agent)
    settings = {"max_tokens": MAX_TOKENS_PER_RUN, "max_calls": 50, "max_cost_usd": 5.0}
    settings.update(config)
    return AgentRunner(
        registry=registry,
        stores=memory_stores(),
        provider=provider(model, effort=effort),
        config=HarnessConfig(provider="anthropic", model=model, **settings),
    )


def spent_so_far() -> float:
    return round(sum(entry["cost_usd"] for entry in read_ledger()), 6)


def require_headroom(estimate_usd: float) -> None:
    total = spent_so_far()
    if total + estimate_usd > SPEND_CAP_USD:
        raise SystemExit(
            f"Refusing to start: ledger at ${total:.2f}, this step estimated at "
            f"${estimate_usd:.2f}, cap ${SPEND_CAP_USD:.2f}"
        )


def read_ledger() -> list[dict[str, Any]]:
    if not LEDGER.exists():
        return []
    return [json.loads(line) for line in LEDGER.read_text().splitlines() if line.strip()]


def record(task: str, run: Run, model: str, **extra: Any) -> dict[str, Any]:
    """Append one run's own usage to the ledger and rewrite SPEND.md."""
    entry = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "task": task,
        "run_id": run.id,
        "agent": run.agent,
        "model": model,
        "status": str(run.status),
        "calls": run.usage.calls,
        "input_tokens": run.usage.input_tokens,
        "output_tokens": run.usage.output_tokens,
        "cost_usd": round(run.usage.cost_usd, 6),
        **extra,
    }
    with LEDGER.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(json.dumps(entry) + "\n")
        fcntl.flock(handle, fcntl.LOCK_UN)
    write_spend()
    return entry


def write_spend() -> None:
    entries = read_ledger()
    by_task: dict[str, list[float]] = defaultdict(lambda: [0, 0, 0, 0.0])
    by_model: dict[str, list[float]] = defaultdict(lambda: [0, 0, 0, 0.0])
    for entry in entries:
        for table, key in ((by_task, entry["task"]), (by_model, entry["model"])):
            row = table[key]
            row[0] += 1
            row[1] += entry["input_tokens"]
            row[2] += entry["output_tokens"]
            row[3] += entry["cost_usd"]

    def rows(table: dict[str, list[float]]) -> list[str]:
        return [
            f"| {key} | {int(r[0])} | {int(r[1]):,} | {int(r[2]):,} | {r[3]:.4f} |"
            for key, r in sorted(table.items())
        ]

    header = "| {} | Runs | Input tokens | Output tokens | Cost (USD) |\n|---|---:|---:|---:|---:|"
    total = sum(entry["cost_usd"] for entry in entries)
    SPEND.write_text(
        "\n".join(
            [
                "# Showcase spend",
                "",
                "Generated by `showcase/harness_setup.py` from `ledger.jsonl`. Each row sums the",
                "usage the harness itself recorded on each run (`run.usage`), priced with",
                f"`{PRICE_FILE.name}`. Do not edit by hand.",
                "",
                f"**Total: USD {total:.4f} over {len(entries)} harness runs.**",
                "",
                "## By task",
                "",
                header.format("Task"),
                *rows(by_task),
                "",
                "## By model",
                "",
                header.format("Model"),
                *rows(by_model),
                "",
            ]
        ),
        encoding="utf-8",
    )


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=HERE,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def require_key() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY first (for example: set -a; source .env)")
