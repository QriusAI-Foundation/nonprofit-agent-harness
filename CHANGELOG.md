# Changelog

Notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the version stays below 1.0, the interfaces may change in a minor release.
Pin an exact version if you depend on them.

## [Unreleased]

## [0.4.0]

An independent source audit of 0.3.0 (2026-09-30, commit f8c25de) reported thirteen
findings. This release closes all thirteen, and adds the first recorded runs of the
harness against real models: outputs, receipts, and a labelled test set, in `showcase/`.

### Security

- **Output routes require a login when auth is on.** `GET /v1/runs/{id}` and
  `GET /v1/review/{id}/released` went without `get_principal`, so a known run id was
  enough to read output. Every lookup by id now goes through one membership rule
  (`can_access`), with `authorized_run` and `authorized_blob` dependencies. Another
  organisation's run, blob, or review answers 404, the same as a missing one. (F01, F02)
- **Membership is a server-side record.** Sign-in no longer takes an organisation from
  the request body; a body `org_id` that differs from the record gets 403. A first
  sign-in joins `HARNESS_DEFAULT_ORG` (default `org_default`; set it empty to admit only
  enrolled users). Admins enrol people through `PUT /v1/admin/members/{email}`, and
  admin status comes from `HARNESS_ADMIN_EMAILS` on every request, never from a token
  claim. A membership change reaches a session at its next sign-in. (F02)
- **The harness owns review state.** Decision state that arrives with an agent's
  result is discarded on the way in; an artifact supplied as approved is not approved.
  Release requires a coherent, attributed review record, and a failed verification
  still blocks automatic release. Reviewer names starting with `system:` are
  reserved. (F03)
- **Uploads are bounded before they are read whole.** An upload is refused in flight
  past `HARNESS_MAX_UPLOAD_BYTES` (20 MB, HTTP 413). Extraction stops at
  `HARNESS_MAX_PDF_PAGES` (300, marked as truncated), `HARNESS_MAX_DOCX_EXPANDED_BYTES`
  (50 MB, checked from the zip directory before any member is read),
  `HARNESS_MAX_DOCUMENT_CHARS` (2,000,000) and `HARNESS_EXTRACT_TIMEOUT_SECONDS` (120).
  A malformed document is a controlled error, and a refused upload leaves no blob. (F13)

### Fixed

- **Review decisions are atomic.** `Run` carries a `version`; `RunStore.save` is
  compare-and-set and raises `StaleRun` (409) on a stale copy; `RunStore.update` applies
  a change under a lock in memory and a transaction in Firestore. Two reviewers can no
  longer overwrite each other. The same decision by the same reviewer again is a no-op
  that keeps the original attribution; a different decision on a decided artifact is a
  `ReviewConflict` (409) that names who decided first. (F06)
- **Citation matching no longer accepts altered quotes.** Exact matches are on word
  boundaries, so "reached 5" is not found inside "reached 50". Approximate matches
  follow bounded rules (punctuation, a dropped or added article, a few interchangeable
  function words) and are refused when a number, a negation, or the word order changes.
  A quote that resembles the source but falls outside those rules is held for a person
  as `citation_uncertain`. The cross-check allows 1,024 output tokens per vote and reads
  the vote from prose. On a 3,966-item labelled corpus the share of altered quotes
  rejected went from 35.8% to 100%. (F07)
- **Completed work survives a verification failure.** Finished artifacts and usage are
  stored before claim verification runs. Any failure during verification marks the
  unreached artifacts as stopped short, with the reason, and holds the run for review;
  a run no longer stays `running` with nothing saved. (F05)
- **Interrupted runs are recovered on a schedule, with leases.** A worker records a
  lease on the run it executes and renews it; recovery runs at startup and every
  `HARNESS_REAP_INTERVAL_SECONDS`, pages through every running run, and resolves only
  those whose lease lapsed, so another worker's live job is never failed. A run that
  died during verification goes to review with its work; one that died while
  generating is failed as abandoned. Completed work that lands after an abandonment mark
  is kept. Counts are in the admin effective-config response. (F12)
- **Results arithmetic respects scope.** A measurement's scope is its dimensions and its
  location; a figure for one district is no longer the programme's total, totals are
  chosen by scope and never by input order, and two disagreeing totals are refused. A
  baseline for a different population is refused with the mismatch named. (F09, F10)
