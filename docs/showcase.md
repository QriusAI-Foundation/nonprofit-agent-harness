# See it run: the harness against real Claude models

On 2026-10-17 the QriusAI Foundation spent USD 85.36 of Anthropic API credit on real
runs of this harness. Every call went through `AgentRunner`, the Anthropic provider and
the budget guard, so every cost and token count below is the harness's own accounting,
written into a receipt beside each output. Everything is in [`showcase/`](../showcase),
and [`showcase/README.md`](../showcase/README.md) says how to reproduce it with your own
key.

| | |
|---|---|
| Date | 2026-10-17 |
| Models | `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5` (effort medium unless stated), `claude-fable-5-1` |
| Prices | [`showcase/prices-2026-10-17.json`](../showcase/prices-2026-10-17.json), first-party list prices on that date. Deployer data for this showcase, not a package default |
| Harness | the merged `main` after the audit fixes (523 tests), plus this branch's provider changes |
| Spend | USD 85.36 over 183 harness runs, itemised in [`showcase/SPEND.md`](../showcase/SPEND.md) |

**No model judged quality here.** The tables report tokens, cost, and what the free
citation check found. Whether a brief is good is the human review gate's decision, and
every artifact in `showcase/runs/` is still `pending_review`, as the harness left it.

## What was run

| Task | Harness runs | USD | What it shows |
|---|---:|---:|---|
| Three example agents over six documents and three IATI activities, four models | 118 | 64.94 | Cost per model and document, and what the citation check finds in real output |
| Quotation-integrity corpus generation | 56 | 18.96 | A 3,966-item labelled test set for the citation check, CC0 |
| Cross-model quorum, before and after the vote-cap fix | 4 | 0.99 | Three reviewers on three models agreeing per claim |
| Budget ceilings tripped on purpose | 3 | 0.39 | The ceiling stops the run and records the overshoot |
| Readiness answer sets for 50 fictional organisations | 1 | 0.08 | How the scorer handles messy answers |
| One live check after a review fix to the adapter | 1 | 0.001 | Structured outputs still work |

## The example agents

Three short agents, each in `examples/`, each working offline with the echo provider:

- [`board_brief.py`](../examples/board_brief.py): a plain-language brief for trustees,
  six key points, each with a verbatim quote.
- [`funder_report.py`](../examples/funder_report.py): one funder report section, with a
  quote for every factual statement.
- [`results_narrative.py`](../examples/results_narrative.py): a narrative over an
  IATI activity's results. The harness's own `achievement()` does the arithmetic before
  the model sees anything. The agent then appends the list of indicators that cannot be
  calculated, taken from data rather than from the model.

Sources: six openly licensed documents of 103,000 to 385,000 tokens (WHO, IFRC,
Pathfinder, ALNAP, two World Bank reports) and three published IATI activities. URLs,
licences, hashes and attribution are in [`showcase/SOURCES.md`](../showcase/SOURCES.md).
Each whole document went to the model in one call.

### Tokens, cost, and citation outcomes by model

Totals over all runs of each agent and model. "Resolved" means the quote was found in
the source. It does not mean the source supports the statement; only the opt-in
cross-check tests that. "Uncertain" goes to a person. "Not found" is a quote the source
does not contain.

| Agent | Model | Runs | Input tokens | Output tokens | USD | Claims | Not found | Uncertain | Resolved (exact) | Resolved (fuzzy) | Empty outputs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| board-brief | haiku-5-5 | 6 | 1,551,229 | 9,519 | 0.80 | 38 | 2 | 5 | 30 | 1 | 0 |
| board-brief | sonnet-5-5 | 6 | 1,551,229 | 15,879 | 3.26 | 36 | 0 | 0 | 36 | 0 | 0 |
| board-brief | opus-5-5 | 9 | 2,212,077 | 20,218 | 9.25 | 54 | 0 | 3 | 51 | 0 | 0 |
| board-brief | fable-5-1 | 2 | 716,843 | 6,819 | 7.51 | 12 | 0 | 0 | 12 | 0 | 0 |
| funder-report | haiku-5-5 | 6 | 1,551,367 | 20,876 | 0.83 | 96 | 2 | 17 | 77 | 0 | 1 |
| funder-report | sonnet-5-5 | 6 | 1,551,367 | 27,636 | 3.38 | 84 | 1 | 10 | 72 | 1 | 0 |
| funder-report | opus-5-5 | 9 | 2,212,284 | 45,598 | 9.76 | 194 | 0 | 4 | 190 | 0 | 0 |
| funder-report | opus-5-5, effort high | 1 | 158,089 | 8,475 | 0.80 | 25 | 0 | 0 | 25 | 0 | 0 |
| funder-report | fable-5-1 | 2 | 716,889 | 17,195 | 8.03 | 51 | 0 | 2 | 49 | 0 | 0 |
| results-narrative | haiku-5-5 | 3 | 17,458 | 23,482 | 0.01 | 84 | 0 | 35 | 49 | 0 | 0 |
| results-narrative | sonnet-5-5 | 3 | 17,458 | 10,978 | 0.14 | 43 | 0 | 18 | 25 | 0 | 1 |
| results-narrative | opus-5-5 | 6 | 34,916 | 26,059 | 0.66 | 166 | 0 | 54 | 112 | 0 | 0 |

