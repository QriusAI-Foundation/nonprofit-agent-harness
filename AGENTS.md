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

## Layout

```
src/nonprofit_harness/
  core/        agent contract, run types, registry, runner
  providers/   model seam: echo (offline default), google
  guardrails/  budget ceilings, redaction
  review/      the approval gate
  readiness/   scoring engine + instrument schema
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