- **Nominal, ordinal, and unknown measures permit no ratios.** `Measure.UNKNOWN` records
  a code the parser does not know instead of assuming a count; nominal and ordinal values
  get no achievement percentage and are never summed. New `NotCalculable` reasons:
  `NO_TOTAL`, `CONFLICTING_TOTALS`, `BASELINE_SCOPE_MISMATCH`, `NOMINAL_LABELS`,
  `ORDINAL_SCALE`, `UNKNOWN_MEASURE`, with `Achievement.detail` saying which figures
  were involved. (F11)
- **Readiness scores cannot be inflated.** Repeated multi-select values count once and
  are reported as dropped. An overall score and tier are issued only when every
  dimension has a scored answer; otherwise the result is `incomplete`, with `overall`
  null and no tier. `partial` means every dimension is covered but some questions are
  blank. Coverage per dimension, and the distinction between excluded and unanswered,
  are in the result. (F08)
- **Budget ceilings mean what they say.** `BudgetedProvider` runs three named steps:
  `admit` (the call check), `reserve` (an estimate of the input, the output limit
  lowered to the tokens and dollars left, refusal when nothing is left), and `record`
  (add-then-check, unchanged). A response cut off at a budget-lowered limit stops the
  run as incomplete. Unknown cost is not zero: `Usage` counts `unpriced_calls` and names
  `unpriced_models`, the CLI prints `cost: unknown (no price for ...)`, and a dollar
  ceiling refuses an unpriced model before dispatch. `HARNESS_PRICES=model=in/out,...`
  supplies rates from the environment; there is still no built-in rate table. A failed
  call banks the usage it was billed for. (F04)
- **The Anthropic adapter works with the Claude 5.x models.** Default
  `claude-haiku-5-5`; no sampling parameters are sent (the 5.x models reject them);
  `HARNESS_MODEL` and `ANTHROPIC_EFFORT` are honoured; a refusal raises `ProviderError`
  with its category and billed usage; JSON schemas go through structured outputs.

### Added

- **A showcase of real runs** (`showcase/`, `docs/showcase.md`): three example agents
  (`board_brief`, `funder_report`, `results_narrative`) over six openly licensed
  documents and three IATI activities on Haiku 5.5, Sonnet 5.5, Opus 5.5, and
  Fable 5.1, with tokens, cost, and citation outcomes per run; a cross-model quorum; the
  budget ceilings tripped on purpose; the audit's verification table; and a CC0
  quotation-integrity corpus of 3,966 items with `scripts/quotation_eval.py`.
- `RunOut.metadata`, `Run.version`, `RunStore.update`, `Verdict.label` and
  `Verdict.support_checked`, `Usage.describe_cost()`, `Measure.UNKNOWN`, `Scope`,
  readiness `status` and `coverage`, `ExtractionLimits`, `core/lease.py`.

### Breaking changes

- A sign-in body `org_id` that differs from the user's record gets 403; with auth on,
  the two output routes need a token, and other organisations' objects answer 404.
- A custom `RunStore` must implement `update()`; `save()` must honour `version`.
- `PriceBook.cost()` returns `None` for an unknown model; `UsageOut.cost_usd` is
  nullable, with `priced_cost_usd` beside it.
- `Measure.from_code` maps unknown codes to `UNKNOWN`, not `UNIT`; nominal and ordinal
  indicators get no percentage; a location-only figure is no longer a total.
- Readiness results can have `overall` null and `tier` empty.
- Verification: new outcome `citation_uncertain`; `verified` now carries
  `support_checked=false` and the label "resolved (support not checked)" unless the
  cross-check ran.
- A `ReviewGate` subclass overriding `submit` or `auto_release` is bypassed for runner
  results; the runner calls the module functions those methods use.
- Oversized uploads answer 413, not 400.
- The Anthropic adapter ignores `temperature`.

## [0.3.0]

Everything the IATI thread was blocked on. Results now come back grouped under their
own indicators, with disaggregated values attached and codes that read as words.

### Added

