# Writing an agent

An agent implements one method. Everything else is the harness's job.

## The contract

```python
from nonprofit_harness import Agent, AgentResult, RunContext

class BoardBriefAgent(Agent):
    name = "board-brief"                  # required, unique, used in the API and CLI
    description = "Briefs for trustees."  # shown by GET /v1/agents
    version = "0.1.0"
    requires_review = True                # default, and usually right
    budget_usd = None                     # None means the deployment default applies

    def run(self, ctx: RunContext) -> AgentResult:
        ...
```

Setting `name` is enforced at class creation. A concrete agent without one raises
`TypeError` immediately rather than failing later at registration.

## What `ctx` gives you

| Field | What it is |
|---|---|
| `ctx.inputs` | `list[Document]`, already extracted to plain text |
| `ctx.provider` | The model interface, already wrapped in this run's budget guard |
| `ctx.options` | Whatever the caller passed as `options` |
| `ctx.run_id`, `ctx.org_id` | Identifiers for logging and metadata |
| `ctx.logger` | A standard library logger |

That is the whole surface. An agent has no store, no config object, and no environment
of its own. Three things follow from that, all of them deliberate:

- The same agent runs offline in a test and on Cloud Run in production, unchanged.
- An agent cannot skip a budget ceiling or approve its own output, because neither
  lever is on its side of the interface.
- Adding a capability is a change to `RunContext`, in one place, reviewed once.

## Reading options

```python
words = int(ctx.option("words", 200))
tone = ctx.option("tone", "neutral")
```

Options arrive from the API as `{"options": {...}}` or from the CLI as
`--option words=150`. They are plain data. Validate them yourself if it matters.

## Producing artifacts

```python
return AgentResult(
    artifacts=[
        self.artifact("brief", text, title=document.name, source=document.name),
    ],
    summary="1 brief",
)
```

`self.artifact(kind, content, title=..., **metadata)` builds one. `kind` is a free
string you choose, such as `brief`, `summary`, or `translation`. Extra keyword arguments land
in the artifact's metadata.

An artifact starts as a draft. It becomes `pending_review`, then `approved` or
`rejected` when a person decides. Your agent never sets that status.

## Attaching claims

If your agent asserts facts drawn from the inputs, say where each one came from:

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

The harness then checks every cited span against this run's own inputs before a
reviewer sees the artifact. That check costs nothing. See the verification section of
the [README](../README.md) for what it does and does not accept.

`locator` is free text for a page or section reference. The harness never parses it. It
exists so a reviewer can find the passage without searching for it.

## Choosing a review policy

`requires_review = True` is the default and is usually correct. Turn it off only for
output that no person would ever read, such as an internal classification feeding
another step.

Even then, the gate refuses to auto-release an artifact whose claims failed
verification. Opting out of review says the output is routine, and an unresolved
citation is evidence that it is not.

## Budgets

Set `budget_usd` on the class if one agent is more expensive than the deployment
default:

```python
class ExpensiveAgent(Agent):
    budget_usd = 2.50
```

Token and call ceilings come from configuration and always apply. Your agent does not
need to count anything. When a ceiling is hit, the run ends as `failed` with the spend
so far recorded, and your `run` method simply stops.

## Failing

Raise. A raised exception becomes a `failed` run with the error recorded, not a crash
and not a lost job. There is no need to catch and convert anything.

```python
if not ctx.inputs:
    raise InvalidRequest("This agent needs at least one document")
```

## Registering it

Three ways, depending on where you are.

```bash
# CLI, one off
harness run mypackage.agents:BoardBriefAgent report.pdf

# Server, at startup
HARNESS_AGENTS=mypackage.agents:BoardBriefAgent uvicorn nonprofit_harness.main:app
```

```python
# In code
from nonprofit_harness import registry
registry.register(BoardBriefAgent())
```

The working directory is added to the import path, so an agent in your own project is
importable without installing it.

## Testing it

Use the offline provider. No key, no network, no spend.

```python
from nonprofit_harness.core.runner import AgentRunner
from nonprofit_harness.core.registry import AgentRegistry
from nonprofit_harness.providers.echo import EchoProvider
from nonprofit_harness.storage.memory import memory_stores
from nonprofit_harness.config import HarnessConfig
from nonprofit_harness.core.types import Document

def test_it_produces_a_brief():
    registry = AgentRegistry()
    registry.register(BoardBriefAgent())
    runner = AgentRunner(
        registry=registry,
        stores=memory_stores(),
        provider=EchoProvider(),
        config=HarnessConfig(),
    )

    run = runner.start(
        "board-brief",
        org_id="org_test",
        inputs=[Document(text="Programme notes.", name="notes.txt")],
    )

    assert run.status == "awaiting_review"
    assert len(run.artifacts) == 1
```

`EchoProvider(canned={"trustees": "..."})` returns fixed text when a prompt contains a
given substring, which is usually enough to test branching without a real model.

## Patterns worth knowing

**One artifact per input document** is the common shape. Loop `ctx.inputs`, append an
artifact per document.

**Several artifacts from one document** is fine too. A brief and a summary from the
same source are two artifacts, reviewed separately, so a reviewer can approve one and
reject the other.

**Multi-step agents** just call the provider more than once inside `run`. The harness
does not impose a chain or graph abstraction. If you want one, use a framework inside
your `run` method. The budget guard counts every call either way.
