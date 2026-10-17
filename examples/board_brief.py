"""A plain-language brief for a board, with every key point quoted from the source.

    harness run examples.board_brief:BoardBriefAgent report.pdf --option words=300

Each point carries a verbatim quote, so the harness checks it against the document for
free before a person in the organisation reads the brief.
"""

from __future__ import annotations

from examples._cited import ask_for_cited, with_claims_listed
from nonprofit_harness import Agent, AgentResult, RunContext

SYSTEM = (
    "You brief the board of a small nonprofit. Board members are volunteers, not "
    "specialists. Use short sentences and plain words. Say what the document is, what "
    "it asks of the organisation, and what the board should decide or watch. Never "
    "state a fact that is not in the source."
)


class BoardBriefAgent(Agent):
    name = "board-brief"
    description = "Writes a plain-language board brief with every key point quoted."
    version = "0.1.0"

    # Left on. A brief goes to trustees under the organisation's name.
    requires_review = True

    def run(self, ctx: RunContext) -> AgentResult:
        words = int(ctx.option("words", 300))
        points = int(ctx.option("points", 6))
        artifacts = []

        for document in ctx.inputs:
            text, claims, model = ask_for_cited(
                ctx,
                f"Write a board brief of about {words} words on the document below, in "
                f"Markdown, with {points} key points. Put the brief in `text` and give "
                f"one claim per key point.\n\nTitle: {document.name}\n\n{document.text}",
                system=SYSTEM,
                document=document.name,
            )
            artifacts.append(
                self.artifact(
                    "board-brief",
                    with_claims_listed(text, claims),
                    title=f"Board brief: {document.name}",
                    claims=claims,
                    source_document=document.name,
                    model=model,
                )
            )

        return AgentResult(artifacts=artifacts, summary=f"{len(artifacts)} board brief(s)")
