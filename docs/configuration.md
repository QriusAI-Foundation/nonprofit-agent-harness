# Configuration

Every setting is an environment variable. Defaults are chosen so a fresh clone runs
offline, for free, with review switched on. Loosening any of that is a deliberate act.

Run `harness check` to print what is actually in force, along with any warnings.

## Model

| Variable | Default | Meaning |
|---|---|---|
| `HARNESS_PROVIDER` | `echo` | Which adapter to use. See the table below |
| `HARNESS_MODEL` | provider default | Model name to use |
| `OPENAI_API_KEY` | unset | For any OpenAI-compatible server |
| `OPENAI_BASE_URL` | vendor default | Point the same adapter at another server |
| `ANTHROPIC_API_KEY` | unset | For Claude models |
| `GOOGLE_API_KEY` | unset | Gemini API key. Leave unset to use Vertex AI instead |
| `GOOGLE_CLOUD_PROJECT` | unset | Vertex AI project |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | Vertex AI region |

`echo` makes no network call and returns deterministic text. It exists so that tests,
continuous integration, and a first local run cost nothing.

### Which providers exist

| `HARNESS_PROVIDER` | Goes to | Needs |
|---|---|---|
| `echo` | Offline, deterministic | nothing |
| `openai` | api.openai.com | `OPENAI_API_KEY`, `HARNESS_MODEL` |
| `groq`, `together`, `openrouter` | that vendor's endpoint | `OPENAI_API_KEY`, `HARNESS_MODEL` |
| `ollama`, `local` | localhost:11434 | `HARNESS_MODEL` |
| `vllm` | localhost:8000 | `HARNESS_MODEL` |
| `anthropic`, `claude` | api.anthropic.com | `ANTHROPIC_API_KEY` |
| `google`, `gemini`, `vertex` | Vertex AI or the Gemini API | the `adk` extra |

Everything except Google and Anthropic is one adapter speaking the OpenAI chat API, so
any server implementing it works by setting `OPENAI_BASE_URL`, whether or not it has a
named alias here.

No provider needs an extra except Google. The others speak HTTP directly using the
`httpx` the harness already depends on, so a plain install reaches all of them.

### Two differences worth knowing

**Structured output is not equally strict.** OpenAI-compatible servers get
`response_format` with your JSON schema, which most enforce. Anthropic has no
equivalent, so the schema is requested in the system prompt and the reply is not
guaranteed to match. Validate what comes back rather than assuming, otherwise an agent
works on one provider and fails on another for reasons that look random.

**Vertex AI has no API key at all.** It authenticates with the service account, so
there is no long-lived credential to leak. Prefer it for anything deployed on GCP.

### Keeping data on your own hardware

Beneficiary data that must not leave the building can go to a local model:

```bash
export HARNESS_PROVIDER=ollama
export HARNESS_MODEL=llama3.1
```

Nothing else changes. Agents, review, budget ceilings, and verification all behave the
same, because the model layer is the only thing that moved.

## Storage

| Variable | Default | Meaning |
|---|---|---|
| `HARNESS_STORAGE` | `memory` | `memory` or `gcp` |
| `HARNESS_DOCUMENTS_BUCKET` | unset | Cloud Storage bucket, required when `gcp` |

`memory` keeps everything in the process and loses it on restart. That is correct for
development and wrong for production.

## Budget ceilings

All three apply per run. Any one of them stops the run when it trips.

| Variable | Default | Meaning |
|---|---|---|
| `HARNESS_MAX_COST_USD` | unset | Cost ceiling in USD |
| `HARNESS_MAX_TOKENS` | `200000` | Combined input and output tokens |
| `HARNESS_MAX_CALLS` | `50` | Model calls |

Each accepts a number, or `none`, `unlimited`, or `off` to switch that ceiling off.
`0` means zero, not "unset".

Cost ceilings only work once pricing is configured, because published rates change too
often to hardcode. Token and call ceilings need no pricing and work immediately, which
is why they carry the defaults.

To price a model, supply a `PriceBook`:

```python
from nonprofit_harness.providers import PriceBook
from nonprofit_harness.providers.google import GoogleProvider

prices = PriceBook().set("your-model", input_per_1m=0.30, output_per_1m=2.50)
provider = GoogleProvider(model="your-model", prices=prices)
```

**These ceilings bound one run, not a total.** Many small runs can add up without any
individual ceiling tripping. A deployment reachable by people you do not know needs
quota and rate limiting on top. See [security.md](security.md).

## Verification

| Variable | Default | Meaning |
|---|---|---|
| `HARNESS_VERIFY_CLAIMS` | `true` | Check cited quotes against the source |
| `HARNESS_VERIFY_PASSES` | `0` | Cross-check passes per claim |
| `HARNESS_VERIFY_MODELS` | empty | Models to rotate across passes |

Claim checking costs nothing and is on. Cross-checking spends model calls against the
run's own budget, so it is off until you ask for it.

Use an odd number of passes, since a tie resolves as inconclusive. List at least as
many distinct models as passes. Several passes on one model agree with themselves far
more readily than independent reviewers would, and `harness check` warns when the
configuration implies otherwise.

## Data handling

| Variable | Default | Meaning |
|---|---|---|
| `HARNESS_REDACT_INPUTS` | `false` | Mask direct identifiers before text reaches a model |
| `HARNESS_RUN_TIMEOUT_SECONDS` | `3600` | How long a run may sit in `running` before a restart treats it as abandoned |

Redaction is a pattern matcher for emails, phone numbers, and similar identifiers. It
reduces exposure. It is not anonymisation and it is not a lawful basis for processing
personal data.

## Authentication

| Variable | Default | Meaning |
|---|---|---|
| `HARNESS_AUTH_REQUIRED` | `false` | Require a session token on every request |
| `HARNESS_GOOGLE_CLIENT_ID` | unset | Google Sign-In client id |
| `HARNESS_JWT_SECRET` | unset | Session signing secret, 32 bytes or more |
| `HARNESS_JWT_TTL_SECONDS` | `43200` | Session lifetime |
| `HARNESS_ADMIN_EMAILS` | empty | Comma-separated admin allowlist |

With auth off, the API is a single shared workspace with no caller identity. That is
intended for a laptop. **Turn it on before exposing a deployment to anyone.**

The admin allowlist is exact-match and case-insensitive. There are no domain wildcards,
deliberately, because a wildcard on a shared email domain is an accident waiting to
happen.

## Agents and clients

| Variable | Default | Meaning |
|---|---|---|
| `HARNESS_AGENTS` | empty | Comma-separated `module:ClassName` to register at startup |
| `HARNESS_CORS_ORIGINS` | empty | Comma-separated browser origins |
| `LOG_LEVEL` | `INFO` | Standard library log level |

## Validation

`HarnessConfig.validate()` returns the problems that would bite in production without
raising. The API logs them at startup, `harness check` prints them, and
`GET /v1/admin/config` returns them.

It reports, among others:

- auth required but no client id or signing secret configured
- `gcp` storage with no bucket set
- no budget ceiling of any kind, so a run can consume without limit
- cross-check passes configured without enough distinct models to make them independent
- an even number of cross-check passes, where ties are possible

The admin endpoint reports whether each secret is set, never its value. A configuration
endpoint that echoes a signing key is a configuration endpoint that leaks one.
