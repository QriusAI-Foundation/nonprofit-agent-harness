# Security Policy

## Reporting a vulnerability

Email **sanmaya@qriusai.org** with the details. Please do not open a public issue for a
security problem.

Include what you did, what happened, and what you expected. A proof of concept helps.
We will acknowledge within a week and keep you updated until it is resolved.

## Scope

This project is alpha software. Treat the following as known properties rather than
vulnerabilities:

- **Auth is off by default.** With `HARNESS_AUTH_REQUIRED=false`, the API is a single
  shared workspace with no caller identity. That is intended for local use. Turn auth on
  before exposing a deployment.
- **Redaction is a pattern matcher, not anonymisation.** `Redactor` masks common direct
  identifiers. It will miss things. It is a reduction in exposure, not a guarantee, and
  it is not a lawful basis for processing personal data.
- **The review gate is an application-level control.** It governs what the harness
  releases. It cannot stop code that bypasses the harness and calls a provider directly.

## Handling data

- Secrets belong in environment variables or a secret manager, never in a committed
  file. `.env` is gitignored.
- The admin config endpoint reports whether secrets are set, never their values.
- Uploaded documents are stored under the organisation that uploaded them. There is no
  automatic retention limit in the application; the Terraform bucket sets one at the
  infrastructure level.
