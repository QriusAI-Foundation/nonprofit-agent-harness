# quotation_integrity.jsonl: licence and provenance

Released under CC0 1.0 Universal (public domain dedication):
https://creativecommons.org/publicdomain/zero/1.0/

Every passage is invented. The items were generated on 2026-10-17 by Claude Opus 5.5
(36 calls, effort medium, plus a 12-call second pass on the hardest kinds) and Claude Sonnet 5.5 (8 calls, effort high) through the
harness's own `AgentRunner`, with `showcase/quotation_corpus.py`. The raw replies are in
`showcase/corpus_raw/`. No third-party text was used as input.

Each item was then checked mechanically: the quote must differ from its passage exactly
as its `kind` says (see `valid()` in `showcase/quotation_corpus.py`). Items that failed
were dropped, the rest deduplicated and balanced: 407 per kind, and up to twice that for the hardest kinds (changed quantity, reordered, moved negation).

Fields: `id`, `kind`, `label` (`faithful`: a verbatim quote that only drifts in spacing,
case or punctuation; `altered`: the meaning changed, or the text is not a quote),
`source_passage`, `quote`, `generator`.

A mechanical check proves the edit has the right shape. It does not prove that every
altered quote reads naturally, or that a paraphrase keeps the meaning. Nobody has
reviewed all 3,966 items by hand.
