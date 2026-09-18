from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from nonprofit_harness.config import HarnessConfig
from nonprofit_harness.core.agent import Agent, RunContext
from nonprofit_harness.core.errors import BudgetExceeded, HarnessError
from nonprofit_harness.core.registry import AgentRegistry
from nonprofit_harness.core.types import Document, Run, RunStatus
from nonprofit_harness.guardrails.budget import BudgetedProvider, BudgetGuard
from nonprofit_harness.guardrails.redaction import Redactor
from nonprofit_harness.providers.base import ModelProvider
from nonprofit_harness.review.gate import ReviewGate
from nonprofit_harness.storage.base import Stores
from nonprofit_harness.verification import GroundingVerifier
from nonprofit_harness.verification.types import Claim, Outcome, Verdict, VerificationReport

logger = logging.getLogger("nonprofit_harness.runner")


@dataclass(slots=True)
class AgentRunner:
    """Owns the run lifecycle so agents do not have to.

    An agent implements one method and knows nothing about persistence, budgets,
    review state, or failure handling. All of that happens here, identically for
    every agent, which is the whole point of a harness.
    """

    registry: AgentRegistry
    stores: Stores
    provider: ModelProvider
    config: HarnessConfig
    gate: ReviewGate = None  # type: ignore[assignment]
    redactor: Redactor = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.gate is None:
            self.gate = ReviewGate(self.stores.runs)
        if self.redactor is None:
            self.redactor = Redactor()

    def create(
        self,
        agent_name: str,
        *,
        org_id: str,
        inputs: list[Document],
        options: dict | None = None,
    ) -> Run:
        agent = self.registry.get(agent_name)
        run = Run(
            agent=agent.name,
            org_id=org_id,
            inputs=self._prepare(inputs),
            metadata={"options": options or {}, "agent_version": agent.version},
        )
        return self.stores.runs.save(run)

    def start(
        self,
        agent_name: str,
        *,
        org_id: str,
        inputs: list[Document],
        options: dict | None = None,
    ) -> Run:
        run = self.create(agent_name, org_id=org_id, inputs=inputs, options=options)
        return self.execute(run.id)

    def execute(self, run_id: str) -> Run:
        run = self.stores.runs.get(run_id)
        agent = self.registry.get(run.agent)

        run.status = RunStatus.RUNNING
        self.stores.runs.save(run)

        guard = self._guard_for(agent)
        provider = BudgetedProvider(self.provider, guard)
        ctx = RunContext(
            run_id=run.id,
            org_id=run.org_id,
            inputs=run.inputs,
            provider=provider,
            options=run.metadata.get("options", {}),
            logger=logger,
        )

        try:
            result = agent.run(ctx)
        except BudgetExceeded as exc:
            return self._fail(run, guard, f"Stopped at the budget ceiling: {exc}")
        except HarnessError as exc:
            return self._fail(run, guard, str(exc))
        except Exception as exc:  # noqa: BLE001 - a failed run is data, not a crash
            logger.exception("Agent %s failed on run %s", agent.name, run.id)
            return self._fail(run, guard, f"{type(exc).__name__}: {exc}")

        run.artifacts = list(result.artifacts)
        run.summary = result.summary
        run.metadata.update(result.metadata)

        # Before usage is banked, so cross-checking shows up in the run's own cost.
        self._verify_claims(run, provider)
        run.usage = guard.spent

        if agent.requires_review:
            return self.gate.submit(run)
        return self.gate.auto_release(run, reason=f"{agent.name} declares requires_review=False")

    def _verify_claims(self, run: Run, provider: BudgetedProvider) -> None:
        if not self.config.verify_claims:
            return
        claimed = [artifact for artifact in run.artifacts if artifact.claims]
        if not claimed:
            return

        sources = _sources_for(run)
        verifier = GroundingVerifier(
            provider=provider if self.config.verify_passes > 0 else None,
            passes=self.config.verify_passes,
            models=self.config.verify_models,
        )

        for position, artifact in enumerate(claimed):
            try:
                artifact.verification = verifier.verify_all(artifact.claims, sources)
            except BudgetExceeded as exc:
                # The agent's work is already done and already paid for. Throwing the
                # run away because the checking ran out of budget would destroy more
                # than it protects, so what is left goes to a person instead.
                for remaining in claimed[position:]:
                    remaining.verification = _stopped_short(remaining.claims, str(exc))
                logger.warning("Verification stopped at the budget ceiling on run %s", run.id)
                return

    def _fail(self, run: Run, guard: BudgetGuard, message: str) -> Run:
        run.status = RunStatus.FAILED
        run.error = message
        run.usage = guard.spent
        return self.stores.runs.save(run)

    def _guard_for(self, agent: Agent) -> BudgetGuard:
        return BudgetGuard(
            max_cost_usd=(
                agent.budget_usd if agent.budget_usd is not None else self.config.max_cost_usd
            ),
            max_tokens=self.config.max_tokens,
            max_calls=self.config.max_calls,
        )

    def _prepare(self, inputs: list[Document]) -> list[Document]:
        if not self.config.redact_inputs:
            return list(inputs)
        prepared: list[Document] = []
        for document in inputs:
            text, counts = self.redactor.scan(document.text)
            prepared.append(
                replace(document, text=text, metadata={**document.metadata, "redacted": counts})
            )
        return prepared


def _sources_for(run: Run) -> dict[str, str]:
    """The documents a claim in this run is allowed to cite: its own inputs, nothing else."""
    sources: dict[str, str] = {}
    for document in run.inputs:
        key = document.name or document.id
        if key in sources:
            key = f"{key} ({document.id})"
        sources[key] = document.text
    return sources


def _stopped_short(claims: list[Claim], detail: str) -> VerificationReport:
    return VerificationReport(
        verdicts=[
            Verdict(
                claim_id=claim.id,
                outcome=Outcome.INCONCLUSIVE,
                reason=f"verification stopped before this claim: {detail}",
            )
            for claim in claims
        ]
    )


__all__ = ["AgentRunner"]
