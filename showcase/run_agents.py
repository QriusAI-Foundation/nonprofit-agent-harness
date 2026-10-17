"""Run the three cited example agents over the showcase sources, on real Claude models.

    set -a; source .env; set +a
    python -m showcase.run_agents --models claude-opus-5-5 --effort medium

Each run goes through `AgentRunner` with the Anthropic provider and the budget guard.
Outputs land verbatim in `showcase/runs/<agent>/<source>/<model>.md`, with the run's own
accounting beside them in `<model>.receipt.json`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime

from examples.board_brief import BoardBriefAgent
from examples.funder_report import FunderReportAgent
from examples.results_narrative import ResultsNarrativeAgent

from nonprofit_harness import __version__
from nonprofit_harness.core.types import Document, Run
from showcase import harness_setup as setup
from showcase.sources import ALL_DOCUMENTS, document, results_documents

RUNS = setup.HERE / "runs"
AGENTS = {
    BoardBriefAgent.name: BoardBriefAgent,
    FunderReportAgent.name: FunderReportAgent,
    ResultsNarrativeAgent.name: ResultsNarrativeAgent,
}

#: Rough output allowance per run, reasoning included, used only to refuse a step that
#: would cross the spend cap. The ledger records what was actually spent.
OUTPUT_ALLOWANCE_TOKENS = 8_000


@dataclass(frozen=True)
class Job:
    agent: str
    slug: str
    source: Document
    model: str
    repeat: int


def jobs(
    agents: list[str], models: list[str], repeats: int, only: set[str] | None = None
) -> list[Job]:
    manuals = [
        (source.slug, document(source))
        for source in ALL_DOCUMENTS
        if not only or source.slug in only
    ]
    sheets = results_documents()
    planned = []
    for agent in agents:
        inputs = sheets if agent == ResultsNarrativeAgent.name else manuals
        for slug, source in inputs:
            if only and slug not in only:
                continue
            for model in models:
                for repeat in range(1, repeats + 1):
                    planned.append(Job(agent, slug, source, model, repeat))
    return planned


def estimate(job: Job) -> float:
    rates = setup.load_prices()
    return rates.cost(job.model, len(job.source.text) // 4, OUTPUT_ALLOWANCE_TOKENS)


def execute(job: Job, effort: str | None) -> dict:
    agent = AGENTS[job.agent]()
    started = time.monotonic()
    run = setup.runner(agent, job.model, effort=effort).start(
        agent.name, org_id="showcase", inputs=[job.source]
    )
    seconds = round(time.monotonic() - started, 1)
    stem = job.model if job.repeat == 1 else f"{job.model}.r{job.repeat}"
    folder = RUNS / job.agent / job.slug
    folder.mkdir(parents=True, exist_ok=True)
    if run.artifacts:
        (folder / f"{stem}.md").write_text(run.artifacts[0].content, encoding="utf-8")
    receipt = build_receipt(job, run, effort, seconds)
    (folder / f"{stem}.receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    setup.record("agents", run, job.model, source=job.slug, repeat=job.repeat)
    return receipt


def build_receipt(job: Job, run: Run, effort: str | None, seconds: float) -> dict:
    artifact = run.artifacts[0] if run.artifacts else None
    verdicts = {}
    if artifact is not None and artifact.verification is not None:
        verdicts = {v.claim_id: v for v in artifact.verification.verdicts}
    claims = []
    for claim in artifact.claims if artifact else []:
        verdict = verdicts.get(claim.id)
        claims.append(
            {
                "statement": claim.statement,
                "quote": claim.citations[0].text if claim.citations else "",
                "locator": claim.citations[0].locator if claim.citations else "",
                "outcome": str(verdict.outcome) if verdict else None,
                "match": verdict.grounded[0].mode if verdict and verdict.grounded else None,
                "score": verdict.grounded[0].score if verdict and verdict.grounded else None,
                "reason": verdict.reason if verdict else None,
            }
        )
    return {
        "run_id": run.id,
        "date": datetime.now(UTC).date().isoformat(),
        "agent": job.agent,
        "agent_version": run.metadata.get("agent_version"),
        "source": job.slug,
        "source_sha256": hashlib.sha256(job.source.text.encode()).hexdigest(),
        "model": job.model,
        "model_reported": artifact.metadata.get("model") if artifact else None,
        "effort": effort or "model default",
        "repeat": job.repeat,
        "status": str(run.status),
        "error": run.error,
        "review_state": str(artifact.status) if artifact else None,
        "seconds": seconds,
        "usage": {
            "calls": run.usage.calls,
            "input_tokens": run.usage.input_tokens,
            "output_tokens": run.usage.output_tokens,
            "cost_usd": round(run.usage.cost_usd, 6),
        },
        "price_file": setup.PRICE_FILE.name,
        "verification": artifact.verification.summary() if artifact and artifact.verification
        else None,
        "claims": claims,
        "harness_version": __version__,
        "harness_commit": setup.git_commit(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="showcase.run_agents")
    parser.add_argument("--models", default="claude-opus-5-5")
    parser.add_argument("--agents", default=",".join(AGENTS))
    parser.add_argument("--effort", default=None)
    parser.add_argument("--sources", default="", help="comma-separated slugs; all if empty")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    only = set(filter(None, args.sources.split(","))) or None
    planned = jobs(args.agents.split(","), args.models.split(","), args.repeats, only)
    projected = sum(estimate(job) for job in planned)
    print(f"{len(planned)} runs, estimated up to ${projected:.2f}")
    if args.dry_run:
        return 0
    setup.require_key()
    setup.require_headroom(projected)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(execute, job, args.effort): job for job in planned}
        for future in as_completed(futures):
            job = futures[future]
            try:
                r = future.result()
            except Exception as exc:  # noqa: BLE001 - report and keep the others going
                print(f"FAIL {job.agent}/{job.slug}/{job.model}: {exc}", file=sys.stderr)
                continue
            print(
                f"{r['status']:<16} {job.agent}/{job.slug}/{job.model} r{job.repeat}  "
                f"{r['usage']['input_tokens']:>7}+{r['usage']['output_tokens']:<6} "
                f"${r['usage']['cost_usd']:.4f}  {r['seconds']}s  {r['verification']}"
            )
    print(f"ledger total ${setup.spent_so_far():.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
