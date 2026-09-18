"""Summarise an organisation's published IATI activities.

Shows the shape of using a data source with the harness. The important detail is that
the agent does not fetch anything. Data sources run on the caller's side and produce
`Document`s; the agent receives documents and nothing else, exactly as it would for an
uploaded PDF. That is what keeps an agent testable offline and unable to reach past
its own inputs.

Run it with a free key from https://developer.iatistandard.org:

    export IATI_API_KEY=...
    python -m examples.iati_portfolio XM-DAC-41114
"""

from __future__ import annotations

import sys

from nonprofit_harness import Agent, AgentResult, RunContext

SYSTEM = (
    "You write short portfolio overviews for nonprofit and funder staff. "
    "Use plain language and short sentences. "
    "Describe only what the activity records actually say. Do not estimate or infer."
)


class PortfolioSummaryAgent(Agent):
    name = "iati-portfolio"
    description = "Writes a plain-language overview of a set of published IATI activities."

    def run(self, ctx: RunContext) -> AgentResult:
        if not ctx.inputs:
            return AgentResult(summary="No activities to summarise.")

        countries = sorted(
            {
                country
                for document in ctx.inputs
                for country in document.metadata.get("recipient_countries", [])
            }
        )
        combined = "\n\n---\n\n".join(document.text for document in ctx.inputs)

        response = ctx.provider.generate(
            f"Write an overview of these {len(ctx.inputs)} activities in about "
            f"{ctx.option('words', 250)} words.\n\n{combined}",
            system=SYSTEM,
        )

        return AgentResult(
            artifacts=[
                self.artifact(
                    "portfolio-overview",
                    response.text,
                    title=f"Portfolio overview, {len(ctx.inputs)} activities",
                    activity_count=len(ctx.inputs),
                    countries=countries,
                )
            ],
            summary=f"Summarised {len(ctx.inputs)} activities across {len(countries)} countries.",
        )


def main(argv: list[str] | None = None) -> int:
    from nonprofit_harness.config import HarnessConfig
    from nonprofit_harness.core.errors import DataSourceError
    from nonprofit_harness.core.registry import AgentRegistry
    from nonprofit_harness.core.runner import AgentRunner
    from nonprofit_harness.datasources import IatiClient
    from nonprofit_harness.providers import load_provider
    from nonprofit_harness.storage import load_stores

    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m examples.iati_portfolio <reporting-org-ref>", file=sys.stderr)
        return 2

    # A cache matters here. The free tier allows 100 calls a week, and re-running a
    # script during development goes through that faster than you would expect.
    client = IatiClient(cache={})
    try:
        activities = client.search_activities(reporting_org=args[0], rows=5)
    except DataSourceError as exc:
        # A missing key is the common case and is not a bug, so it should read as an
        # instruction rather than a traceback.
        print(f"Could not read IATI: {exc}", file=sys.stderr)
        return 1

    if not activities:
        print(f"No published activities found for {args[0]}", file=sys.stderr)
        return 1

    registry = AgentRegistry()
    registry.register(PortfolioSummaryAgent())
    config = HarnessConfig.from_env()
    runner = AgentRunner(
        registry=registry,
        stores=load_stores(config.storage),
        provider=load_provider(config.provider),
        config=config,
    )

    run = runner.start(
        PortfolioSummaryAgent.name,
        org_id="org_local",
        inputs=[activity.to_document() for activity in activities],
    )

    print(f"run {run.id}: {run.status}")
    for artifact in run.artifacts:
        print(f"\n--- {artifact.title} [{artifact.status}] ---\n{artifact.content}")
    if run.pending_review:
        print(f"\n{len(run.pending_review)} artifact(s) awaiting human review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
