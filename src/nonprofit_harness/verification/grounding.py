"""Does a quoted span really appear in a source document.

This answers one question only: is the quotation faithful to the source? It does
not ask whether the source supports the claim the quotation is attached to. A
verbatim quote can still be cited for a conclusion it does not reach, and catching
that takes a reader (or the opt-in cross-check in `verifier.py`).

The rules, in the order they are applied:

1. **Exact.** After collapsing whitespace and case, the quote appears in the source
   on word boundaries. "reached 5" does not match inside "reached 50", "reached 5.5",
   "reached 5,000", "reached 5%" or "reached -5", and "can" does not match inside
   "can't".
2. **Refused outright.** The quote is aligned in order against the closest passage.
   If a number (sign and currency symbol included), a negation, or the position of
   a content word differs, the quote is a different statement and the match is
   refused. Number words and digits are not equated: "thirty four" never matches
   "34", which costs a false alarm and never a false pass.
3. **Approximate.** Every remaining difference is punctuation, an article or "that"
   added or dropped, or a swap inside a small set of near-synonyms ("in"/"during",
   "a"/"the", "that"/"which"), and there are at most `max_edits` of them.
4. **Needs a person.** The quote still lines up with the passage on most of its
   words, but the differences fall outside rule 3. The free check cannot tell a
   harmless paraphrase from a changed meaning, so it flags rather than decides.
   An exact or approximate quote is also flagged when the words around it change
   what it says: a negation or "failed"/"unable" in the three words before it, a
   qualifier such as "than" or "up to" before a leading number, or a number cut out
   of a range, a ratio, or a scale word ("5" from "5-10", "5/10", "5 million").

Anything else is not found. No rule makes a model call.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from nonprofit_harness.verification.types import GroundingHit

#: A word, a number with its sign or currency symbol, decimal point, thousands
#: separators and percent sign, or a word with an apostrophe in it. Keeping "-5",
#: "$5", "5,000" and "1.5" whole is what stops "5" lining up against them, and
#: keeping "didn't" whole lets the negation in it be seen. A hyphen counts as a sign
#: only after a space or bracket, so "5-10" stays two numbers.
_TOKEN = re.compile(
    r"(?:(?<![^\s(\[])[-+\u2212$\u20ac\u00a3\u00a5\u20b9](?=\d))?"
    r"[^\W_]+(?:(?:(?<=\d)[.,](?=\d)|'(?=[^\W_]))[^\W_]+)*(?:(?<=\d)%)?"
)
_DIGITS = re.compile(r"\d")
_TYPOGRAPHIC = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
_EDGE_PUNCTUATION = " \"'.,;:!?()[]"

#: English number words, checked alongside digits. Reports in this sector write
#: quantities both ways in the same paragraph ("twelve villages", "34 learners"),
#: so digits alone would miss half of them. English-only, and deliberately small.
_NUMBER_WORDS = frozenset(
    # fmt: off
    [
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
        "million",
        "billion",
        "half",
        "quarter",
        "third",
        "first",
        "second",
        "fourth",
        "fifth",
        "none",
        "all",
        "every",
        "no",
    ]
    # fmt: on
)

#: Words that reverse or hollow out what follows. Hedges such as "rarely" are here
#: too: dropping one turns "rarely attended" into "attended", which is the same
#: failure as dropping "not".
_NEGATIONS = frozenset(
    # fmt: off
    [
        "not",
        "no",
        "never",
        "nor",
        "neither",
        "none",
        "nothing",
        "nobody",
        "nowhere",
        "without",
        "hardly",
        "barely",
        "scarcely",
        "seldom",
        "rarely",
    ]
    # fmt: on
)

#: Words that, just before a quote, reverse it without being part of it: "failed to
#: reach the target" contains "reach the target" verbatim.
_REVERSING_CONTEXT = _NEGATIONS | frozenset(
    ["fail", "fails", "failed", "unable", "lack", "lacks", "lacked", "lacking"]
)

#: Words that, just before a quote that opens on a number, bound or approximate it:
#: "fewer than 5 attended" contains "5 attended".
_NUMBER_QUALIFIERS = frozenset(
    # fmt: off
    [
        "than",
        "to",
        "up",
        "over",
        "under",
        "above",
        "below",
        "about",
        "around",
        "approximately",
        "nearly",
        "almost",
        "least",
        "most",
        "only",
        "some",
    ]
    # fmt: on
)

#: Words that, just after a quote that ends on a number, scale it: "raised 5" is cut
#: from "raised 5 million".
_SCALES = frozenset(
    ["hundred", "thousand", "million", "billion", "trillion", "lakh", "crore", "percent", "per"]
)

_IRREGULAR_NEGATIVES = {"can't": "can", "cannot": "can", "won't": "will", "shan't": "shall"}

#: Words a quote may add or drop without changing what it says. Kept tiny on
#: purpose: "and", "or", "to", "from" and "before" all look like filler and all
#: change meaning when they move.
_DROPPABLE = frozenset(["a", "an", "the", "that"])

#: Near-synonyms a model swaps while quoting. A swap outside these sets is a
#: wording change a person has to judge.
_INTERCHANGEABLE = (
    frozenset(["a", "an", "the"]),
    frozenset(["in", "during", "within", "throughout"]),
    frozenset(["that", "which"]),
)

#: Words too common to count as "moved" when they turn up near a passage rather
#: than inside it. Not a list of words a quote may change: see `_DROPPABLE`.
_FUNCTION_WORDS = _DROPPABLE | frozenset(
    # fmt: off
    [
        "in",
        "on",
        "at",
        "to",
        "from",
        "of",
        "for",
        "by",
        "with",
        "into",
        "per",
        "each",
        "and",
        "or",
        "but",
        "as",
        "is",
        "was",
        "are",
        "were",
        "be",
        "been",
        "has",
        "have",
        "had",
        "it",
        "its",
        "they",
        "their",
        "this",
        "these",
        "those",
        "which",
        "who",
    ]
    # fmt: on
)

_EXACT, _APPROXIMATE, _UNCERTAIN = "exact", "fuzzy", "uncertain"
_RANK = {_EXACT: 3, _APPROXIMATE: 2, _UNCERTAIN: 1}


def is_quantity(token: str) -> bool:
    return bool(_DIGITS.search(token)) or token in _NUMBER_WORDS


def is_negation(token: str) -> bool:
    return token in _NEGATIONS


def max_edits(quote_length: int) -> int:
    """How many rule-3 differences an approximate quote may carry.

    One per five words, at least one and at most three. Beyond three, a long quote
    has drifted far enough that a person should compare it.
    """
    return min(3, max(1, quote_length // 5))


def normalize(text: str) -> str:
    return " ".join(text.translate(_TYPOGRAPHIC).split()).lower()


def tokenize(text: str) -> list[str]:
    """Words of `text`, lower-cased, with "didn't" split into "did" and "not"."""
    tokens: list[str] = []
    for token in _TOKEN.findall(text.translate(_TYPOGRAPHIC).lower()):
        tokens.extend(_expand_negative(token))
    return tokens


def _expand_negative(token: str) -> list[str]:
    # "didn't reach" and "did not reach" are the same quote. Splitting the
    # contraction lets them align, and makes "not" visible to the negation rule.
    if token in _IRREGULAR_NEGATIVES:
        return [_IRREGULAR_NEGATIVES[token], "not"]
    if token.endswith("n't") and len(token) > 3:
        return [token[:-3], "not"]
    return [token]


@dataclass(frozen=True, slots=True)
class Lookup:
    """What a search for one quote found.

    `hit` is None when nothing resolved. `refused` then says why the closest passage
    was turned down, if one was close enough to be worth naming.
    """

    hit: GroundingHit | None
    refused: str = ""

    @property
    def resolved(self) -> bool:
        return self.hit is not None and self.hit.mode != _UNCERTAIN


class SourceIndex:
    """The documents a claim may cite, prepared once and reused across claims.

    Tokenising every source for every citation is the obvious way to write this and
    also the slow way, so the preparation happens here.
    """

    def __init__(self, sources: Mapping[str, str]) -> None:
        self._normalized = {name: normalize(text) for name, text in sources.items()}
        self._tokens = {name: tokenize(text) for name, text in sources.items()}

    @property
    def documents(self) -> list[str]:
        return list(self._normalized)

    def find(self, span: str, *, fuzzy_threshold: float = 0.6) -> GroundingHit | None:
        """The exact or approximate match for `span`, or None.

        A quote that only resembles the source is not returned here, so a caller
        that treats any hit as grounded stays safe. Use `lookup` to see those.
        """
        lookup = self.lookup(span, fuzzy_threshold=fuzzy_threshold)
        return lookup.hit if lookup.resolved else None

    def lookup(self, span: str, *, fuzzy_threshold: float = 0.6) -> Lookup:
        """Apply the module's rules to `span` against every document.

        `fuzzy_threshold` is the share of the quote's words that must line up, in
        order, before a quote outside the approximate rules is flagged for a person
        rather than reported as not found. It never makes a quote resolve.
        """
        core = normalize(span).strip(_EDGE_PUNCTUATION)
        if not core:
            return Lookup(None)

        best: GroundingHit | None = None
        for document, text in self._normalized.items():
            best = _better(best, _exact(core, document, text))
        if best is not None and best.mode == _EXACT:
            return Lookup(best)

        quote = tokenize(span)
        if not quote:
            return Lookup(best)
        refused, closest = "", 0.0
        for document, tokens in self._tokens.items():
            for start, end in _regions(quote, tokens, fuzzy_threshold):
                hit, reason, share = _approximate(quote, tokens, start, end, fuzzy_threshold)
                best = _better(best, hit and _named(hit, document))
                # Naming why a passage was refused helps only when it was close.
                # Half the quote lining up is the least that makes "a number
                # differs" a useful pointer rather than noise.
                if reason and share >= 0.5 and share > closest:
                    refused, closest = reason, share
        return Lookup(best, "" if best is not None else refused)


def _better(current: GroundingHit | None, candidate: GroundingHit | None) -> GroundingHit | None:
    if candidate is None:
        return current
    if current is None:
        return candidate
    if (_RANK[candidate.mode], candidate.score) > (_RANK[current.mode], current.score):
        return candidate
    return current


def _named(hit: GroundingHit, document: str) -> GroundingHit:
    return GroundingHit(document=document, mode=hit.mode, score=hit.score, note=hit.note)


# --- rule 1: exact ---------------------------------------------------------------


def _exact(core: str, document: str, text: str) -> GroundingHit | None:
    """A verbatim occurrence, preferring one whose surroundings do not alter it."""
    quote = tokenize(core)
    flagged: GroundingHit | None = None
    for found in _boundary_pattern(core).finditer(text):
        before = tokenize(text[max(0, found.start() - 80) : found.start()])
        # Start one character early so a hyphen after the quote reads as a range
        # dash, not a minus sign, then drop the quote's own last token.
        after = tokenize(text[found.end() - 1 : found.end() + 40])[1:]
        note = _context_note(quote, before, after)
        if note:
            flagged = GroundingHit(document, _UNCERTAIN, 1.0, note)
            continue
        return GroundingHit(document=document, mode=_EXACT, score=1.0)
    return flagged


def _context_note(quote: list[str], before: list[str], after: list[str]) -> str:
    """Why the source around a faithful quote changes what it says, or "".

    "never reached its targets" contains "reached its targets" word for word. The
    quote is real, but it may be cited for the opposite of what the source says, so
    a person looks.
    """
    for word in reversed(before[-3:]):
        if word in _REVERSING_CONTEXT:
            return f"the source reads '{word}' just before it"
    if quote and is_quantity(quote[0]) and before and before[-1] in _NUMBER_QUALIFIERS:
        return f"the source qualifies the number with '{before[-1]}'"
    if (
        quote
        and is_quantity(quote[-1])
        and after
        and (after[0] in _SCALES or _DIGITS.search(after[0]))
    ):
        return f"the number continues in the source as '{quote[-1]} {after[0]}'"
    return ""


def _boundary_pattern(core: str) -> re.Pattern[str]:
    before, after = "", ""
    if core[0].isalnum():
        before = r"(?<!\w)(?<!\w')"
        if core[0].isdigit():
            before += r"(?<!\d[.,])(?<![-+\u2212$\u20ac\u00a3\u00a5\u20b9])"
    if core[-1].isalnum():
        after = r"(?!\w)(?!'\w)"
        if core[-1].isdigit():
            after += r"(?![.,]\d)(?!%)"
    return re.compile(before + re.escape(core) + after)


# --- rules 2 to 4: aligned in order ----------------------------------------------


def _regions(quote: list[str], tokens: list[str], threshold: float) -> list[tuple[int, int]]:
    """Stretches of the source worth aligning against, merged where they overlap.

    Alignment is quadratic, so it runs only where enough of the quote's words occur
    close together to possibly line up. A window with fewer of them cannot hold an
    alignment that matches more.
    """
    width = _span_limit(len(quote))
    needed = max(1, min(math.ceil(threshold * len(quote)), len(quote) - max_edits(len(quote))))
    if len(tokens) <= width:
        return [(0, len(tokens))] if tokens else []

    wanted = set(quote)
    present = [token in wanted for token in tokens]
    count = sum(present[:width])
    regions: list[tuple[int, int]] = []
    for start in range(len(tokens) - width + 1):
        if start:
            count += present[start + width - 1] - present[start - 1]
        if count < needed:
            continue
        end = start + width
        if regions and start <= regions[-1][1]:
            regions[-1] = (regions[-1][0], end)
        else:
            regions.append((start, end))
    return regions


def _span_limit(quote_length: int) -> int:
    # A quote that needs its passage stretched by more than half again is spread
    # across the passage, not quoted from it.
    return quote_length + max(3, quote_length // 2)


def _approximate(
    quote: list[str], tokens: list[str], start: int, end: int, threshold: float
) -> tuple[GroundingHit | None, str, float]:
    """Judge the best in-order alignment of the quote inside `tokens[start:end]`.

    Returns the hit if there is one, the refusal reason if a rule refused it, and
    the share of the quote that lined up.
    """
    pairs, first, last = _align(quote, tokens[start:end])
    matched = sum(1 for q, s in pairs if q is not None and q == s)
    share = matched / len(quote)
    edits = [(q, s) for q, s in pairs if q != s]
    score = round(matched / (matched + len(edits)), 4)
    nearby = tokens[max(0, start + first - len(quote)) : start + last + len(quote)]

    refused = _refusal(pairs, nearby)
    if refused:
        return None, refused, share
    before = tokens[max(0, start + first - 3) : start + first]
    after = tokens[start + last : start + last + 1]
    note = _context_note(quote, before, after)
    if note:
        return GroundingHit("", _UNCERTAIN, score, note), "", share
    if len(edits) <= max_edits(len(quote)) and all(_allowed(q, s) for q, s in edits):
        return GroundingHit("", _APPROXIMATE, score, _describe(edits)), "", share
    if share >= threshold and last - first <= _span_limit(len(quote)):
        note = f"{len(edits)} word difference(s) the free check cannot judge"
        return GroundingHit("", _UNCERTAIN, score, note), "", share
    return None, "", share


def _refusal(pairs: Sequence[tuple[str | None, str | None]], nearby: list[str]) -> str:
    changed = [token for pair in pairs if pair[0] != pair[1] for token in pair if token]
    if any(is_quantity(token) for token in changed):
        return "a number differs from the source"
    if any(is_negation(token) for token in changed):
        return "a negation was added, removed, or moved"
    # A word the alignment could not place, yet which the passage holds unplaced,
    # has been moved: "funds went from the state to the district" swaps two words
    # inside the passage. A content word may also have moved just outside it, since
    # "the NGO funded the district" and "the district funded the NGO" share every
    # word. Function words are not chased that far: "in" occurs in every paragraph.
    unplaced = Counter(q for q, s in pairs if q is not None and q != s and not _allowed(q, s))
    left_over = Counter(s for q, s in pairs if s is not None and q != s)
    matched = Counter(q for q, s in pairs if q is not None and q == s)
    content = Counter({t: n for t, n in unplaced.items() if t not in _FUNCTION_WORDS})
    if unplaced & left_over or content & (Counter(nearby) - matched):
        return "word order differs from the source"
    return ""


def _allowed(quote_token: str | None, source_token: str | None) -> bool:
    if quote_token is None:
        return source_token in _DROPPABLE
    if source_token is None:
        return quote_token in _DROPPABLE
    return any(quote_token in group and source_token in group for group in _INTERCHANGEABLE)


def _describe(edits: list[tuple[str | None, str | None]]) -> str:
    if not edits:
        return "differs only in punctuation"
    return f"{len(edits)} article or near-synonym difference(s)"


def _align(
    quote: list[str], window: list[str]
) -> tuple[list[tuple[str | None, str | None]], int, int]:
    """Best in-order alignment of the whole quote against part of the window.

    Semi-global: the quote must be used end to end, the window may be entered and
    left anywhere. Each pair is (quote token, source token), with None for a word
    one side lacks. Also returns where in the window the alignment starts and ends.

    Cost is ten per edit (five for one rule 3 allows) minus one per matched word, so
    of two alignments with the same edits the one that lines up more words wins.
    That keeps a skipped "not" inside the alignment where the negation rule sees it.
    """
    rows, cols = len(quote), len(window)
    cost = [[0] * (cols + 1) for _ in range(rows + 1)]
    for i in range(1, rows + 1):
        cost[i][0] = cost[i - 1][0] + _gap_cost(quote[i - 1])
        for j in range(1, cols + 1):
            cost[i][j] = min(
                cost[i - 1][j - 1] + _pair_cost(quote[i - 1], window[j - 1]),
                cost[i - 1][j] + _gap_cost(quote[i - 1]),
                cost[i][j - 1] + _gap_cost(window[j - 1]),
            )

    j = min(range(cols + 1), key=lambda col: cost[rows][col])
    last = j
    pairs: list[tuple[str | None, str | None]] = []
    i = rows
    while i > 0:
        if j > 0 and cost[i][j] == cost[i - 1][j - 1] + _pair_cost(quote[i - 1], window[j - 1]):
            pairs.append((quote[i - 1], window[j - 1]))
            i, j = i - 1, j - 1
        elif cost[i][j] == cost[i - 1][j] + _gap_cost(quote[i - 1]):
            pairs.append((quote[i - 1], None))
            i -= 1
        else:
            pairs.append((None, window[j - 1]))
            j -= 1
    pairs.reverse()
    return pairs, j, last


def _pair_cost(quote_token: str, source_token: str) -> int:
    if quote_token == source_token:
        return -1
    return 5 if _allowed(quote_token, source_token) else 10


def _gap_cost(token: str) -> int:
    return 5 if token in _DROPPABLE else 10


def is_grounded(span: str, source: str, *, fuzzy_threshold: float = 0.6) -> bool:
    """Convenience check for a single span against a single document.

    True only for an exact or approximate match. A quote that needs a person to
    compare it is not grounded.
    """
    return SourceIndex({"source": source}).find(span, fuzzy_threshold=fuzzy_threshold) is not None


__all__ = [
    "Lookup",
    "SourceIndex",
    "is_grounded",
    "is_negation",
    "is_quantity",
    "max_edits",
    "normalize",
    "tokenize",
]
