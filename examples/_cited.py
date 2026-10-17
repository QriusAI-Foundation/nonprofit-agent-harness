"""Shared by the cited examples: ask for text plus the quotes that back it.

The model is asked for JSON holding the prose and a list of claims, each with a verbatim
quote from the source. The harness then checks every quote against the run's own inputs
before a person reviews the artifact. Nothing here judges quality; it only makes the
claims checkable.
"""

from __future__ import annotations

import json
from typing import Any

from nonprofit_harness import Citation, Claim, RunContext

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "quote": {"type": "string"},
                    "locator": {"type": "string"},
                },
                "required": ["statement", "quote"],
            },
        },
    },
    "required": ["text", "claims"],
}

QUOTING_RULES = (
    "Every claim must carry a quote copied character for character from the source: "
    "a contiguous passage of one sentence or less, with no words added, removed, or "
    "changed, and no ellipses. If you cannot find a quote for a statement, leave the "
    "statement out. The locator is a section heading or nearby title from the source."
)

#: Long enough for the reasoning the 5.x models do before answering, plus the JSON. The
#: Messages API counts both against one ceiling, so a tight value truncates the reply.
MAX_OUTPUT_TOKENS = 16_000


def ask_for_cited(
    ctx: RunContext, prompt: str, *, system: str, document: str
) -> tuple[str, list[Claim], str]:
    """Return the prose, its claims, and the model that wrote them."""
    response = ctx.provider.generate(
        prompt,
        system=f"{system}\n\n{QUOTING_RULES}",
        json_schema=SCHEMA,
        max_output_tokens=int(ctx.option("max_output_tokens", MAX_OUTPUT_TOKENS)),
    )
    payload = parse_json(response.text)
    claims = [
        Claim(
            statement=str(item.get("statement", "")),
            citations=[
                Citation(
                    text=str(item.get("quote", "")),
                    document=document,
                    locator=str(item.get("locator", "")),
                )
            ],
        )
        for item in payload.get("claims") or []
        if isinstance(item, dict) and item.get("quote")
    ]
    return str(payload.get("text") or response.text), claims, response.model


def parse_json(text: str) -> dict[str, Any]:
    """Read the reply's JSON object, tolerating a code fence or other text around it.

    The Anthropic adapter requests the schema rather than enforcing it, so a reply can
    arrive fenced, after a sentence, or even after an echo of the schema itself. The
    first object holding a `text` key wins. Anything unreadable becomes an artifact with
    no claims, which a reviewer sees as such, rather than a failed run.
    """
    decoder = json.JSONDecoder()
    first: dict[str, Any] = {}
    position = text.find("{")
    while position != -1:
        try:
            payload, end = decoder.raw_decode(text, position)
        except json.JSONDecodeError:
            position = text.find("{", position + 1)
            continue
        if isinstance(payload, dict):
            if "text" in payload:
                return payload
            first = first or payload
        position = text.find("{", end)
    return {} if "properties" in first else first


def with_claims_listed(text: str, claims: list[Claim]) -> str:
    """Append the cited evidence so a reviewer reads the claims next to the prose."""
    if not claims:
        return text
    lines = [text.rstrip(), "", "## Evidence cited", ""]
    for number, claim in enumerate(claims, start=1):
        citation = claim.citations[0]
        where = f" ({citation.locator})" if citation.locator else ""
        lines.append(f"{number}. {claim.statement}")
        lines.append(f'   > "{citation.text}"{where}')
    return "\n".join(lines) + "\n"
