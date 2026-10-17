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
| `ANTHROPIC_EFFORT` | model default | Claude depth: `low`, `medium`, `high`, `xhigh`, `max` |
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
| `anthropic`, `claude` | api.anthropic.com, `claude-haiku-5-5` by default | `ANTHROPIC_API_KEY` |
| `google`, `gemini`, `vertex` | Vertex AI or the Gemini API | the `adk` extra |

Everything except Google and Anthropic is one adapter speaking the OpenAI chat API, so
any server implementing it works by setting `OPENAI_BASE_URL`, whether or not it has a
named alias here.

No provider needs an extra except Google. The others speak HTTP directly using the
`httpx` the harness already depends on, so a plain install reaches all of them.

### Three differences worth knowing

**Structured output is not equally strict.** OpenAI-compatible servers get
`response_format` with your JSON schema, which most enforce. Anthropic has no
equivalent, so the schema is requested in the system prompt and the reply is not
guaranteed to match. Validate what comes back rather than assuming, otherwise an agent
works on one provider and fails on another for reasons that look random.

**Claude takes no sampling parameters.** The Claude 5.x models reject `temperature`,
`top_p` and `top_k` with HTTP 400, so the Anthropic adapter never sends them and every
call runs at the model's default. An agent's `temperature` argument is accepted and
ignored for this provider. Depth is set with `ANTHROPIC_EFFORT` instead. A response the
model refuses raises a `ProviderError` naming the refusal category, and the run fails
rather than keeping a partial answer.

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
| `HARNESS_MAX_COST_USD` | unset | Cost ceiling in USD. Needs a price for every model the run calls |
| `HARNESS_MAX_TOKENS` | `200000` | Combined input and output tokens |
| `HARNESS_MAX_CALLS` | `50` | Model calls |
| `HARNESS_PRICES` | unset | Model rates in USD per 1M tokens, `model=input/output`, comma separated |

Each ceiling accepts a number, or `none`, `unlimited`, or `off` to switch it off.
`0` means zero, not "unset".

### What each ceiling does

Every model call goes through three steps, in this order.

1. **Call check, before the call.** A call that would exceed `HARNESS_MAX_CALLS` is
   not sent. The other ceilings are checked against what is already spent at the same
   time, so a run that broke one cannot make another call.
2. **Reservation, before the call.** The harness estimates the prompt's input tokens as
   its character count divided by 6. That is an estimate, and a low one on purpose:
   English text averages about 4 characters per token, so the check refuses only a
   prompt that almost certainly does not fit. Then:
   - if the estimate leaves no tokens under `HARNESS_MAX_TOKENS`, the call is not sent;
   - otherwise the output limit sent to the provider is lowered to the tokens left after
     the estimate. An answer that uses all of a lowered limit was cut short, so its
     usage is recorded and the run stops at the ceiling instead of passing on a fragment;
   - with a cost ceiling and a known rate, the output limit is also lowered to what the
     remaining dollars buy, and a call whose estimated input alone costs more than is
     left is not sent;
   - a cost ceiling on a model with no price is refused here, before any money moves.
     This needs the provider to expose its price book as `prices`, which the bundled
     adapters do. A custom provider without one is checked after its first call.
3. **Accounting, after the call.** The tokens and cost the provider reports are added
   to the run first and checked second. This is the accounting of record. A call that
   broke a ceiling is counted in full, and the run then stops. A call that failed but
   was still billed, such as a refusal, is counted the same way. A call that failed
   with no usage reported still counts as one call.

### What they cannot prevent

The ceilings narrow the overshoot. They do not remove it.

- **One call can pass the token ceiling** by the amount its real input exceeds the
  estimate. Text that tokenizes densely (code, tables, scripts other than Latin) is
  where the estimate is furthest off. Output is held to the reserved limit by the
  provider, so a provider that returns more than `max_tokens` would overshoot by that
  excess too.
- **One call can pass the cost ceiling** by the cost of that same input difference.
- **When no output limit is stated** by the agent or the provider (the Gemini adapter
  states none), the harness sends a reserved limit only below 8,192 tokens. Above that,
  some APIs reject a limit larger than the model's own maximum, so the model's maximum
  applies and bounds the overshoot instead.
- **A reservation holds nothing.** It is computed from what is already spent, so calls
  an agent makes in parallel each see the whole remaining allowance, and the overshoot
  grows with the number in flight.
- **A cut-off check can fire on a complete answer.** An answer that uses exactly the
  lowered output limit is treated as cut short and stops the run, even if the model
  happened to finish there.
- **The ceilings bound one run, not a total.** Many small runs can add up without any
  individual ceiling tripping. A deployment reachable by people you do not know needs
  quota and rate limiting on top. See [security.md](security.md).

The recorded totals are always what the provider reported, never the estimate.

### Pricing

The harness ships no rates. Published prices change too often to hardcode, and a wrong
rate becomes a wrong figure in a grant report. Token and call ceilings need no pricing
and work immediately, which is why they carry the defaults.

A call on a model with no rate is **unpriced**, not free. The run's usage counts it in
`unpriced_calls` and names the model in `unpriced_models`. `harness run` prints
`cost: unknown (no price for <model>)` instead of a dollar figure, and the API returns
`cost_usd: null` with the priced part in `priced_cost_usd`. With a cost ceiling set, an
unpriced model is refused before dispatch, and the error names the model and the fix.