- **Results read from an activity's published XML**, through `IatiClient.results()` and
  `results_from_xml()`. This recovers everything the flattened path has to refuse.

  The XML keeps the nesting: results hold their own indicators, and every measurement
  keeps the slice it describes. On the same activity where the flattened rows yield no
  values at all, the XML gives `{'female': 2965.0, 'male': 2049.0}` and
  `{'18+': 2692.0, 'under 18': 2322.0}`, with all seven results correctly grouped. Both
  paths cost one call, so prefer the XML; searching still goes through the flattened
  collection, because you cannot search XML you have not fetched.

  Parsed with the standard library, so no new dependency. External entities are not
  resolved and DTD entities are not expanded, and a size ceiling covers the rest, since
  the input is someone else's file.

  Where `ascending` is absent the indicator records that its direction was assumed
  rather than published, so a caller can tell the difference.

- **Which disaggregations a programme reports by**, through `dimensions_used` and
  `disaggregated` on an `IatiResults`. You get that an activity breaks its figures down
  by sex and age, and not which number belongs to which slice.

  That distinction is forced by the data. Checked against three publishers reporting
  genuine breakdowns: 26 values against 52 dimensions, 8 against 28, 16 against 21. The
  count per measurement varies inside one activity, so nothing says which dimension
  belongs to which number, and the clean 2:1 case is the dangerous one because zipping
  would look correct there and mis-assign everywhere else.

  A heavily disaggregated activity may therefore yield no values at all: one real
  activity has 7 indicator rows against 26 reported actuals, which are dropped rather
  than misattributed, with a warning saying so. Placeholder dimensions are ignored,
  because one real publisher ships every one of them as the literal string `TBD`.

  `disaggregated` being false is itself a finding. A programme reporting only totals
  cannot say who it reached.

- **IATI codes resolve to readable names.** An activity reached an agent saying
  `Sectors: 11220` and `Recipient countries: PS`, which is precise and useless. Sector,
  Country, ActivityStatus, Region and OrganisationType now read as words, with the code
  kept alongside because that is what anyone cross-referencing published data searches
  for.

  The lists are bundled rather than fetched, so this costs no network, no key, and none
  of the Datastore's 100 calls a week. 631 entries in about 22KB, regenerated by
  `scripts/refresh_codelists.py`, which records the source and the date so bundled data
  cannot go stale silently.

  A publisher's own narrative always wins over the codelist. And `sector_vocabulary` is
  now requested so that a sector reported against a publisher's own numbering is left
  as a bare code: their `11220` means whatever they say it means, and calling it
  "Primary education" would be a real and wrong name.

## [0.2.0]

The release that makes two claims in the README actually true: that the harness is
usable without Google, and that it is scoped to this sector rather than generic.

### Added

- **Providers beyond Google.** OpenAI, Anthropic, Groq, Together, OpenRouter, vLLM, and
  local models through Ollama. The README claimed the harness was usable without Google
  while Google was the only real adapter, which was not true of a nonprofit holding
  donated credits elsewhere or required to keep data on its own hardware.

  Written against `httpx`, which the harness already depends on, so none of them adds
  anything to an install. Everything except Google and Anthropic is one adapter
  speaking the OpenAI chat API, so any server implementing it works through
  `OPENAI_BASE_URL` whether or not it has a named alias.

  Two differences are documented rather than smoothed over: structured output is
  enforced by OpenAI-compatible servers and only requested of Anthropic, and a
  self-hosted alias never falls back to a public endpoint.

- **Results and indicators.** The sector's own model of whether a programme worked,
  structured to match the IATI Standard's `result` element rather than invented, plus
  the deterministic arithmetic over it: achievement against target, progress from
  baseline, disaggregation and coverage, budget utilisation and unit cost. No model
  calls.

  Three things it refuses to get wrong, each of which otherwise produces a confident
  and incorrect number. Direction, so that beating a descending target is not scored
  as a shortfall. Baselines, so a programme is credited with the distance it moved
  rather than with where it started. Aggregation, so percentages are not summed and a
  publisher's own not-aggregatable flag is honoured. Totals refuse rather than
  filtering quietly, because a total that dropped half its inputs looks complete.
