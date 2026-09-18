"""A minimal reference agent.

It exists to show the shape of an agent and to give the test suite something real
to run. Replace it with your own; nothing else in the harness depends on it.

    harness run examples.summarizer:SummarizerAgent report.pdf
"""

from __future__ import annotations

from nonprofit_harness import Agent, AgentResult, RunContext

SYSTEM = (
    "You write plain-language summaries for nonprofit staff and boards. "
    "Use short sentences. Avoid jargon. Never invent facts that are not in the source."
)


class SummarizerAgent(Agent):
    name = "summarizer"
    description = "Turns a long document into a short plain-language brief for a board update."
    version = "0.1.0"

    # Left at the default. A brief that goes to a board should be read by a person
    # in that organisation before it is sent anywhere.
    requires_review = True

    def run(self, ctx: RunContext) -> AgentResult:
        artifacts = []
        words = int(ctx.option("words", 200))

        for document in ctx.inputs:
            response = ctx.provider.generate(
                f"Summarise the following document in about {words} words.\n\n"
                f"Title: {document.name}\n\n{document.text}",
                system=SYSTEM,
            )
            artifacts.append(
                self.artifact(
                    "summary",
                    response.text,
                    title=f"Summary of {document.name}",
                    source_document=document.name,
                    model=response.model,
                )
            )

        return AgentResult(
            artifacts=artifacts,
            summary=f"Summarised {len(ctx.inputs)} document(s).",
        )