Every run, with its time and verification line, is in
[`showcase/TABLES.md`](../showcase/TABLES.md). Opus has a second run on the three
original documents and the IATI sheets, so its rows show how much a re-run varies (for
example 26 and 23 claims on the IFRC funder report). Fable 5.1 ran on the two largest
documents only. The effort-high row is the WHO funder report: 25 claims, 8,475 output
tokens and USD 0.80, beside 19 claims, about 5,000 to 5,700 output tokens and USD 0.73 to
0.75 for each of the two runs at medium.

What a nonprofit can read from this:

- **Cost.** Haiku 5.5 read a 330,000-token manual for USD 0.17. Opus 5.5 read it for
  USD 1.37 and Fable 5.1 for USD 3.53. Haiku's rate rises fivefold above 100,000 prompt
  tokens, and every manual here was above that; the price file and the receipts include
  that rate.
- **Empty answers.** Every funder-report call to Haiku 5.5 over the 332,000-token
  Pathfinder guide came back empty: 14 output tokens, three times, counting the two
  budget runs. Its board brief on the same guide was fine. Sonnet returned a narrative
  with no claims once.
  An artifact with no claims has nothing for the free check to test. A reviewer sees an
  empty evidence list, and the harness does not flag it.

### What the citation check caught, and what it got wrong

Five quotes in real output were not found in their source. Reading each against the
extracted text:

| Model | Source | Quote (start) | Finding |
|---|---|---|---|
| haiku-5-5 | WDR 2018 | "Recent examples show how an iterative, adaptive approach can strengthen..." | **A real misquote.** The source says "adopting a more iterative, adaptive approach to change". The model wrote a sentence the report does not contain |
| haiku-5-5 | WDR 2018 | "Ensure that new information and communication technology is really implementable..." | False rejection: the PDF text reads "tech- nology", hyphenated at a line break |
| haiku-5-5, sonnet-5-5 | IFRC manual | "What you learn is in response to what your own community has decided..." | False rejection: the PDF text reads "com- munity" |
| haiku-5-5 | IFRC manual | "...explain to community members what CBHFA activities CAN, and CANNOT do." | False rejection: the PDF text reads "ac- tivities" |

So the check caught one invented quote in 883 claims, and rejected four correct
quotes because PDF extraction keeps line-break hyphens. Its stated reason for the four,
"word order differs from the source", is wrong. See "Noticed, not fixed".

Most "uncertain" verdicts on results narratives are also false positives. The results
sheet has a line such as `target 60, actual none reported`, and the next line is the
achievement line the model quoted exactly. The negation-context check reads "none" at
the end of the previous line as if it came just before the quote, and holds the claim
for a person. It is safe, because a person decides, but it is noise on line-structured
data.

## The quotation-integrity corpus

No openly licensed dataset fits a verbatim-quote checker
([`showcase/RESEARCH.md`](../showcase/RESEARCH.md)), so one was generated:
[`tests/fixtures/quotation_integrity.jsonl`](../tests/fixtures/quotation_integrity.jsonl),
3,966 items, CC0. Each item is an invented programme-report passage and one quote.
Opus 5.5 (48 calls) and Sonnet 5.5 (8 calls) wrote them through the harness. Each item
then passed a mechanical check that the quote differs from the passage exactly as its
kind says. The hardest kinds have up to twice as many items. Nobody has read all 3,966
by hand.

