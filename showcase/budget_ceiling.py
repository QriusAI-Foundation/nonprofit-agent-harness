"""Trip the budget ceilings on purpose, and record what the harness does.

    python -m showcase.budget_ceiling

Three runs, all cheap:

1. A cost ceiling below what one call costs. The call has already happened by the time
   its usage is known, so the run fails and records the full spend, overshoot included
   (add-then-check, AGENTS.md rule 4).
2. The harness's default token ceiling (200,000) against a 330,000-token manual.
3. A ceiling that the agent's own call fits under but cross-model checking does not.
   The run keeps its artifact, and the claims verification did not reach go to a person
   as inconclusive.
"""

from __future__ import annotations

import json
import sys

from examples.funder_report import FunderReportAgent
from examples.results_narrative import ResultsNarrativeAgent

from showcase import harness_setup as setup
from showcase.quorum import REVIEWERS
from showcase.sources import DOCUMENTS, document, results_documents

OUT = setup.HERE / "budget"


def cases():
    pathfinder = document(next(s for s in DOCUMENTS if s.slug == "pathfinder-chbc-trainers"))
    sheet = dict(results_documents())["wbtf-rwanda-chw"]
    yield (
        "cost-ceiling",
        FunderReportAgent(),
        pathfinder,
        "claude-haiku-5-5",
        {"max_cost_usd": 0.05},
    )
    yield (
        "token-ceiling-default",
        FunderReportAgent(),
        pathfinder,
        "claude-haiku-5-5",
        {"max_tokens": 200_000, "max_cost_usd": None},
    )
    yield (
        "ceiling-during-verification",
        ResultsNarrativeAgent(),
        sheet,
        "claude-sonnet-5-5",
        {
            "max_cost_usd": 0.06,
            "verify_passes": 3,
            "verify_models": REVIEWERS,
            "max_calls": 200,
        },
    )


def main() -> int:
    setup.require_key()
    setup.require_headroom(1.0)
    OUT.mkdir(exist_ok=True)
    for label, agent, source, model, limits in cases():
        run = setup.runner(agent, model, **limits).start(
            agent.name, org_id="showcase", inputs=[source]
        )
        setup.record("budget", run, model, case=label)
        artifact = run.artifacts[0] if run.artifacts else None
        verification = artifact.verification if artifact else None
        receipt = {
            "case": label,
            "run_id": run.id,
            "model": model,
            "limits": limits,
            "status": str(run.status),
            "error": run.error,
            "usage": {
                "calls": run.usage.calls,
                "input_tokens": run.usage.input_tokens,
                "output_tokens": run.usage.output_tokens,
                "cost_usd": round(run.usage.cost_usd, 6),
            },
            "artifact_kept": artifact is not None,
            "verification": verification.summary() if verification else None,
            "harness_commit": setup.git_commit(),
        }
        (OUT / f"{label}.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt))
    print(f"ledger total ${setup.spent_so_far():.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
