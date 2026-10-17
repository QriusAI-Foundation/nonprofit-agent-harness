"""Generate the quotation-integrity corpus through the harness, then validate it.

    set -a; source .env; set +a
    python -m showcase.quotation_corpus generate --calls 30
    python -m showcase.quotation_corpus build

`generate` runs a small agent through `AgentRunner` on Claude: each call writes fictional
programme-report passages and, for each passage, one quote per kind. Raw replies are kept
in `showcase/corpus_raw/`. `build` validates every item mechanically (the quote must
differ from the passage exactly in the way its kind says), dedupes, balances, and writes
`tests/fixtures/quotation_integrity.jsonl`.

The passages are invented, so the corpus contains no third-party text and is released
under CC0 1.0 (see the fixture's licence note).
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from examples._cited import parse_json

from nonprofit_harness import Agent, AgentResult, RunContext
from nonprofit_harness.core.types import Document
from nonprofit_harness.verification.grounding import is_quantity, normalize, tokenize
from showcase import harness_setup as setup

RAW = setup.HERE / "corpus_raw"
FIXTURE = setup.HERE.parent / "tests" / "fixtures" / "quotation_integrity.jsonl"

FAITHFUL_KINDS = ("exact", "whitespace_case", "punctuation")
ALTERED_KINDS = (
    "changed_quantity",
    "added_negation",
    "removed_negation",
    "reordered",
    "paraphrase",
)
KINDS = FAITHFUL_KINDS + ALTERED_KINDS

#: Words that carry negation once text is tokenised. "doesn't" tokenises to "doesn",
#: "t", so the contracted stems are here too.
# fmt: off
NEGATION = frozenset([
    "not", "no", "never", "none", "nor", "neither", "without", "cannot", "t", "isn",
    "aren", "wasn", "weren", "doesn", "don", "didn", "won", "hasn", "haven", "hadn",
    "shouldn", "wouldn", "couldn",
])
# fmt: on

DOMAINS = [
    ("community health workers", "a district health programme in East Africa"),
    ("maternal and newborn health", "a clinic-outreach project in South Asia"),
    ("school feeding", "a primary-school nutrition programme in West Africa"),
    ("girls' secondary education", "a scholarship programme in Central America"),
    ("water, sanitation and hygiene", "a rural borehole and latrine project"),
    ("smallholder agriculture", "a farmer field school network"),
    ("microfinance and savings groups", "a village savings and loan programme"),
    ("refugee protection", "a camp-based case management service"),
    ("disaster preparedness", "a coastal early-warning programme"),
    ("adult literacy", "an evening literacy class network"),
    ("mental health and psychosocial support", "a community counselling service"),
    ("youth employment", "a vocational training centre"),
    ("HIV community home-based care", "a home-visiting programme"),
    ("malaria prevention", "a bed net distribution campaign"),
    ("child protection", "a foster care and family tracing service"),
    ("climate adaptation", "a drought-resilient crops project"),
    ("disability inclusion", "an assistive devices and accessibility project"),
    ("food security", "a cash transfer programme"),
    ("early childhood development", "a community playgroup network"),
    ("legal aid", "a paralegal outreach service"),
]

GENRES = [
    "an annual report to a funder",
    "a mid-term evaluation summary",
    "a trainer's guide for volunteers",
    "a board update",
    "a monitoring report",
    "a grant proposal background section",
]

SYSTEM = """You write test data for a citation checker used by nonprofits.

