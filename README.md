# QriusAI Nonprofit Agent Harness

An open agent harness for the nonprofit sector. You write the agent. It gives you
everything around the agent.

Built on [Google's Agent Development Kit](https://github.com/google/adk-python), and
usable without it — the model layer is one swappable interface.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

> **Status: alpha.** The interfaces below work and are covered by tests, but they
> will still change. Pin a commit if you depend on it.

## Why this exists

Plenty of agent frameworks will help you call a model. Very few of them assume the
things a nonprofit has to assume:

- **Someone is accountable for every output.** A generated training handout, funder
  summary, or beneficiary-facing message cannot be published because a model produced
  it. Review is the default here, not an add-on.
- **A claim has to be traceable to a source.** An invented statistic in a funder report
  is the failure that costs an organisation its credibility. The harness checks cited
  quotes against the source document, for free, before a reviewer sees them.
- **The budget is fixed and small.** Grant money does not stretch because a retry loop
  misbehaved. Every run carries a hard ceiling.
- **There is no platform team.** It has to run with no cloud account before it runs
  with one.

If your agent does not need those things, use a general framework. This one is scoped
deliberately.

## Quickstart

No cloud account, no API key, no spend:

```bash
git clone https://github.com/QriusAI-Foundation/nonprofit-agent-harness
cd nonprofit-agent-harness
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,documents]"

harness run examples.summarizer:SummarizerAgent path/to/report.pdf
```

That runs against a built-in offline provider that returns deterministic text, so the
whole path works before you connect a real model.

Point it at Gemini when you are ready:

```bash
export HARNESS_PROVIDER=google
export GOOGLE_API_KEY=...          # or use Vertex with GOOGLE_CLOUD_PROJECT
harness run examples.summarizer:SummarizerAgent report.pdf
```

## Writing an agent

One method. The harness owns the rest.

```python
from nonprofit_harness import Agent, AgentResult, RunContext

class BoardBriefAgent(Agent):
    name = "board-brief"
    description = "Turns programme documents into a short brief for trustees."

    def run(self, ctx: RunContext) -> AgentResult:
        artifacts = []
        for document in ctx.inputs:
            response = ctx.provider.generate(
                f"Write a 200-word brief for trustees:\n\n{document.text}",
                system="Plain language. Short sentences. No invented facts.",
            )
            artifacts.append(self.artifact("brief", response.text, title=document.name))
        return AgentResult(artifacts=artifacts, summary=f"{len(artifacts)} brief(s)")
```

`ctx` is the only thing your agent touches. It never reaches for a database handle, a
global client, or an environment variable of its own, which is why the same agent runs
offline in a test and on Cloud Run in production without changing.

## What you get around it

| Piece | What it does |
|---|---|
| **Review gate** | Artifacts land in `pending_review`. Nothing is released until a person approves it, and every decision records who made it — including automatic ones. |
| **Claim verification** | Cited quotes are checked against the source. Free and offline. An optional cross-check has several models re-derive the claim from its evidence alone. |
| **Budget ceilings** | Hard per-run limits on cost, tokens, and calls. Token and call limits work before you configure any pricing. |
| **Readiness scoring** | A scoring engine for AI-readiness instruments: per-question direction, excluded options, weighted dimensions, geometric-mean aggregation, tier bands. |
| **Documents** | PDF, DOCX, and text in, plain text out. Agents never see bytes. |
| **Storage** | In-memory by default. Firestore and Cloud Storage behind the same interface. |
| **Auth** | Google Sign-In verification plus the harness's own session tokens. Off by default. |
| **Redaction** | Optional masking of direct identifiers before text reaches a model. |
| **HTTP API** | FastAPI surface for runs, uploads, the review queue, readiness, and webhooks. |

## Run it as a service

```bash
uvicorn nonprofit_harness.main:app --reload
```

```bash
HARNESS_AGENTS=examples.summarizer:SummarizerAgent uvicorn nonprofit_harness.main:app
```

```
GET  /healthz
GET  /v1/agents
POST /v1/uploads
POST /v1/runs
GET  /v1/runs/{id}
GET  /v1/review/queue
POST /v1/review/{run_id}/artifacts/{artifact_id}/approve
GET  /v1/review/{run_id}/released
POST /v1/readiness/score
POST /v1/webhooks/{source}
```

Interactive docs at `/docs`.

## Verifying what an artifact claims

Attach claims to an artifact and the harness checks them before anyone reviews it:

```python
from nonprofit_harness import Citation, Claim

self.artifact(
    "brief", text,
    claims=[
        Claim(
            statement="The programme reached twelve villages.",
            citations=[Citation(text="reached twelve villages", locator="p.3")],
        )
    ],
)
```

**Layer one costs nothing.** Every quoted span must actually appear in one of the run's
own input documents. No model call, no network, no spend. This is what catches an
invented citation, and it runs by default.

Matching accepts an exact quote, or a close one — models do introduce small edits while
quoting. It does *not* accept a changed number. `"reached ninety villages"` shares two
words in three with `"reached twelve villages"`, so plain word-overlap would wave it
through, and a swapped figure is precisely the fabrication that does damage. Any
quantity in the quote that is missing from the source rejects the match.

**Layer two costs model calls and is opt-in.** Several reviewers re-derive the claim
from its evidence alone and have to agree:

```bash
export HARNESS_VERIFY_PASSES=3
export HARNESS_VERIFY_MODELS=model-a,model-b,model-c
```

Use *different* models rather than the same one several times. Reviewers that share an
architecture tend to share its blind spots, which makes their agreement much weaker
evidence than it looks. A reviewer that cannot decide abstains rather than guessing.

Results reach the person doing the review, not a silent filter:

```json
{ "ok": false, "summary": "3 claim(s), 2 verified, 1 citation not found" }
```

A failed claim never discards work and never fails the run. It flags the artifact so a
reviewer knows where to look. One consequence worth knowing: an agent that sets
`requires_review = False` still cannot auto-release an artifact whose claims failed.
Opting out of review says the output is routine; a citation that does not resolve is
evidence that it is not.

## Readiness scoring

The engine is open. The questionnaire is data you supply.

```python
from nonprofit_harness.readiness import Instrument, score

instrument = Instrument.from_json("my-instrument.json")
result = score(instrument, {"d1": "spreadsheets", "d2": "dont_know"})

result.overall            # 0.0 - 1.0
result.dimension_scores   # per dimension
result.tier               # whichever band the overall lands in
result.excluded_questions # what was left out of scoring, and why
```

Two design choices worth knowing about, because they change the numbers:

- **"Don't know" removes a question from scoring rather than scoring it zero.** In this
  sector, "don't know" usually means a thin back office, not low capability. Scoring it
  as zero systematically marks down the smallest organisations.
- **Dimensions combine with a geometric mean.** An organisation with excellent tooling
  and no data governance is not "average", it is blocked on data governance, and an
  arithmetic mean hides that.

A small example instrument ships in `src/nonprofit_harness/readiness/instruments/`. It
is a demonstration, not a validated index. Bring your own.

## Configuration

Everything is environment variables. Defaults are offline, free, and reviewed.

| Variable | Default | Meaning |
|---|---|---|
| `HARNESS_PROVIDER` | `echo` | `echo` (offline) or `google` |
| `HARNESS_MODEL` | provider default | Model name |
| `HARNESS_STORAGE` | `memory` | `memory` or `gcp` |
| `HARNESS_MAX_COST_USD` | unset | Per-run cost ceiling |
| `HARNESS_MAX_TOKENS` | `200000` | Per-run token ceiling |
| `HARNESS_MAX_CALLS` | `50` | Per-run model-call ceiling |
| `HARNESS_REDACT_INPUTS` | `false` | Mask identifiers before sending text |
| `HARNESS_VERIFY_CLAIMS` | `true` | Check cited quotes against the source (free) |
| `HARNESS_VERIFY_PASSES` | `0` | Cross-check passes per claim (costs model calls) |
| `HARNESS_VERIFY_MODELS` | empty | Comma-separated models to rotate across passes |
| `HARNESS_AUTH_REQUIRED` | `false` | Require a session token |
| `HARNESS_GOOGLE_CLIENT_ID` | unset | For Google Sign-In |
| `HARNESS_JWT_SECRET` | unset | Session signing secret |
| `HARNESS_ADMIN_EMAILS` | empty | Comma-separated allowlist |
| `HARNESS_AGENTS` | empty | Comma-separated `module:ClassName` to register |

Ceilings accept `none`, `unlimited`, or `off` to switch off. `0` means zero, not
"unset". Run `harness check` to print what is actually in force.

## Use it as a starter template

This repo doubles as an
[agent-starter-pack](https://github.com/GoogleCloudPlatform/agent-starter-pack) remote
template:

```bash
uvx agent-starter-pack create my-agent -a github.com/QriusAI-Foundation/nonprofit-agent-harness
```

## Deploying

`deployment/` has a Dockerfile and Terraform for Cloud Run, configured to scale to zero
so an idle deployment costs nothing.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and pull requests are welcome, especially
from people running agents in actual nonprofit settings — that is the feedback this is
hardest to get.

## License and credit

[Apache License 2.0](LICENSE). You may fork it, change it, and use it commercially.

Attribution is required, and it is enforced by the license rather than by request:
section 4(d) says any derivative work must carry forward the notice in
[NOTICE](NOTICE). Keep that file, and you are compliant.

Built and maintained by [QriusAI Foundation](https://qriusai.org/).
