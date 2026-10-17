"""One section of a funder report, with each factual claim cited to the source.

    harness run examples.funder_report:FunderReportAgent manual.pdf \
        --option section="Approach and training content"

The section describes what the source says. It does not report results the source does
not contain, and every claim is checked against the document before review.
"""

from __future__ import annotations

from examples._cited import ask_for_cited, with_claims_listed
from nonprofit_harness import Agent, AgentResult, RunContext

SYSTEM = (
    "You draft sections of reports to institutional funders for a nonprofit. Write in "
    "a factual, measured register. Describe only what the source document states. Do "
    "not claim outcomes, numbers reached, or impact unless the source gives them, and "
    "attribute them to the source when it does."
)

DEFAULT_SECTION = "Programme approach and training content"


class FunderReportAgent(Agent):
    name = "funder-report"
    description = "Drafts a funder report section with every factual claim cited."
    version = "0.1.0"

    # Left on. A funder report is a representation made to a funder.
    requires_review = True

    def run(self, ctx: RunContext) -> AgentResult:
        section = str(ctx.option("section", DEFAULT_SECTION))
        words = int(ctx.option("words", 400))
        artifacts = []

        for document in ctx.inputs:
            text, claims, model = ask_for_cited(
                ctx,
                f'Draft the funder report section "{section}" in about {words} words of '
                "Markdown, drawing on the document below as the programme's training "
                "material. Put the section in `text`, and give one claim for each factual "
                f"statement it makes.\n\nTitle: {document.name}\n\n{document.text}",
                system=SYSTEM,
                document=document.name,
            )
            artifacts.append(
                self.artifact(
                    "funder-report-section",
                    with_claims_listed(text, claims),
                    title=f"{section}: {document.name}",
                    claims=claims,
                    section=section,
                    source_document=document.name,
                    model=model,
                )
            )

        return AgentResult(artifacts=artifacts, summary=f"{len(artifacts)} section(s)")
