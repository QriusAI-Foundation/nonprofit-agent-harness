from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping

from nonprofit_harness.verification.types import GroundingHit

#: How much wider than the quoted span the fuzzy window may be. A small allowance
#: for a quote that picked up a few extra words; anything larger starts matching
#: unrelated passages that happen to share vocabulary.
_WINDOW_SLACK = 1.5
_MIN_WINDOW = 8

_TOKEN = re.compile(r"[a-z0-9]+")
_DIGITS = re.compile(r"\d")

#: English number words, checked alongside digits. Reports in this sector write
#: quantities both ways in the same paragraph ("twelve villages", "34 learners"),
#: so digits alone would miss half of them. English-only, and deliberately small.
_NUMBER_WORDS = frozenset(
    # fmt: off
    [
        "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
        "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
        "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty",
        "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand",
        "million", "billion", "half", "quarter", "third", "first", "second",
        "fourth", "fifth", "none", "all", "every", "no",
    ]
    # fmt: on
)


def is_quantity(token: str) -> bool:
    return bool(_DIGITS.search(token)) or token in _NUMBER_WORDS


def normalize(text: str) -> str:
    return " ".join(text.split()).lower()


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class SourceIndex:
    """The documents a claim may cite, prepared once and reused across claims.

    Tokenising every source for every citation is the obvious way to write this and
    also the slow way, so the preparation happens here and each lookup is a single
    linear pass.
    """

    def __init__(self, sources: Mapping[str, str]) -> None:
        self._normalized = {name: normalize(text) for name, text in sources.items()}
        self._tokens = {name: tokenize(text) for name, text in sources.items()}

    @property
    def documents(self) -> list[str]:
        return list(self._normalized)

    def find(self, span: str, *, fuzzy_threshold: float = 0.6) -> GroundingHit | None:
        """Locate a quoted span, preferring a real quote over a near approximation.

        An exact match (after collapsing whitespace and case) is what an honest
        verbatim citation looks like. The fuzzy pass exists because models reliably
        introduce small edits while quoting, not to accept a paraphrase.
        """
        normalized_span = normalize(span)
        if not normalized_span:
            return None

        for document, text in self._normalized.items():
            if normalized_span in text:
                return GroundingHit(document=document, mode="exact", score=1.0)

        span_tokens = tokenize(span)
        if not span_tokens:
            return None
        span_set = set(span_tokens)

        best: GroundingHit | None = None
        for document, tokens in self._tokens.items():
            score, missing = _best_window(span_set, tokens, len(span_tokens))
            if score < fuzzy_threshold:
                continue
            # A quote that changed a number is not an approximate quote, it is a
            # different statement. "reached ninety villages" overlaps "reached twelve
            # villages" on two words out of three, and that is exactly the fabrication
            # this check exists to catch.
            if any(is_quantity(token) for token in missing):
                continue
            if best is None or score > best.score:
                best = GroundingHit(document=document, mode="fuzzy", score=round(score, 4))
        return best


def _best_window(
    span_set: set[str], tokens: list[str], span_length: int
) -> tuple[float, set[str]]:
    """Best-matching stretch of the source, and which span words it did not contain.

    Measured over a sliding window rather than the whole document. Checking against
    the document as a whole lets a span pass whenever its words appear *anywhere*,
    which in a long report is nearly always true and makes the check meaningless.
    """
    if not span_set or not tokens:
        return 0.0, set(span_set)

    window = max(_MIN_WINDOW, int(span_length * _WINDOW_SLACK))
    if len(tokens) <= window:
        present = span_set & set(tokens)
        return len(present) / len(span_set), span_set - present

    counts: defaultdict[str, int] = defaultdict(int)
    matched = 0
    best = 0.0
    best_start = 0

    for index, token in enumerate(tokens):
        if token in span_set:
            counts[token] += 1
            if counts[token] == 1:
                matched += 1
        if index >= window:
            leaving = tokens[index - window]
            if leaving in span_set:
                counts[leaving] -= 1
                if counts[leaving] == 0:
                    matched -= 1
        if index >= window - 1:
            score = matched / len(span_set)
            if score > best:
                best, best_start = score, index - window + 1
            if best == 1.0:
                break

    present = span_set & set(tokens[best_start : best_start + window])
    return best, span_set - present


def is_grounded(span: str, source: str, *, fuzzy_threshold: float = 0.6) -> bool:
    """Convenience check for a single span against a single document."""
    return SourceIndex({"source": source}).find(span, fuzzy_threshold=fuzzy_threshold) is not None


__all__ = ["SourceIndex", "is_grounded", "normalize", "tokenize"]
