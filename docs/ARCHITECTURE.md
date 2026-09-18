# Architecture

## The shape

```
          HTTP / CLI
              │
        ┌─────▼─────┐
        │AgentRunner│   owns the run lifecycle
        └─────┬─────┘
              │ builds a RunContext
     ┌────────┼────────────────┐
     │        │                │
┌────▼───┐ ┌──▼──────────┐ ┌───▼────┐
│ Agent  │ │BudgetedProv.│ │ Stores │
│(yours) │ │  → Provider │ │        │
└────┬───┘ └─────────────┘ └────────┘
     │ returns AgentResult
┌────▼──────┐
│ ReviewGate│   nothing is released without a decision
└───────────┘
```

## Why the agent is so small

An `Agent` implements one method and receives one object. It has no access to storage,
no knowledge of budgets, and no way to release its own output. That is deliberate:

- The same agent runs in a unit test against an offline provider and in production
  against Vertex AI, unchanged.
- Cross-cutting guarantees stay guaranteed. An agent cannot skip the budget ceiling or
  self-approve, because neither lever is on its side of the interface.
- Failure handling is uniform. A raised exception becomes a `FAILED` run record, not a
  500 and a lost job.

## The seams

| Seam | Interface | Default | Swap for |
|---|---|---|---|
| Model | `ModelProvider` | `EchoProvider` (offline) | `GoogleProvider`, or your own |
| Storage | `Stores` | in-memory | Firestore + Cloud Storage |
| Instrument | `Instrument` | tiny example | your own JSON |
| Inbound events | webhook registry | none | your form or CRM vendor |

Every seam is a protocol with an in-process default, so the whole system runs on a
laptop with nothing configured. That is not a demo mode — it is the same code path.

## Run lifecycle

```
create → QUEUED
execute → RUNNING
   agent raises          → FAILED (error recorded, spend recorded)
   budget ceiling hit    → FAILED (partial spend recorded)
   agent returns
      requires_review    → AWAITING_REVIEW → (per-artifact decisions) → COMPLETED
      not requires_review→ COMPLETED, with an automatic review record
```

A failed run is data, not an exception. By the time an agent can fail, the caller has
usually already been handed a run id, so the failure surfaces on the next poll as a
normal response with `status: failed`.

## Budget accounting

`BudgetGuard` records spend and then checks ceilings, rather than the other way round.
The call that breaches a limit has already happened and already cost money, so refusing
to count it would make the harness report less spend than the invoice shows.

Call ceilings are also checked *before* dispatch, so an exhausted budget fails fast
instead of paying for one more response first.

## Review

`ArtifactStatus` moves `DRAFT → PENDING_REVIEW → APPROVED | REJECTED`. `ReviewGate.release`
raises if anything is still pending rather than quietly returning a shorter list, so a
caller that forgot about review finds out at the boundary.

Automatic releases still write a `Review` record, with `system:auto-release` as the
reviewer. An audit can always answer who released a given artifact.

## Readiness scoring

Three decisions carry the method:

1. **Per-question direction is explicit.** Option scores live in the instrument. Nothing
   infers direction from the order options happen to appear in, because a list-position
   rule silently inverts every question whose options run the other way.
2. **Excluded options drop a question.** A "don't know" answer removes the question from
   scoring instead of scoring it zero.
3. **Geometric mean across dimensions.** Weakness in one dimension is not averaged away
   by strength in another. A `ZERO_FLOOR` keeps a single genuine zero from collapsing
   the whole index.

## Not included on purpose

- **No agent orchestration DSL.** Chains, graphs, and multi-agent routing belong to the
  framework you choose. This harness runs whatever your `run` method does.
- **No vector store or RAG layer.** It would force an infrastructure choice that most
  first deployments do not need yet.
- **No UI.** The API is the contract, so a frontend is a separate concern.
