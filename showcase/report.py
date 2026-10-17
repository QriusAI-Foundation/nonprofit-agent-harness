"""Build the showcase tables from the committed receipts. Offline, no model calls.

    python -m showcase.report > showcase/TABLES.md

Every number comes from a receipt the harness wrote for a run. Nothing here judges
quality: the outcome columns are the free citation check's verdicts, and the quality
judgement is the human review each artifact is still waiting for.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from showcase import harness_setup as setup

RUNS = setup.HERE / "runs"
MODELS = ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5")


def receipts(folder: Path = RUNS) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(folder.rglob("*.receipt.json"))]


def outcome_counts(receipt: dict) -> Counter:
    counts: Counter = Counter()
    for claim in receipt["claims"]:
        outcome = claim["outcome"] or "unchecked"
        if outcome == "verified" and claim.get("match"):
            outcome = f"verified ({claim['match']})"
        counts[outcome] += 1
    return counts


def model_table(rows: list[dict]) -> list[str]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for receipt in rows:
        groups[(receipt["agent"], receipt["model"])].append(receipt)
    names = sorted({name for r in rows for name in outcome_counts(r)})
    header = ["Agent", "Model", "Runs", "Input tokens", "Output tokens", "Cost (USD)",
              "Claims", *names, "Empty outputs"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for agent in sorted({key[0] for key in groups}):
        for model in MODELS:
            group = groups.get((agent, model))
            if not group:
                continue
            counts = sum((outcome_counts(r) for r in group), Counter())
            empty = sum(1 for r in group if not r["claims"])
            lines.append(
                "| "
                + " | ".join(
                    [
                        agent,
                        model,
                        str(len(group)),
                        f"{sum(r['usage']['input_tokens'] for r in group):,}",
                        f"{sum(r['usage']['output_tokens'] for r in group):,}",
                        f"{sum(r['usage']['cost_usd'] for r in group):.4f}",
                        str(sum(counts.values())),
                        *(str(counts.get(name, 0)) for name in names),
                        str(empty),
                    ]
                )
                + " |"
            )
    return lines


def run_table(rows: list[dict]) -> list[str]:
    lines = [
        "| Agent | Source | Model | Run | Input | Output | USD | Seconds | Verification |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in sorted(rows, key=lambda r: (r["agent"], r["source"], r["model"], r["repeat"])):
        lines.append(
            f"| {r['agent']} | {r['source']} | {r['model']} | {r['repeat']} | "
            f"{r['usage']['input_tokens']:,} | {r['usage']['output_tokens']:,} | "
            f"{r['usage']['cost_usd']:.4f} | {r['seconds']} | "
            f"{r['verification'] or 'no claims returned'} |"
        )
    return lines


def quorum_table() -> list[str]:
    lines = [
        "| Label | Agent | Source | Calls | USD | Outcomes | Votes by reviewer |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for path in sorted((setup.HERE / "quorum").glob("*.json")):
        q = json.loads(path.read_text())
        by_model: dict[str, Counter] = defaultdict(Counter)
        for verdict in q["verdicts"]:
            for index, vote in enumerate(verdict["votes"]):
                by_model[q["reviewers"][index % len(q["reviewers"])]][vote] += 1
        votes = "; ".join(
            f"{model.removeprefix('claude-')}: "
            + ", ".join(f"{v} {n}" for v, n in sorted(c.items()))
            for model, c in by_model.items()
        )
        outcomes = ", ".join(f"{k} {v}" for k, v in sorted(q["outcomes"].items()))
        lines.append(
            f"| {q['label']} | {q['agent']} | {q['source']} | {q['usage']['calls']} | "
            f"{q['usage']['cost_usd']:.4f} | {outcomes} | {votes} |"
        )
    return lines


def budget_table() -> list[str]:
    lines = [
        "| Case | Model | Limits | Status | Calls | Tokens | USD recorded | Artifact kept "
        "| Error |",
        "|---|---|---|---|---:|---:|---:|---|---|",
    ]
    for path in sorted((setup.HERE / "budget").glob("*.json")):
        b = json.loads(path.read_text())
        limits = {k: v for k, v in b["limits"].items() if k != "verify_models"}
        tokens = b["usage"]["input_tokens"] + b["usage"]["output_tokens"]
        lines.append(
            f"| {b['case']} | {b['model']} | `{json.dumps(limits)}` | {b['status']} | "
            f"{b['usage']['calls']} | {tokens:,} | {b['usage']['cost_usd']:.4f} | "
            f"{b['artifact_kept']} | {(b['error'] or b['verification'] or '')[:140]} |"
        )
    return lines


def main() -> int:
    rows = receipts()
    out = [
        "# Showcase tables",
        "",
        "Generated by `python -m showcase.report` from the receipts. Do not edit by hand.",
        "",
        "## By agent and model",
        "",
        *model_table(rows),
        "",
        "## Every run",
        "",
        *run_table(rows),
        "",
        "## Cross-model quorum",
        "",
        *quorum_table(),
        "",
        "## Budget ceilings",
        "",
        *budget_table(),
        "",
    ]
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
