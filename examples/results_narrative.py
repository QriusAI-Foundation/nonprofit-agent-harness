"""A results narrative over IATI-shaped results, honest about what cannot be calculated.

The arithmetic happens before the model sees anything: `results_sheet` runs the
harness's deterministic `achievement` over every indicator and writes one line per
figure. The agent narrates that sheet, quotes the lines it relies on, and the harness
checks each quote. Indicators whose achievement cannot be calculated are listed by the
agent itself from the sheet's metadata, so that list never depends on the model.

    python -m examples.results_narrative activity.xml
"""

from __future__ import annotations

import sys
from pathlib import Path

from examples._cited import ask_for_cited, with_claims_listed
from nonprofit_harness import Agent, AgentResult, RunContext
from nonprofit_harness.core.types import Document
from nonprofit_harness.datasources.iati_xml import XmlActivity, parse_activities
from nonprofit_harness.results import Indicator, achievement

SYSTEM = (
    "You write results narratives for nonprofit programme reports. Use only the "
    "results sheet you are given. Do not compute new figures, percentages, or totals; "
    "the sheet already holds every figure that can be stated. Where the sheet says an "
    "achievement is not calculable, say so plainly and give its reason. Never treat a "
    "missing actual as zero."
)


class ResultsNarrativeAgent(Agent):
    name = "results-narrative"
    description = "Narrates an IATI-shaped results sheet and lists what is not calculable."
    version = "0.1.0"

    # Left on. Results statements go to funders and the public.
    requires_review = True

    def run(self, ctx: RunContext) -> AgentResult:
        words = int(ctx.option("words", 400))
        artifacts = []

        for document in ctx.inputs:
            text, claims, model = ask_for_cited(
                ctx,
                f"Write a results narrative of about {words} words in Markdown from the "
                "results sheet below. Put it in `text`, and give one claim for every "
                "figure or finding it states, quoting the sheet line it comes from."
                f"\n\n{document.text}",
                system=SYSTEM,
                document=document.name,
            )
            not_calculable = document.metadata.get("not_calculable", [])
            artifacts.append(
                self.artifact(
                    "results-narrative",
                    with_claims_listed(text, claims) + _not_calculable_section(not_calculable),
                    title=f"Results narrative: {document.name}",
                    claims=claims,
                    source_document=document.name,
                    not_calculable=not_calculable,
                    model=model,
                )
            )

        return AgentResult(artifacts=artifacts, summary=f"{len(artifacts)} narrative(s)")


def results_sheet(activity: XmlActivity, *, name: str | None = None) -> Document:
    """One activity's results as plain lines, with the arithmetic already done.

    Runs on the caller's side, like any data source, so the agent receives a document
    and nothing else.
    """
    lines = [f"Results sheet for IATI activity {activity.iati_identifier}", activity.title, ""]
    not_calculable: list[str] = []

    for result in activity.results:
        lines.append(f"Result ({result.type}): {result.title}")
        for indicator in result.indicators:
            figure = achievement(indicator)
            lines.extend(f"  {line}" for line in _indicator_lines(indicator))
            lines.append(f"  Achievement: {figure.explain()}")
            if figure.ratio is None:
                not_calculable.append(figure.explain())
        lines.append("")

    return Document(
        text="\n".join(lines).strip() + "\n",
        name=name or activity.iati_identifier,
        media_type="text/plain",
        metadata={"iati_identifier": activity.iati_identifier, "not_calculable": not_calculable},
    )


def _indicator_lines(indicator: Indicator) -> list[str]:
    direction = "higher is better" if indicator.ascending else "lower is better"
    lines = [f"Indicator: {indicator.title} ({indicator.measure}, {direction})"]
    if indicator.baseline is not None:
        value = _number(indicator.baseline.value)
        lines.append(f"  Baseline: {value} in {indicator.baseline.year or 'an unstated year'}")
    for period in indicator.periods:
        target = _number(period.target.value) if period.target else "none stated"
        actual = _number(period.actual.value) if period.actual else "none reported"
        lines.append(f"  Period {period.label()}: target {target}, actual {actual}")
    return lines


def _number(value: float | None) -> str:
    if value is None:
        return "not stated"
    return str(int(value)) if float(value).is_integer() else str(value)


def _not_calculable_section(items: list[str]) -> str:
    if not items:
        return ""
    lines = ["", "## Not calculable from the published data", ""]
    lines.extend(f"- {item}" for item in items)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from nonprofit_harness.config import HarnessConfig
    from nonprofit_harness.core.registry import AgentRegistry
    from nonprofit_harness.core.runner import AgentRunner
    from nonprofit_harness.providers import load_provider
    from nonprofit_harness.storage import load_stores

    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m examples.results_narrative <activity.xml>", file=sys.stderr)
        return 2

    sheets = [results_sheet(a) for a in parse_activities(Path(args[0]).read_bytes())]
    config = HarnessConfig.from_env()
    registry = AgentRegistry()
    registry.register(ResultsNarrativeAgent())
    runner = AgentRunner(
        registry=registry,
        stores=load_stores(config.storage),
        provider=load_provider(config.provider),
        config=config,
    )
    run = runner.start(ResultsNarrativeAgent.name, org_id="org_local", inputs=sheets)
    print(f"run {run.id}: {run.status}")
    if run.error:
        print(f"error: {run.error}", file=sys.stderr)
        return 1
    for artifact in run.artifacts:
        print(artifact.content)
        if artifact.verification is not None:
            print(f"verification: {artifact.verification.summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
