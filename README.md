# QriusAI Nonprofit Agent Harness

An open agent harness for the nonprofit sector. You write the agent. It gives you
everything around the agent.

Built on [Google's Agent Development Kit](https://github.com/google/adk-python), and
genuinely usable without it: OpenAI, Anthropic, Groq, Together, OpenRouter, vLLM and
local models through Ollama all work out of the box, with no extra install.

[![PyPI](https://img.shields.io/pypi/v/nonprofit-agent-harness.svg)](https://pypi.org/project/nonprofit-agent-harness/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

> **Status: alpha.** Everything described below works and is covered by tests. The
> interfaces will still change while the version stays below 1.0, so pin an exact
> version if you depend on them.

---

## Why the Foundation built this

[QriusAI Foundation](https://qriusai.org/) works on AI capacity building for
nonprofits. Across that work one pattern keeps repeating. A nonprofit team knows
exactly what it needs an agent to do, because nobody understands their programme
better than they do. What stops them is never the idea. It is the six weeks of
scaffolding around the idea: sign-in, file handling, job state, cost control, an
approval step, somewhere to put the output.

So they either do not build it, or they pay someone to build a single tool that only
that someone can maintain.

We would rather give away the scaffolding.

**We are not trying to build the tools the sector needs. We are building the blocks
the sector can build them from.** A harness is infrastructure. It is deliberately not
a product, not a platform you sign up for, and not something that routes your work
through us. You fork it, you run it, you own it, and the capability stays with you.

This is what we think AI capacity building has to mean eventually. Training helps.
Tools help. But a sector that can only use what it is given stays dependent on
whoever gives it. A sector with its own building blocks does not.

## This is not a design sketch

The Foundation runs the **Curriculum Agent** for nonprofits: an organisation uploads
its own training material, an agent restructures it into something teachable, and a
person reviews every change before anything is released. You can see it at
[qriusai.org/harness](https://qriusai.org/harness).

The harness in this repository is that system's machinery, rewritten for public use
rather than invented for it. The review gate exists because real output had to be
signed off by a real person. The budget ceilings exist because the bill was real. The
citation checking exists because a generated fact reaching a funder report is a
specific thing to be afraid of, not a hypothetical.

What is here is the scaffolding, not the agents. The Curriculum Agent and the
Foundation's other work stay in its own repositories. This is the part worth giving
away.

## What we looked for, and did not find

Before writing this we searched for one already. Two angles: open-source agent
projects scoped to the nonprofit sector, and agent projects built on Google's ADK for
nonprofit use.

We found real, useful work in each direction separately. There are nonprofit-specific
single-purpose tools, for grant writing and for board governance. There are ADK
projects built by and for individual organisations. There are excellent
general-purpose agent frameworks that any sector can build on.

What we did not find was something at the intersection: a reusable harness, scoped to
this sector, that a nonprofit could fork and build several different agents on.

We want to be precise about what that is and is not. It is an absence of evidence from
two search angles, not an exhaustive audit of everything that exists. So the honest
claim is **"we found no comparable project"**, not "this is the first in the world."
If you know of one, please [open an issue](https://github.com/QriusAI-Foundation/nonprofit-agent-harness/issues).
We would genuinely like to know, and we would rather link to it than duplicate it.

## What makes this a nonprofit harness

Plenty of frameworks will help you call a model. Very few assume the things this
sector has to assume.

**Someone is accountable for every output.** A generated training handout, funder
summary, or community-facing message cannot go out because a model produced it. Review
is the default here, not an add-on, and every release records who approved it.

**A claim has to be traceable to a source.** An invented statistic in a funder report
is the failure that costs an organisation its credibility. Cited quotes are checked
against the source document before a reviewer ever sees them, and that check costs
nothing to run.

**The budget is fixed and small.** Grant money does not stretch because a retry loop
misbehaved. Every run carries a hard ceiling on cost, tokens, and calls.

**Nobody chose their model provider.** Credits arrive donated, from whichever platform
offered them, and some data is not allowed to leave the building at all. Eight
providers work out of the box, including local models, and switching is one
environment variable.

**There is no platform team.** It has to run with no cloud account before it runs with
one. A fresh clone works offline, for free, in one command.

If your agent does not need those things, use a general framework. This one is scoped
on purpose.

## Quickstart

No cloud account, no API key, no spend:

```bash
pip install nonprofit-agent-harness
harness check
```

That prints the settings in force. Nothing is configured yet, and it still runs,
because the default provider is offline and deterministic.

To work on the harness itself, or to run the bundled examples:

```bash
git clone https://github.com/QriusAI-Foundation/nonprofit-agent-harness
cd nonprofit-agent-harness
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,documents]"

harness run examples.summarizer:SummarizerAgent path/to/report.pdf
```

The examples are not packaged, deliberately. They are reference material rather than
library code, and your agents live in your own project.

Continuous integration installs the package with no extras and runs the example on
every commit, so the offline promise stays true rather than being an aspiration.

Point it at a real model when you are ready. Any of these work, and no provider needs
an extra install except Google:

```bash
# OpenAI, or Groq, Together, OpenRouter with the same adapter
HARNESS_PROVIDER=openai  HARNESS_MODEL=gpt-4o-mini  OPENAI_API_KEY=...

# Claude
HARNESS_PROVIDER=anthropic  ANTHROPIC_API_KEY=...

# A local model. Nothing leaves the machine.
HARNESS_PROVIDER=ollama  HARNESS_MODEL=llama3.1

# Vertex AI, which uses the service account and so has no API key at all
HARNESS_PROVIDER=google  GOOGLE_CLOUD_PROJECT=...
```

Everything except Google and Anthropic is one adapter speaking the OpenAI chat API, so
any server implementing it works by setting `OPENAI_BASE_URL`, named alias or not. That
matters for two situations this sector actually hits: donated credits on whichever
platform offered them, and data that is not allowed to leave your own hardware.

Switching provider changes nothing else. Agents, review, budget ceilings and
verification behave identically, because the model layer is the only thing that moved.

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
global client, or an environment variable of its own. That is why the same agent runs
offline in a test and on Cloud Run in production without changing, and why it cannot
skip a budget ceiling or approve its own output.

See [docs/writing-an-agent.md](docs/writing-an-agent.md) for the full guide.

## What you get around it

| Piece | What it does |
|---|---|
| **Review gate** | Artifacts land in `pending_review`. Nothing is released until a person approves it, and every decision records who made it, including automatic ones. |
| **Claim verification** | Cited quotes are checked against the source. Free and offline. An optional cross-check has several models re-derive the claim from its evidence alone. |
| **Budget ceilings** | Hard per-run limits on cost, tokens, and calls. Token and call limits work before you configure any pricing. |
| **Readiness scoring** | A scoring engine for AI-readiness instruments: per-question direction, excluded options, weighted dimensions, geometric-mean aggregation, tier bands. |
| **Documents** | PDF, DOCX, and text in, plain text out. Agents never see bytes. |
| **Sector data** | An IATI adapter that turns published activity data, and published indicators, into harness input. |
| **Results and indicators** | The sector's own arithmetic: achievement against target, progress from baseline, disaggregation, budget utilisation. Deterministic, no model calls. |
| **Providers** | OpenAI, Anthropic, Groq, Together, OpenRouter, vLLM, Ollama, and Gemini. Only Gemini needs an extra install. |
| **Storage** | In-memory by default. Firestore and Cloud Storage behind the same interface. |
| **Auth** | Google Sign-In verification plus the harness's own session tokens. Off by default. |
| **Redaction** | Optional masking of direct identifiers before text reaches a model. |
| **Credential hygiene** | Every provider's error text is scrubbed of API keys before it is raised, logged, or returned. |
| **Run recovery** | A run stranded by a stopped process is failed at startup, so a poller gets an answer instead of waiting forever. |
| **HTTP API and CLI** | FastAPI surface for runs, uploads, review, readiness and webhooks, plus a `harness` command. |

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

Matching accepts an exact quote, or a close one, because models do introduce small
edits while quoting. It does not accept a changed number. `"reached ninety villages"`
shares two words in three with `"reached twelve villages"`, so plain word overlap would
wave it through, and a swapped figure is precisely the fabrication that does damage.
Any quantity in the quote that is missing from the source rejects the match.

**Layer two costs model calls and is opt-in.** Several reviewers re-derive the claim
from its evidence alone and have to agree:

```bash
export HARNESS_VERIFY_PASSES=3
export HARNESS_VERIFY_MODELS=model-a,model-b,model-c
```

Use different models rather than the same one several times. Reviewers that share an
architecture tend to share its blind spots, which makes their agreement much weaker
evidence than it looks. A reviewer that cannot decide abstains rather than guessing.

Results reach the person doing the review, not a silent filter:

```json
{ "ok": false, "summary": "3 claim(s), 2 verified, 1 citation not found" }
```

A failed claim never discards work and never fails the run. It flags the artifact so a
reviewer knows where to look. One consequence worth knowing: an agent that sets
`requires_review = False` still cannot auto-release an artifact whose claims failed.
Opting out of review says the output is routine. A citation that does not resolve is
evidence that it is not.

## Did the programme work

The sector's own arithmetic, written down once. Deterministic, and free to run.

```python
from nonprofit_harness.results import Baseline, Indicator, achievement

got = achievement(indicator)
got.explain()   # "Enrolment: 50.0% (70 from a baseline of 60 towards 80)"
```

Three things this refuses to get wrong, each of which produces a confident and
incorrect number if you do the obvious thing:

- **Direction.** Forty disease cases against a target of fifty is a success, not an
  80% shortfall. The IATI `ascending` flag says which way is good, and it is honoured.
- **Baselines.** Enrolment moving 60 to 70 against a target of 80 is 50% of the
  intended change, not 87.5%. Measuring from zero credits a programme with what was
  already true before it started.
- **What may be added.** Percentages do not sum, ordinal codes are labels, and
  publishers can mark their own data as not aggregatable. Totals refuse rather than
  filtering quietly, because a total that dropped half its inputs looks complete.

Nothing returns a bare number. Every figure carries how it was reached, and anything
that cannot be calculated says why instead of guessing. See
[docs/results.md](docs/results.md).

## Reading the sector's own data

Funders and implementing organisations publish activity data to the
[IATI standard](https://iatistandard.org/). The harness reads it and turns it into
ordinary harness input:

```python
from nonprofit_harness.datasources import IatiClient

client = IatiClient(cache={})                                  # IATI_API_KEY, free
activities = client.search_activities(reporting_org="XM-DAC-41114", rows=5)

run = runner.start("my-agent", org_id="org_1",
                   inputs=[a.to_document() for a in activities])
```

Fetching happens on the caller's side, never inside the agent. An agent that could
fetch its own data would reach past its inputs, could not be tested offline, and could
not have its claims checked against a known set of sources.

The free IATI tier allows 100 calls a week, so pass a cache.

Codes arrive resolved, because `Sectors: 11220` is precise and useless:

```
Recipient countries: Palestine, State of (PS)
Sectors: Primary education (11220)
Activity status: Closed (4)
```

The lists are bundled, so that costs no network, no key, and none of the call budget.
A publisher's own narrative always wins over the codelist, and a sector reported
against a publisher's own numbering is left as a bare code rather than given a DAC name
that would be real and wrong.

Published indicators come back as the results model above, ready to compute on:

```python
parsed = client.indicators("US-EIN-521257057-WRI-23-27")
parsed.indicators      # rebuilt, ready for achievement()
parsed.warnings        # read these before reporting any number
```

**Read the warnings.** The Datastore flattens a nested activity into parallel arrays,
and IATI's own guidance says you cannot tell which element of one list belongs to which
element of another. Confirmed live: one real activity returns 16 result titles against
301 indicator rows, with nothing relating them. Indicators are therefore reconstructed,
because their fields are internally consistent, and results are reported without being
attached to them. Guessing the grouping would put indicators under the wrong result.

See [docs/datasources.md](docs/datasources.md).

## Readiness scoring

The engine is open. The questionnaire is data you supply.

```python
from nonprofit_harness.readiness import Instrument, score

instrument = Instrument.from_json("my-instrument.json")
result = score(instrument, {"d1": "spreadsheets", "d2": "dont_know"})

result.overall            # 0.0 to 1.0
result.dimension_scores   # per dimension
result.tier               # whichever band the overall lands in
result.excluded_questions # what was left out of scoring, and why
```

Two design choices worth knowing about, because they change the numbers:

- **"Don't know" removes a question from scoring rather than scoring it zero.** In this
  sector, "don't know" usually means a thin back office, not low capability. Scoring it
  as zero systematically marks down the smallest organisations.
- **Dimensions combine with a geometric mean.** An organisation with excellent tooling
  and no data governance is not "average". It is blocked on data governance, and an
  arithmetic mean hides that.

A small example instrument ships in `src/nonprofit_harness/readiness/instruments/`. It
is a demonstration, not a validated index. Bring your own.

The Foundation authors and stewards a nonprofit AI readiness index of its own. That
index is meant as a neutral standard for the sector rather than a QriusAI product,
which is exactly why the scoring engine is here in the open and the questionnaire is
just data.

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
POST /v1/runs                                              create a run
GET  /v1/runs                                              list them
GET  /v1/runs/{run_id}
GET  /v1/review/queue                                      what is waiting on a person
POST /v1/review/{run_id}/artifacts/{artifact_id}/approve
POST /v1/review/{run_id}/artifacts/{artifact_id}/reject
POST /v1/review/{run_id}/approve-all
GET  /v1/review/{run_id}/released                          409 while anything is pending
GET  /v1/readiness/instrument
POST /v1/readiness/score
POST /v1/auth/google                                       exchange a Google credential
GET  /v1/auth/me
GET  /v1/admin/config                                      settings in force, plus warnings
GET  /v1/admin/orgs
POST /v1/webhooks/{source}
```

Interactive docs at `/docs`.

## The command line

```bash
harness check                                        # settings in force, and any warnings
harness run mypackage.agents:BriefAgent report.pdf   # run an agent over files
harness score answers.json                           # score readiness answers
```

`harness run` adds the working directory to the import path, so an agent in your own
project works without installing it. Pass `--option key=value` to reach `ctx.options`.

## Configuration

Everything is environment variables. Defaults are offline, free, and reviewed. See
[docs/configuration.md](docs/configuration.md) for the full reference.

| Variable | Default | Meaning |
|---|---|---|
| `HARNESS_PROVIDER` | `echo` | `echo`, `openai`, `anthropic`, `groq`, `ollama`, `google`, and more |
| `HARNESS_MODEL` | provider default | Model name |
| `HARNESS_STORAGE` | `memory` | `memory` or `gcp` |
| `HARNESS_MAX_COST_USD` | unset | Per-run cost ceiling |
| `HARNESS_MAX_TOKENS` | `200000` | Per-run token ceiling |
| `HARNESS_MAX_CALLS` | `50` | Per-run model-call ceiling |
| `HARNESS_VERIFY_CLAIMS` | `true` | Check cited quotes against the source (free) |
| `HARNESS_VERIFY_PASSES` | `0` | Cross-check passes per claim (costs model calls) |
| `HARNESS_VERIFY_MODELS` | empty | Comma-separated models to rotate across passes |
| `HARNESS_REDACT_INPUTS` | `false` | Mask identifiers before sending text |
| `HARNESS_RUN_TIMEOUT_SECONDS` | `3600` | How long before a stranded run is treated as abandoned |
| `HARNESS_AUTH_REQUIRED` | `false` | Require a session token |
| `HARNESS_GOOGLE_CLIENT_ID` | unset | For Google Sign-In |
| `HARNESS_JWT_SECRET` | unset | Session signing secret, 32 bytes or more |
| `HARNESS_ADMIN_EMAILS` | empty | Comma-separated allowlist, exact match |
| `HARNESS_CORS_ORIGINS` | empty | Comma-separated browser origins |
| `HARNESS_AGENTS` | empty | Comma-separated `module:ClassName` to register |

Provider keys use each vendor's usual name: `OPENAI_API_KEY`, `OPENAI_BASE_URL`,
`ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` or `GOOGLE_CLOUD_PROJECT`. Data sources use
`IATI_API_KEY`.

Ceilings accept `none`, `unlimited`, or `off` to switch off. `0` means zero, not
"unset". Run `harness check` to print what is actually in force, along with the
problems that would bite in production.

## Deploying

`deployment/` has a Dockerfile and Terraform for Cloud Run, configured to scale to zero
so an idle deployment costs nothing. See [docs/deployment.md](docs/deployment.md), and
read [docs/security.md](docs/security.md) before exposing an instance publicly.

## Use it as a starter template

This repo doubles as an
[agent-starter-pack](https://github.com/GoogleCloudPlatform/agent-starter-pack) remote
template:

```bash
uvx agent-starter-pack create my-agent -a github.com/QriusAI-Foundation/nonprofit-agent-harness
```

## Documentation

| Document | What it covers |
|---|---|
| [docs/writing-an-agent.md](docs/writing-an-agent.md) | The agent contract in depth, options, claims, testing |
| [docs/datasources.md](docs/datasources.md) | Reading the sector's open data, starting with IATI |
| [docs/results.md](docs/results.md) | Results, indicators, and the arithmetic that gets them wrong |
| [docs/configuration.md](docs/configuration.md) | Every setting, what it does, what it costs |
| [docs/deployment.md](docs/deployment.md) | Cloud Run and Terraform, start to finish |
| [docs/security.md](docs/security.md) | Threat model, what is and is not protected |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Why the pieces are shaped the way they are |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup, conventions, what we are looking for |

## Project status

Honest about where this is:

**Works and is tested.** The agent contract, review gate, claim verification, budget
ceilings, the results and indicator arithmetic, the readiness engine, the IATI data
source, eight model providers, document extraction, in-memory and GCP storage, auth,
the HTTP API, and the CLI. **253 tests**, all offline, on Python 3.11 through 3.13.

**Known gaps.** Per-run ceilings bound a single run rather than a total, so a
deployment open to the public needs quota and rate limiting on top. Runs still execute
in-process, and although a stranded run is now failed at startup, high volumes want a
real queue.

**Not started.** Reading an activity's published XML, which is what would make IATI
disaggregated values and result grouping recoverable at all. An evaluation harness.
Logframe and theory of change structures, which are mostly narrative and so offer
little for code to check.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and pull requests are welcome,
especially from people running agents in actual nonprofit settings. That is the
feedback this is hardest to get and the most useful to have.

## License and credit

[Apache License 2.0](LICENSE). You may fork it, change it, and use it commercially.

Attribution is required, and the license enforces it rather than asking. Section 4(d)
says any derivative work must carry forward the notice in [NOTICE](NOTICE). Keep that
file and you are compliant.

## About QriusAI Foundation

[QriusAI Foundation](https://qriusai.org/) is the public brand of KRIAAJEE
ENVIRONMENTAL FOUNDATION, a Section 8 nonprofit. The Foundation works on AI literacy
and AI capacity building with nonprofits, schools, and colleges, including in places
where the digital divide is widest.

This harness is part of that work. Software is one of the ways capability transfers,
and open source is the version of it that does not depend on us still being here.
