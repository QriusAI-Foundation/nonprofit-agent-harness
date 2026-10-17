# Is there a quotation-integrity dataset to adopt?

Date: 2026-10-17. Time box: 15 minutes. Method: Exa web search, `gh search repos`, and
dataset cards. No dataset was downloaded or run.

**Decision: generate our own corpus.** No openly licensed dataset pairs a source passage
with a *verbatim quote* and labels the quote's alterations by kind (changed number, added
or removed negation, reordering, drift in case, spacing or punctuation) under a licence
an Apache 2.0 repository can carry without a separate notice.

## What the harness needs

`GroundingVerifier` with `passes=0` answers one question: is this quoted span really in
the source? A test set for it needs (passage, quote, label) items where faithful quotes
differ only in spacing, case or punctuation, and altered quotes change the meaning by a
small edit. Entailment datasets answer a different question ("does the evidence support
this claim?"), where a faithful paraphrase is a positive. For a quote checker a paraphrase
is a negative.

## Candidates

| Dataset | Licence | Size | Last update | Verbatim quotes | Number / negation negatives | Fit (1-5) |
|---|---|---|---|---|---|---|
| VitaminC (`tals/vitaminc`) | Data CC BY-SA 3.0 | 450k+ pairs | 2021 | No: claims, entailment labels | Numbers yes (contrastive Wikipedia edits); negation implicit | 2 |
| FactCC (salesforce/factCC) | Code BSD-3; no data licence; needs CNN/DailyMail | generated | archived 2025-05 | No: summary sentences | Yes, as transforms (number swap, negation) | 2 |
| AttributionBench (`osunlp/AttributionBench`) | Apache 2.0 card; mixed upstream terms | 10k-100k | 2024 | No | No | 1 |
| groundtruth-bench | Code MIT; data CC BY-SA 4.0 plus unlicensed items | 200 | 2026-07 | Yes (97 substring items) | Number swap yes, negation no | 3 |
| SeekBench v0 (`seekbot/skbench`) | CC BY 4.0, gated, "must not be used to train" | 1,405 | 2026-10 | Yes | No; noisy no-match labels | 2 |
| Legal_Phantom_Citation | CC BY 4.0 | 1,300 | 2025 | Partly (synonym misquotes) | No | 2 |
| quote-provenance-eval | Apache 2.0 | about 55 questions | n/a | Yes, with formatting traps | No | 2 |
| SciFact, FEVER, ALCE, SummaC, AggreFact | various (SciFact NC) | n/a | n/a | No: entailment or retrieval | n/a | 1 |

## Adopt now

- Generate the corpus: invented passages (no third-party text, so CC0), one quote per
  kind per passage, and a mechanical check that each altered quote differs from its
  passage exactly as its kind says. See `showcase/quotation_corpus.py`.
- Borrow the ideas, not the data: FactCC's number-swap and negation transforms shaped the
  kinds; quote-provenance-eval's formatting traps (curly quotes, dashes, double spaces)
  shaped the whitespace and punctuation kinds.

## Avoid

- SeekBench: gated, with use restrictions, and labels too noisy for a test oracle.
- FactCC data: no data licence and a dependency on CNN/DailyMail text.
- Entailment sets as a quote-checker benchmark: they reward paraphrase.
- groundtruth-bench as the main set: 200 items, one annotator, mixed licences.
