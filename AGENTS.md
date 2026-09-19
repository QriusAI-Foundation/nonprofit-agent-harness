# Notes for AI coding assistants

Context for an assistant working in this repository.

## What this is

A harness, not a framework and not an application. It provides the machinery around an
agent: run lifecycle, budget ceilings, human review, storage, documents, auth, and an
HTTP surface. The agent itself belongs to whoever is using this.

## Rules that are load-bearing

1. **A fresh clone must run with no cloud account, no API key, and no optional extras.**
   `pip install -e . && harness run examples.summarizer:SummarizerAgent file.txt` has to
   work. CI enforces this in the `offline` job. Any change that breaks it is wrong.
2. **Agents only touch `RunContext`.** Do not give an agent a store, a config object, or
   an environment variable. If an agent needs something new, add it to `RunContext`.
3. **Review is default-on.** Never change `Agent.requires_review` to default `False`, and
   never add a path that releases an artifact without writing a `Review` record.
4. **Budget accounting is add-then-check.** See `BudgetGuard.record`. Do not "fix" it to
   check first; under-reporting real spend is the bug that ordering prevents.
5. **No invented pricing.** `PriceBook` is empty by default on purpose. Do not commit a
   table of model rates; they go stale and end up in someone's grant report.
6. **The bundled readiness instrument is a demo.** Do not present it as a validated
   index, and do not add a real organisation's calibrated instrument to this repo.
7. **Citation checking must stay free.** `GroundingVerifier` with `passes=0` makes no
   model call. Do not add one to the default path.
8. **A missing quantity rejects a fuzzy citation match.** See `is_quantity` in
   `verification/grounding.py`. Loosening this re-admits the swapped-number
   fabrication the check exists to catch; `test_a_swapped_number_is_not_an_approximate_quote`
   fails if you do.
9. **Verification reports to a human, it does not judge.** A failed claim flags an
   artifact for review. It must never fail the run, delete work, or auto-reject.
10. **Results arithmetic honours direction, baselines, and measure.** See
    `results/analysis.py`. An indicator with `ascending=False` improves downward;
    progress is measured from the baseline, not from zero; only `Measure.UNIT` values
    may be summed, and `aggregatable=False` is the publisher's decision, not a hint.
    Each has a test named after the failure it prevents.
11. **A calculation that cannot be made says so.** Return a `NotCalculable` reason
    rather than zero, `None` alone, or a guess. A missing actual is not zero.
12. **Never pair IATI's flattened arrays across different lengths.** The Datastore
    loses which element of one list belongs to which element of another. Some
    activities return matching lengths by coincidence, so a wrong implementation looks
    correct in testing and mis-assigns in production. Read `datasources/iati_results.py`
    before touching it, and prefer `iati_xml.py`, where the nesting survives.
13. **A code is only meaningful inside its vocabulary.** See `codelists.py`. Resolving
    a publisher's own sector numbering against the DAC list attaches a real and wrong
    name to it.
14. **Codelists stay bundled.** Fetching them at runtime would put a network call, a
    key and a quota in the path of reading a code.

## Layout

```
src/nonprofit_harness/
  core/        agent contract, run types, registry, runner
  providers/   model seam: echo (offline default), google
  guardrails/  budget ceilings, redaction
  review/      the approval gate
  verification/ citation grounding + optional cross-model checking
  readiness/   scoring engine + instrument schema
  results/     IATI-shaped results model + deterministic M&E arithmetic
  datasources/ IATI: search (flattened, lossy), XML (full), bundled codelists
  storage/     protocols, in-memory, GCP
  auth/        Google ID token verification, session tokens
  api/         FastAPI app, routes, schemas
examples/      one reference agent
tests/         offline, no network
```

## Working here

```bash
make install
make test
make lint
```

Add a test for any guarantee you change. Comments explain why, not what.
