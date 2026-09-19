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
laptop with nothing configured. That is not a demo mode. It is the same code path.

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

## Verification

Two layers, split by what they cost.

**Citation checking** is deterministic, offline, and free. Each cited span is matched
against the run's own input documents: an exact match after normalising whitespace and
case, or failing that a sliding-window token overlap.

The window matters. Comparing a span against the document's whole vocabulary passes
almost anything, because in a long report every individual word appears somewhere. The
comparison is therefore against the best-matching *passage*.

Overlap alone is still not enough. A quote that changes a figure keeps most of its
words, so `"reached ninety villages"` scores two out of three against `"reached twelve
villages"`. Any quantity present in the quote but absent from the matched passage
rejects the match outright, because a changed number is a different statement rather
than an approximate quote.

**Cross-checking** costs model calls and is off unless configured. Several reviewers
re-derive the claim from its evidence alone and must reach a quorum. Two details carry
most of its value:

- Passes rotate across *different* models. Reviewers sharing an architecture share its
  blind spots, so agreement between them is weaker evidence than it appears.
- A reviewer that cannot decide abstains, and an empty reply counts as an abstention.
  Unanimous abstention is inconclusive, never a pass.

Verification calls go through the run's budgeted provider, so checking is charged to
the run that caused it. If the ceiling is hit mid-check, the remaining claims are marked
inconclusive and the artifact goes to a person. Discarding finished, already-paid-for
work because the checking ran out of budget would destroy more than it protects.

A failed claim is routed, not punished: the run does not fail and nothing is deleted.
The one hard consequence is that `ReviewGate.auto_release` refuses to release an
artifact whose claims failed, even when the agent set `requires_review = False`. That
rule lives in the gate rather than the runner so no caller can route around it.

## Data sources

A data source turns someone else's published data into `Document`s and results. Once it
does, everything else applies unchanged: an agent consumes those documents as it would
an uploaded PDF, and a claim citing them is verified against the same text.

Fetching runs on the **caller's** side, never inside an agent. An agent that could fetch
its own data would reach past its inputs, could not be tested offline, and could not
have its claims checked against a known set of sources.

The IATI adapter has two paths into the same results model, and the difference is worth
understanding because it is a property of the data rather than of the code.

**The Datastore flattens** a nested activity into parallel arrays, and IATI's own
guidance says you cannot tell which element of one list belongs to which element of
another. Live evidence: one activity returns 16 result titles against 301 indicator
rows; another returns 26 values against 52 dimensions, while a third returns 16 against
21. So results are reported without being attached to indicators, disaggregation is
reported without being attached to numbers, and fields whose length disagrees are
dropped and named. The danger is that some activities return matching lengths by
coincidence, which makes a wrong implementation look correct in testing.

**The published XML keeps the nesting**, so `client.results()` recovers all of it. Both
cost one call. Searching still goes through the flattened collection, because you cannot
search XML you have not fetched.

Codelists are bundled rather than fetched, so resolving a code costs no network, no key
and none of the weekly quota. A code is only resolved inside its own vocabulary: a
publisher's own sector numbering is left bare rather than given an OECD DAC name that
would be real and wrong.

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
