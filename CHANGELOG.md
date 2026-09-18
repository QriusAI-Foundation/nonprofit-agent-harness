# Changelog

Notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the version stays below 1.0, the interfaces may change in a minor release.
Pin an exact version if you depend on them.

## [Unreleased]

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

[Unreleased]: https://github.com/QriusAI-Foundation/nonprofit-agent-harness/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/QriusAI-Foundation/nonprofit-agent-harness/releases/tag/v0.1.0