`python scripts/quotation_eval.py` runs `GroundingVerifier(passes=0)` over it: offline,
free, no model call. Before is `main` at `bb46dd2`, before the citation fix (PR #6).
After is the final `main`. Same 3,966 items. A faithful quote is correct when accepted;
an altered quote is correct when not accepted.

| Kind | Label | Items | Correct before | Correct after | After: uncertain (to a person) |
|---|---|---:|---:|---:|---:|
| exact | faithful | 407 | 100.0% | 98.8% | 5 |
| whitespace or case drift | faithful | 407 | 100.0% | 97.8% | 9 |
| punctuation drift | faithful | 407 | 100.0% | 97.1% | 12 |
| changed quantity | altered | 624 | 99.0% | 100.0% | 0 |
| added negation | altered | 407 | 1.0% | 100.0% | 0 |
| removed negation | altered | 407 | 0.0% | 100.0% | 0 |
| reordered content words | altered | 660 | 0.0% | 100.0% | 0 |
| moved negation | altered | 240 | 0.0% | 100.0% | 0 |
| paraphrase | altered | 407 | 88.7% | 100.0% | 6 |
| **all altered** | | 2,745 | **35.8%** | **100.0%** | |
| **all faithful** | | 1,221 | **100.0%** | **97.9%** | |

Before the fix, a quote with a negation added, removed or moved, or with its words
reordered, passed almost every time. After it, none passed. The cost is that 26 faithful
quotes (2.1%) now go to a person as uncertain instead of passing. None is wrongly
rejected. With each passage placed among 20 others (`--context 20`), the after figures
are 100.0% and 97.3%. Raw counts are in [`showcase/eval/`](../showcase/eval).

The corpus measures one thing: whether the check tells a quote from a near-quote. It
does not measure whether a quoted passage supports the claim that cites it.

## Cross-model quorum

`HARNESS_VERIFY_PASSES=3` with `HARNESS_VERIFY_MODELS=claude-haiku-5-5,claude-sonnet-5-5,claude-opus-5-5`.
Each claim gets one vote from each model, and two of three must agree. Run with
[`showcase/quorum.py`](../showcase/quorum.py). Before and after are separate runs, so
the claims differ.

| | Agent, source | Calls | USD | Outcomes | Votes by reviewer |
|---|---|---:|---:|---|---|
| before | funder report, WHO | 55 | 0.39 | 14 verified, 4 inconclusive | Haiku 15 supported, 3 unsure; Sonnet 15, 3; **Opus 0, 18 unsure** |
| after | funder report, WHO | 55 | 0.44 | 14 supported, 4 inconclusive | Haiku 15, 3; Sonnet 16, 2; **Opus 13, 5** |
| before | results narrative, Rwanda | 34 | 0.06 | 9 verified, 2 inconclusive | Haiku 10, 1; Sonnet 9, 2; Opus 0, 11 |
| after | results narrative, Rwanda | 34 | 0.10 | 7 supported, 4 inconclusive | Haiku 7, 4; Sonnet 10, 1; Opus 0, 11 |

Before the fix every Opus vote was "unsure". The verifier allowed 16 output tokens, and
the 5.5 models spend those on thinking before they answer. In a live probe, Sonnet and
Opus returned empty text with `stop_reason: max_tokens`. The fix raised the cap to 1,024.
Opus now votes on the funder report claims. On the Rwanda claims it still answered
"unsure" eleven times out of eleven. Those claims quote lines such as
`target 26, actual 0`, and saying "unsure" about whether that supports "the project
reached 0%" is a reasonable answer. The receipts do not show which of the two reasons
applies.

Checking cost little: 33 to 54 reviewer calls added about USD 0.04 to 0.09 to a run,
because each reviewer sees only the claim and its quote, not the document.

## Budget ceilings

Recorded with [`showcase/budget_ceiling.py`](../showcase/budget_ceiling.py):

| Case | Limit | What happened | Recorded spend |
|---|---|---|---:|
| Cost ceiling below one call | `max_cost_usd=0.05`, Haiku on the 332,000-token guide | One call went out, then the run failed: "Run would exceed its cost ceiling: $0.1660 of $0.0500" | USD 0.1660 |
| Default token ceiling | `HARNESS_MAX_TOKENS=200000`, same document | Failed: "Run would exceed its token ceiling: 331,874 of 200,000" | USD 0.1660 |
| Ceiling reached during verification | `max_cost_usd=0.06`, quorum on | The agent's artifact was kept; 11 claims marked inconclusive for a person; run sent to review | USD 0.0605 |
| Dollar ceiling, no price | `HARNESS_MAX_COST_USD=1`, no `HARNESS_PRICES` | Refused before dispatch, 0 calls ([`showcase/checks/`](../showcase/checks/unpriced-dollar-ceiling.txt)) | USD 0 |

The first two show add-then-check (AGENTS.md rule 4): the harness cannot know a prompt's
size in tokens before the API reports it, so the first call goes out. The run then
records the full spend, overshoot included, rather than the ceiling. A deployment that
reads documents of this size needs `HARNESS_MAX_TOKENS` raised; the showcase used
600,000.

## Readiness scoring on messy answers

**A demo of the demo instrument.** `example_instrument()` is six made-up questions and
not a validated index. Sonnet 5.5 wrote 50 fictional organisations' answers, five per
scenario, each scenario a mistake real forms produce. Each set went through
`harness score`. Before is the scorer before PR #7; after is the final `main`. Full
tables: [`RESULTS-before.md`](../showcase/readiness/RESULTS-before.md),
[`RESULTS.md`](../showcase/readiness/RESULTS.md).

| Scenario | Before | After |
|---|---|---|
| Same option selected twice | Counted twice: e.g. 0.684 High | Duplicate dropped and named: 0.623 Medium. All five scores fell, one by a tier |
| Every answer "don't know" | 0.000, tier Low | No score, no tier, status incomplete |
| One dimension left blank | A score from the other dimension alone, e.g. 0.467 Medium | No score, no tier, status incomplete |
| Two or three questions blank | A score | The same score, status partial |
| An option that does not exist | `harness score` exits 1 with a Python traceback | Unchanged |
| Scale value outside 1 to 5 | Clamped without comment | Unchanged |
| "None of these" with real skills | Scored on the real skills | Unchanged |

## The audit's verification table

Each guarantee from the audit's section 6, and what shows it. "Test" is an offline
test on the final `main` (all pass: 523 tests). "Live" used the real API or the real
CLI on 2026-10-17.

| Guarantee | Shown by | Kind |
|---|---|---|
| Anonymous access to output refused when auth is on | `test_released_output_without_a_token_is_refused_when_auth_is_required` | Test |
| Cross-org access refused | `test_org_a_cannot_read_org_b_run`, `test_org_a_cannot_read_org_b_released_output` | Test |
| A pre-approved agent result is held for review | `test_a_pre_approved_agent_result_cannot_skip_required_review`; every showcase artifact is `pending_review` | Test and live |
| Conflicting decisions leave one record | `test_conflicting_approve_and_reject_cannot_both_stand` | Test |
| A verification outage after generation keeps the artifacts and sends the run to review | `test_a_provider_error_during_verification_ends_in_review_not_running`, `..._keeps_the_artifacts_and_usage`; live: the budget run that stopped during verification | Test and live |
| A citation with a changed number or negation is flagged | `test_a_swapped_number_is_not_an_approximate_quote`, `test_added_negation_cannot_pass`, `test_removed_negation_cannot_pass`; the corpus eval above (2,745 altered quotes, 0 accepted) | Test and offline eval of model-written data |
| Location and baseline scope refused | `test_a_scoped_baseline_is_refused_against_an_overall_result`, `test_a_location_only_value_does_not_become_the_total`; live: the Netherlands Red Cross results narrative lists "not calculable (no total): the target is reported only for gender=Female" | Test and live |
| Nominal and unknown measures refused | `test_nominal_labels_produce_no_percentage`, `test_an_unknown_measure_produces_no_percentage` | Test |
| Duplicate readiness answers do not inflate | `test_duplicate_selections_do_not_raise_a_score`; the five duplicate sets above | Test and live CLI |
| An incomplete questionnaire gets no tier | `test_an_empty_submission_is_explicitly_incomplete`, `test_one_answered_question_gets_no_unqualified_tier`; ten sets above | Test and live CLI |
| An oversized upload is refused | `test_an_oversized_upload_is_refused_and_leaves_no_blob_and_no_run`; `harness run` on a 21 MB file exits 2: "exceeds the 20MB upload limit" ([check](../showcase/checks/oversized-upload.txt)) | Test and live CLI |
| A dollar ceiling with no price refuses dispatch | `test_a_dollar_ceiling_with_an_unpriced_model_refuses_dispatch`; live run above, 0 calls | Test and live API |

Firestore-backed behaviour (concurrent decisions across instances, the worker lease) is
covered by tests against the emulator only, and was not exercised here.

## What the provider needed

The run found four problems in the Anthropic adapter, fixed in this branch and in PR #2:

1. **Sampling parameters.** The 5.x models reject `temperature`, `top_p` and `top_k`
   with HTTP 400. The adapter no longer sends them.
2. **Refusals.** A `stop_reason: "refusal"` now raises `ProviderError` with its category
   instead of passing partial text on. No showcase run was refused.
3. **JSON output.** The adapter asked for the schema in the system prompt. Opus and
   Sonnet complied. Haiku 5.5 often replied with the schema itself: 4 of 9 runs in the
   first pass ([`showcase/runs-prompted-schema/`](../showcase/runs-prompted-schema)). The
   adapter now sends `output_config.format` with a strict copy of the schema, and the
   API enforces it.
4. **The verifier's 16-token cap**, described under the quorum. Fixed in PR #6.

## What the receipts prove, and what they do not

They prove:

- The harness ran these agents against these models on these documents, and wrote these
  outputs. Each receipt has the run id, model, effort, token counts, cost, call count,
  review state and the verdict on every claim.
- The costs are the harness's own: `run.usage`, priced with the dated price file.
- The ceilings stop runs and record the overshoot, and checking that runs out of budget
  keeps the work.

They do not prove:

- **That the bill matches.** The receipts were not reconciled with Anthropic's invoice.
  A call that failed in transport after it was billed would be missing from the ledger.
- **That the outputs are good.** No person has reviewed them yet, and no model graded
  them on purpose.
- **That a resolved quote supports its claim.** The free check finds the text. Only the
  opt-in cross-check, and the reviewer, judge support.
- **That the prices are current.** They are list prices on 2026-10-17.
- **That the corpus is natural.** The mechanical check proves each edit has the right
  shape, not that every altered quote reads as a model would write it.

## Reproduce it

See [`showcase/README.md`](../showcase/README.md). In short:

```bash
make install
set -a; source .env; set +a          # ANTHROPIC_API_KEY, and IATI_API_KEY for results
python -m showcase.sources
python -m showcase.run_agents --models claude-haiku-5-5 --dry-run
python -m showcase.run_agents --models claude-opus-5-5 --effort medium
```

The price file can also be given to the CLI as an environment line, for any agent:

```bash
export HARNESS_PRICES='claude-haiku-5-5=0.10/0.50,claude-sonnet-5-5=2.00/10.00,claude-opus-5-5=4.00/20.00'
```

That line has no long-prompt rate, so it under-prices Haiku above 100,000 tokens.
`showcase/harness_setup.py` has a price book that includes it.

## Attribution

The sources are the work of the World Health Organization, the International Federation
of Red Cross and Red Crescent Societies, Pathfinder International, ALNAP/ODI and the
World Bank, used under their licences (see
[`showcase/SOURCES.md`](../showcase/SOURCES.md)). This showcase is not created or
endorsed by any of them. The IATI data is published by The Netherlands Red Cross, World
Bank Trust Funds and Cordaid.

## Noticed, not fixed

Problems this run found in modules other sessions own. Each is a follow-up.

- **PDF line-break hyphens.** Extraction keeps "com- munity", so a correct quote of
  "community" is rejected. The rejection reason says "word order differs", which is
  wrong. (`documents/`, `verification/grounding.py`)
- **One bad PDF page loses the whole document.** On WDR 2018, pypdf raises
  `LimitReachedError` on page 155 and `extract` raises `DocumentError` ("looks corrupt")
  for all 240 pages. (`documents/extraction.py`)
- **The negation-context check reads across a line break**, so a results sheet line
  ending in "none" makes the next line's exact quote uncertain. (`verification/`)
- **An artifact with no claims passes with nothing checked.** Two real runs returned no
  claims. (`core/runner.py`, review)
- **An unknown readiness option crashes `harness score`** with a traceback, and a scale
  value outside its range is clamped without comment. (`readiness/`, `cli.py`)
- **The quorum's Opus votes on short structured quotes** stayed "unsure" after the cap
  fix. Worth a look at whether 1,024 tokens is enough at Opus's default effort.
  (`verification/verifier.py`)
- **`harness run` has no provider timeout setting.** A 300,000-token document on Opus
  took up to 150 seconds, past the 60-second default. The showcase passes
  `timeout=900`. (`providers/`, `config.py`)