Supply rates in one of two ways.

From the environment, read by every provider that is not given a price book in code:

```bash
export HARNESS_PRICES="your-model=0.30/2.50,meta-llama/llama-4=0.10/0.30"
```

In code, which takes precedence over the environment:

```python
from nonprofit_harness.providers import PriceBook
from nonprofit_harness.providers.google import GoogleProvider

prices = PriceBook().set("your-model", input_per_1m=0.30, output_per_1m=2.50)
provider = GoogleProvider(model="your-model", prices=prices)
```

Price the name the API **answers** with, not only the one you request. A call is costed
by the model the response names. OpenAI, for example, answers `gpt-x` with a dated
snapshot such as `gpt-x-2026-10-01`. When the answered name has no rate and the
requested one does, the call is unpriced and the usage says so. The harness does not
borrow the requested rate, because a fallback or a newer snapshot can cost more.
Under a cost ceiling the pre-dispatch check sees only the requested name, so that first
call is sent and billed, its usage is recorded, and then the run stops as unpriced.
Price both names to avoid losing it.

A rate must be a finite number of 0 or more. `nan`, `inf`, and negative rates are
rejected, because each one would quietly switch the cost ceiling off.

The offline `echo` provider is free and reports a known zero cost, so it runs under a
cost ceiling with no prices set.

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
| `HARNESS_RUN_TIMEOUT_SECONDS` | `3600` | The longest a run may take. After it, its lease is no longer renewed and recovery fails it |
| `HARNESS_RUN_LEASE_SECONDS` | `120` | How long a worker's claim on a running run lasts without renewal. A lapsed lease means the worker is gone |
| `HARNESS_REAP_INTERVAL_SECONDS` | `300` | How often the API looks for runs whose worker is gone. `0` or `off` checks only at startup |
| `HARNESS_MAX_UPLOAD_BYTES` | `20971520` (20MB) | Largest file accepted, by upload or `harness run`. Refused with 413 as soon as the read passes it |
| `HARNESS_MAX_PDF_PAGES` | `300` | Pages read from one PDF. Later pages are skipped and the document is marked `truncated_by: pages` |
| `HARNESS_MAX_DOCX_EXPANDED_BYTES` | `52428800` (50MB) | Total unzipped size a DOCX may declare. Checked from the zip directory before any part is read; past it, refused with 413. This, not the character limit, bounds DOCX memory, because the parser reads each part whole |
| `HARNESS_MAX_DOCUMENT_CHARS` | `2000000` | Characters of text kept from one file. Extraction stops here and marks the document `truncated_by: characters` |
| `HARNESS_EXTRACT_TIMEOUT_SECONDS` | `120` | Wall-clock ceiling on reading one PDF, checked between pages. Past it, refused with 413 |

Each limit accepts `none` to switch it off. A ceiling that cuts a document short sets
`truncated` and `truncated_by` in the document's metadata, so an agent or a reviewer
can tell. A ceiling that cannot leave a usable part (too many bytes, too large once
unzipped, too slow) refuses the file with `document_too_large`. A corrupt, encrypted,
or mislabelled PDF or DOCX is refused with `invalid_document`. Either way no file is
stored and no run starts. The time ceiling cannot interrupt one slow page, so the page
ceiling is what bounds the worst case. The web framework spools an upload to a
temporary file before the route reads it, so also set a request-size limit at your
proxy or platform.

Redaction is a pattern matcher for emails, phone numbers, and similar identifiers. It
reduces exposure. It is not anonymisation and it is not a lawful basis for processing
personal data.

## Authentication

| Variable | Default | Meaning |
|---|---|---|
| `HARNESS_AUTH_REQUIRED` | `false` | Require a session token for runs, uploads, review, and admin routes |
| `HARNESS_GOOGLE_CLIENT_ID` | unset | Google Sign-In client id |
| `HARNESS_JWT_SECRET` | unset | Session signing secret, 32 bytes or more |
| `HARNESS_JWT_TTL_SECONDS` | `43200` | Session lifetime |
| `HARNESS_ADMIN_EMAILS` | empty | Comma-separated admin allowlist |
| `HARNESS_DEFAULT_ORG` | `org_default` | Org a first-time Google user joins; empty means only enrolled users sign in |

With auth off, the API is a single shared workspace with no caller identity. That is
intended for a laptop. **Turn it on before exposing a deployment to anyone.**

The admin allowlist is exact-match and case-insensitive. There are no domain wildcards,
deliberately, because a wildcard on a shared email domain is an accident waiting to
happen.

Sign-in never chooses an organisation. An admin assigns one with
`PUT /v1/admin/members/{email}`. See [security.md](security.md#organisations-and-membership).

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
- a cost ceiling with no `HARNESS_PRICES`, or with no price for `HARNESS_MODEL`
- a malformed `HARNESS_PRICES` entry
- cross-check passes configured without enough distinct models to make them independent
- an even number of cross-check passes, where ties are possible

The admin endpoint reports whether each secret is set, never its value. A configuration
endpoint that echoes a signing key is a configuration endpoint that leaks one.
