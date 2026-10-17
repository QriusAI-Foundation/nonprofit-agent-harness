"""Run the free citation check over the quotation-integrity corpus and tabulate it.

    python scripts/quotation_eval.py
    python scripts/quotation_eval.py --context 20 --markdown

Offline and free: `GroundingVerifier` with `passes=0` makes no model call. Each item is a
source passage and a quote that is either faithful to it (exact, or drifted only in
whitespace, case or punctuation) or altered (a changed quantity, an added or removed
negation, reordered words, or a paraphrase). A faithful quote should be accepted and an
altered one should not.

`--context N` puts each passage among N other passages from the corpus, which is closer
to a real document: a fuzzy match then has more text in which to find shared words.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from nonprofit_harness.verification import GroundingVerifier
from nonprofit_harness.verification.types import Citation, Claim

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "quotation_integrity.jsonl"
KIND_ORDER = (
    "exact",
    "whitespace_case",
    "punctuation",
    "changed_quantity",
    "added_negation",
    "removed_negation",
    "reordered",
    "paraphrase",
)


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def evaluate(items: list[dict], context: int) -> dict[str, Counter]:
    verifier = GroundingVerifier(passes=0)
    rng = random.Random(7)
    passages = sorted({item["source_passage"] for item in items})
    outcomes: dict[str, Counter] = defaultdict(Counter)

    for item in items:
        source = item["source_passage"]
        if context:
            pool = [p for p in passages if p != source]
            others = rng.sample(pool, k=min(context, len(pool)))
            parts = [*others[: context // 2], source, *others[context // 2 :]]
            source = "\n\n".join(parts)
        claim = Claim(statement=item["quote"], citations=[Citation(text=item["quote"])])
        verdict = verifier.verify(claim, {"source": source})
        outcomes[item["kind"]][str(verdict.outcome)] += 1
    return outcomes


def table(outcomes: dict[str, Counter], labels: dict[str, str]) -> list[list[str]]:
    names = sorted({name for counts in outcomes.values() for name in counts})
    rows = [["kind", "label", "n", *names, "correct"]]
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for kind in [k for k in KIND_ORDER if k in outcomes]:
        counts = outcomes[kind]
        n = sum(counts.values())
        # Accepted means verified; anything else is a rejection or a flag for a person.
        accepted = counts.get("verified", 0)
        correct = accepted if labels[kind] == "faithful" else n - accepted
        totals[labels[kind]][0] += correct
        totals[labels[kind]][1] += n
        rows.append(
            [kind, labels[kind], str(n), *(str(counts.get(x, 0)) for x in names), _pct(correct, n)]
        )
    for label, (correct, n) in sorted(totals.items()):
        rows.append([f"all {label}", label, str(n), *("" for _ in names), _pct(correct, n)])
    return rows


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def render(rows: list[list[str]], markdown: bool) -> str:
    if markdown:
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
        lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
        return "\n".join(lines)
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    padded = (
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True))
        for row in rows
    )
    return "\n".join(padded)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--context", type=int, default=0, help="other passages around each")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--json", type=Path, default=None, help="also write raw counts here")
    args = parser.parse_args(argv)

    items = load(args.fixture)
    labels = {item["kind"]: item["label"] for item in items}
    outcomes = evaluate(items, args.context)
    print(f"{len(items)} items, context={args.context} passage(s), passes=0 (no model calls)\n")
    print(render(table(outcomes, labels), args.markdown))
    if args.json:
        args.json.write_text(
            json.dumps({k: dict(v) for k, v in outcomes.items()}, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
