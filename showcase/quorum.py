"""Cross-model verification: three reviewers, three models, one quorum per claim.

    python -m showcase.quorum --label before

Runs agents through `AgentRunner` with `verify_passes=3` and one model per pass, the
same as setting `HARNESS_VERIFY_PASSES=3` and
`HARNESS_VERIFY_MODELS=claude-haiku-5-5,claude-sonnet-5-5,claude-opus-5-5`. Every
reviewer call is metered by the same budget guard as the agent's own call, so the
receipt shows what checking cost on top of writing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from examples.funder_report import FunderReportAgent
from examples.results_narrative import ResultsNarrativeAgent

from showcase import harness_setup as setup
from showcase.sources import DOCUMENTS, document, results_documents

OUT = setup.HERE / "quorum"
REVIEWERS = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]


def cases():
    sheets = dict(results_documents())
    manuals = {source.slug: source for source in DOCUMENTS}
    yield "results-narrative", "wbtf-rwanda-chw", ResultsNarrativeAgent(), sheets[
        "wbtf-rwanda-chw"
    ]
    yield "funder-report", "who-chw-curriculum", FunderReportAgent(), document(
        manuals["who-chw-curriculum"]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="showcase.quorum")
    parser.add_argument("--label", required=True, help="before or after, for the file name")
    parser.add_argument("--writer", default="claude-sonnet-5-5")
    args = parser.parse_args(argv)
    setup.require_key()
    setup.require_headroom(3.0)
    OUT.mkdir(exist_ok=True)

    for agent_name, slug, agent, source in cases():
        run = setup.runner(
            agent, args.writer, verify_passes=3, verify_models=REVIEWERS, max_calls=200
        ).start(agent.name, org_id="showcase", inputs=[source])
        setup.record("quorum", run, args.writer, source=slug, label=args.label)
        artifact = run.artifacts[0] if run.artifacts else None
        report = artifact.verification if artifact else None
        verdicts = report.verdicts if report else []
        receipt = {
            "label": args.label,
            "run_id": run.id,
            "agent": agent_name,
            "source": slug,
            "writer": args.writer,
            "reviewers": REVIEWERS,
            "harness_commit": setup.git_commit(),
            "status": str(run.status),
            "error": run.error,
            "usage": {
                "calls": run.usage.calls,
                "input_tokens": run.usage.input_tokens,
                "output_tokens": run.usage.output_tokens,
                "cost_usd": round(run.usage.cost_usd, 6),
            },
            "summary": report.summary() if report else None,
            "outcomes": dict(Counter(str(v.outcome) for v in verdicts)),
            "votes": dict(Counter(vote for v in verdicts for vote in v.votes)),
            "verdicts": [v.to_dict() for v in verdicts],
            "claims": [
                {"id": c.id, "statement": c.statement, "quote": c.citations[0].text}
                for c in (artifact.claims if artifact else [])
            ],
        }
        path = OUT / f"{agent_name}-{slug}.{args.label}.json"
        path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(
            f"{args.label} {agent_name}/{slug}: {run.status} calls={run.usage.calls} "
            f"${run.usage.cost_usd:.4f} {receipt['summary']} votes={receipt['votes']}"
        )
    print(f"ledger total ${setup.spent_so_far():.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