- **Indicators can be read from IATI** through `IatiClient.indicators()`, rebuilt into
  that model. The Datastore flattens a nested activity into parallel arrays, and IATI's
  guidance is explicit that the flattening is lossy. Confirmed live: a real activity
  returns 16 result titles against 301 indicator rows with nothing relating them, while
  other activities happen to return matching lengths and make the association look
  recoverable. Indicators are therefore reconstructed and results are reported
  unattached, alongside warnings for any field dropped for length mismatch and for
  indicators whose direction was not published.

## [0.1.1]

### Security

- **Credentials are stripped from provider error text.** On the API-key path the SDK
  builds request URLs containing `?key=...`, and an error could quote the URL it failed
  on. That text reached logs and, through the API's error handler, an HTTP response
  body. Both a key embedded in any URL and the configured key itself are now redacted.
  Vertex AI deployments were never affected, because they authenticate with a service
  account and no key appears in a URL.

### Fixed

- **Firestore composite indexes are defined in Terraform**, and a missing one now
  raises a `StorageError` that keeps the link Firestore supplies to create it. Listing
  runs filters on one field and orders by another, which needs a composite index that
  Firestore does not create on its own. The in-memory backend has no such rule, so this
  only appeared on a real deployment.
- **Runs abandoned by a stopped process are failed at startup.** Runs execute in the
  web process, so a recycled instance left a record in `running` that nothing would
  ever update and a poller would wait on forever. The threshold is
  `HARNESS_RUN_TIMEOUT_SECONDS`, defaulting to an hour, and must exceed the longest run
  you expect so a run in progress elsewhere is not reaped.

### Changed

- The quickstart leads with `pip install nonprofit-agent-harness` now that the package
  is published.
- `__version__` is read from installed metadata rather than hardcoded, so it cannot
  drift from the packaged version at release time.

## [0.1.0]

First release, published to PyPI as `nonprofit-agent-harness`.

### Added

- **Agent contract.** `Agent`, `RunContext`, and `AgentResult`. An agent implements
  one method and receives one object, so the same agent runs offline in a test and in
  production unchanged.
- **Review gate.** Artifacts are held in `pending_review` until a person decides.
  Every decision is recorded, including automatic releases.
- **Claim verification.** Cited quotes are checked against the run's own inputs, with
  no model call. An optional cross-check has several models re-derive a claim from its
  evidence alone. A quote whose quantity does not appear in the source is rejected.
- **Budget ceilings.** Per-run limits on cost, tokens, and calls. Token and call
  limits work before any pricing is configured.
- **Readiness scoring.** An engine for AI-readiness instruments: explicit per-question
  direction, excluded options, weighted dimensions, geometric-mean aggregation, and
  tier bands. The questionnaire is data you supply.
- **Providers.** An offline deterministic provider as the default, and Gemini through
  Vertex AI or the Gemini API.
- **Storage.** In-memory by default, with Firestore and Cloud Storage behind the same
  interface.
- **Documents.** PDF, DOCX, and text extraction.
- **IATI data source.** Reads activity data published to the International Aid
  Transparency Initiative standard and turns it into harness input. Fetching stays on
  the caller's side, so agents still receive documents and nothing else. Verified
  against the live API: a plain search term is expanded across text fields, because
  the Datastore declares no default search field and rejects an unqualified query.
  Repeated codes are deduplicated and dates are labelled with their type.
- **Guardrails.** Optional masking of direct identifiers before text reaches a model.
- **Auth.** Google Sign-In verification and harness-issued session tokens, off by
  default.
- **HTTP API and CLI.** FastAPI surface for runs, uploads, review, readiness, and
  webhooks, plus a `harness` command.
- **Deployment.** Dockerfile and Terraform for Cloud Run, scaled to zero.

### Known gaps

- Budget ceilings bound a single run, not a total across runs. A publicly reachable
  deployment needs quota and rate limiting on top.
- Runs execute in-process, so an instance restart can leave a run in `running`.
- Firestore listing needs a composite index before the GCP backend is used in anger.

[Unreleased]: https://github.com/QriusAI-Foundation/nonprofit-agent-harness/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/QriusAI-Foundation/nonprofit-agent-harness/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/QriusAI-Foundation/nonprofit-agent-harness/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/QriusAI-Foundation/nonprofit-agent-harness/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/QriusAI-Foundation/nonprofit-agent-harness/releases/tag/v0.1.0
