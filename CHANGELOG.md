# Changelog

Notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the version stays below 1.0, the interfaces may change in a minor release.
Pin an exact version if you depend on them.

## [Unreleased]

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

[Unreleased]: https://github.com/QriusAI-Foundation/nonprofit-agent-harness/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/QriusAI-Foundation/nonprofit-agent-harness/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/QriusAI-Foundation/nonprofit-agent-harness/releases/tag/v0.1.0