Write realistic but entirely fictional passages from nonprofit programme documents.
Invent organisation and place names; never copy real text. Each passage is one paragraph
of 70 to 140 words. Every passage must contain at least two quantities (some as digits,
some as words, a percentage, a date or year) and at least one negated sentence (using
not, no, never, or a contraction such as did not or wasn't).

For each passage, write exactly one quote of each kind below. Every quote is taken from
the passage. Spans are 8 to 30 words long and must not cross more than one sentence
boundary.

- exact: a contiguous span copied character for character.
- whitespace_case: a contiguous span with only letter case and spacing changed (for
  example extra spaces, a line break, or capitalisation). Same words, same punctuation.
- punctuation: a contiguous span with only punctuation changed (a comma dropped or
  added, straight quotes made curly, a hyphen made a dash, a full stop removed). Same
  words in the same order.
- changed_quantity: a contiguous span that contains a quantity, with exactly one
  quantity replaced by a different one. Everything else verbatim.
- added_negation: a contiguous span from an affirmative sentence with a negation inserted
  (not, no, never, or a contraction) so the meaning reverses. Everything else verbatim.
- removed_negation: a contiguous span containing a negation, with the negation removed
  so the meaning reverses. Everything else verbatim.
- reordered: a contiguous span with two content words or two noun phrases swapped so the
  meaning changes, for example "mothers trained volunteers" from "volunteers trained
  mothers". Same words, different order.
- paraphrase: the meaning of a span restated in different words, as a summary would.
"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "passages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_passage": {"type": "string"},
                    "variants": {
                        "type": "object",
                        "properties": {kind: {"type": "string"} for kind in KINDS},
                        "required": list(KINDS),
                    },
                },
                "required": ["source_passage", "variants"],
            },
        },
    },
    "required": ["text", "passages"],
}


class QuotationCorpusAgent(Agent):
    name = "quotation-corpus"
    description = "Writes fictional passages with labelled quote variants for testing."
    version = "0.1.0"

    def run(self, ctx: RunContext) -> AgentResult:
        brief = ctx.inputs[0]
        response = ctx.provider.generate(
            brief.text, system=SYSTEM, json_schema=SCHEMA, max_output_tokens=32_000
        )
        return AgentResult(
            artifacts=[self.artifact("corpus-batch", response.text, title=brief.name)],
            summary="1 batch",
        )


def brief_for(call: int, passages: int) -> Document:
    rng = random.Random(call)
    picks = rng.sample(DOMAINS, k=min(passages, len(DOMAINS)))
    lines = [
        f"Write {passages} passages. Put a one-line note in `text` and the passages in "
        "`passages`. Use these settings, one passage each, varying the genre:"
    ]
    for number, (topic, setting) in enumerate(picks, start=1):
        lines.append(f"{number}. {topic}, in {setting}, written as {rng.choice(GENRES)}")
    return Document(text="\n".join(lines), name=f"corpus-call-{call:03d}")


def generate(calls: int, first: int, model: str, effort: str | None, workers: int) -> None:
    setup.require_key()
    setup.require_headroom(calls * 0.9)
    RAW.mkdir(parents=True, exist_ok=True)

    def one(call: int) -> str:
        run = setup.runner(QuotationCorpusAgent(), model, effort=effort, max_cost_usd=3.0).start(
            QuotationCorpusAgent.name, org_id="showcase", inputs=[brief_for(call, 10)]
        )
        setup.record("corpus", run, model, call=call)
        if run.artifacts:
            (RAW / f"{model}-{call:03d}.json").write_text(run.artifacts[0].content)
        return f"call {call}: {run.status} ${run.usage.cost_usd:.4f} {run.error or ''}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(one, c) for c in range(first, first + calls)]):
            print(future.result(), flush=True)
    print(f"ledger total ${setup.spent_so_far():.4f}")


# --- mechanical validation -----------------------------------------------------------


def _ops(passage: list[str], quote: list[str]) -> list[tuple[str, list[str], list[str]]] | None:
    """Edits that turn the best-aligned passage window into the quote, or None."""
    matcher = difflib.SequenceMatcher(None, passage, quote, autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size]
    if not blocks:
        return None
    start, end = blocks[0].a, blocks[-1].a + blocks[-1].size
    window = passage[start:end]
    inner = difflib.SequenceMatcher(None, window, quote, autojunk=False)
    ops = [(tag, window[i1:i2], quote[j1:j2]) for tag, i1, i2, j1, j2 in inner.get_opcodes()]
    return [op for op in ops if op[0] != "equal"]


