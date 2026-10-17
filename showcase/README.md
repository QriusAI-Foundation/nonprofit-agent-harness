# Showcase: the harness against real Claude models

Real runs of the harness on 2026-10-17, with the receipts the harness itself wrote.
The write-up, the tables, and what the runs do and do not prove are in
[docs/showcase.md](../docs/showcase.md).

## What is here

| Path | What it is |
|---|---|
| `runs/<agent>/<source>/<model>.md` | Each artifact exactly as the agent produced it, still awaiting human review |
| `runs/<agent>/<source>/<model>.receipt.json` | That run's id, model, effort, tokens, cost, calls, review state, and the citation check's verdict on every claim |
| `runs-prompted-schema/` | The first pass, before the Anthropic adapter used structured outputs. Kept because it shows Haiku 5.5 answering with the schema instead of the content |
| `quorum/` | Cross-model verification runs: three reviewers on three models, before and after the citation fix |
| `budget/` | Runs that trip a ceiling on purpose |
| `readiness/` | 50 fictional answer sets scored with the demo instrument, and what the scorer reported |
| `corpus_raw/` | Raw model replies the quotation-integrity corpus was built from |
| `ledger.jsonl`, `SPEND.md` | Every harness run's usage, and the totals |
| `TABLES.md` | Tables generated from the receipts by `python -m showcase.report` |
| `prices-2026-10-17.json` | The dated price book these runs used. Deployer data, not a package default |
| `SOURCES.md` | Every source document: URL, licence, SHA-256, attribution |
| `RESEARCH.md` | Why the corpus was generated rather than adopted |

## Reproduce it with your own key

Runs cost real money. The whole showcase cost the total in `SPEND.md`; one agent over
one document costs between USD 0.002 and 1.50, depending on model and document length.

```bash
make install
cp .env.example .env            # then set ANTHROPIC_API_KEY, and IATI_API_KEY for results
set -a; source .env; set +a

python -m showcase.sources                                   # download and verify sources
python -m showcase.run_agents --models claude-haiku-5-5 --dry-run   # see the estimate
python -m showcase.run_agents --models claude-opus-5-5 --effort medium
python -m showcase.run_agents --models claude-sonnet-5-5,claude-haiku-5-5
python -m showcase.quorum --label mine
python -m showcase.budget_ceiling
python -m showcase.readiness_demo generate && python -m showcase.readiness_demo score
python -m showcase.quotation_corpus generate --calls 2 && python -m showcase.quotation_corpus build
python -m showcase.report > showcase/TABLES.md
```

Free and offline:

```bash
python scripts/quotation_eval.py              # the citation check over the corpus
python -m showcase.readiness_demo score       # re-score the committed answer sets
python -m showcase.report                     # rebuild the tables from the receipts
```

Every script refuses to start a step that would take the ledger past
`SPEND_CAP_USD` in `harness_setup.py`. Change the cap, and the price file, for your own
deployment. Prices change: check them before you trust a cost column.

## What a nonprofit can take from this

- `examples/board_brief.py`, `examples/funder_report.py` and
  `examples/results_narrative.py` are short agents you can copy. Each attaches claims
  with verbatim quotes, so the free citation check runs on every output.
- `showcase/harness_setup.py` shows the deployer's side: a price book, a provider with a
  longer timeout, ceilings raised for long documents, and a ledger.
- The receipts show what each model costs on documents of 100,000 to 330,000 tokens.