def _contiguous(passage: list[str], quote: list[str]) -> bool:
    n = len(quote)
    return any(passage[i : i + n] == quote for i in range(len(passage) - n + 1))


def valid(kind: str, passage: str, quote: str) -> bool:
    """True when the quote differs from the passage exactly as its kind says."""
    p_tokens, q_tokens = tokenize(passage), tokenize(quote)
    if len(q_tokens) < 5:
        return False
    if kind == "exact":
        return quote in passage
    if kind == "whitespace_case":
        return quote not in passage and normalize(quote) in normalize(passage)
    if kind == "punctuation":
        return normalize(quote) not in normalize(passage) and _contiguous(p_tokens, q_tokens)

    ops = _ops(p_tokens, q_tokens)
    if not ops:
        return False
    if kind == "changed_quantity":
        return all(
            tag == "replace" and any(map(is_quantity, a)) and any(map(is_quantity, b))
            for tag, a, b in ops
        ) and not _contiguous(p_tokens, q_tokens)
    if kind in ("added_negation", "removed_negation"):
        added = kind == "added_negation"
        for _, a, b in ops:
            gained, lost = (b, a) if added else (a, b)
            if not set(gained) & NEGATION or len(gained) - len(lost) > 2:
                return False
        return True
    if kind == "reordered":
        return (
            not _contiguous(p_tokens, q_tokens)
            and normalize(quote) not in normalize(passage)
            and any(
                sorted(p_tokens[i : i + len(q_tokens)]) == sorted(q_tokens)
                for i in range(len(p_tokens) - len(q_tokens) + 1)
            )
        )
    if kind == "paraphrase":
        novel = [t for t in q_tokens if t not in set(p_tokens)]
        return not _contiguous(p_tokens, q_tokens) and len(novel) >= 2
    return False


def build(per_kind: int | None) -> None:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    rejected: dict[str, int] = {kind: 0 for kind in KINDS}

    for path in sorted(RAW.glob("*.json")):
        generator = path.stem.rsplit("-", 1)[0]
        for entry in parse_json(path.read_text()).get("passages") or []:
            passage = str(entry.get("source_passage") or "").strip()
            variants = entry.get("variants") or {}
            if not passage:
                continue
            for kind in KINDS:
                quote = str(variants.get(kind) or "")
                key = hashlib.sha256(f"{kind}\0{normalize(passage)}\0{quote}".encode()).hexdigest()
                if key in seen:
                    continue
                seen.add(key)
                if not valid(kind, passage, quote):
                    rejected[kind] += 1
                    continue
                items.append(
                    {
                        "id": key[:12],
                        "kind": kind,
                        "label": "faithful" if kind in FAITHFUL_KINDS else "altered",
                        "source_passage": passage,
                        "quote": quote,
                        "generator": generator,
                    }
                )

    by_kind: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}
    for item in items:
        by_kind[item["kind"]].append(item)
    cap = per_kind or min(len(v) for v in by_kind.values())
    rng = random.Random(17)
    balanced = []
    for kind in KINDS:
        rng.shuffle(by_kind[kind])
        balanced.extend(by_kind[kind][:cap])
    balanced.sort(key=lambda item: item["id"])

    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in balanced))
    print(f"wrote {len(balanced)} items ({cap} per kind) to {FIXTURE}")
    for kind in KINDS:
        print(f"  {kind:<18} valid {len(by_kind[kind]):>5}  rejected {rejected[kind]:>4}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="showcase.quotation_corpus")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--calls", type=int, default=30)
    gen.add_argument("--first", type=int, default=0)
    gen.add_argument("--model", default="claude-opus-5-5")
    gen.add_argument("--effort", default="medium")
    gen.add_argument("--workers", type=int, default=4)
    bld = sub.add_parser("build")
    bld.add_argument("--per-kind", type=int, default=None)
    args = parser.parse_args(argv)

    if args.command == "generate":
        generate(args.calls, args.first, args.model, args.effort, args.workers)
    else:
        build(args.per_kind)
    return 0


if __name__ == "__main__":
    sys.exit(main())
