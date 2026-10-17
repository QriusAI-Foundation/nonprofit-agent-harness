from __future__ import annotations

import copy
import logging
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from nonprofit_harness.config import HarnessConfig
from nonprofit_harness.core import lease
from nonprofit_harness.core.agent import Agent, RunContext
from nonprofit_harness.core.errors import BudgetExceeded, HarnessError
from nonprofit_harness.core.registry import AgentRegistry
from nonprofit_harness.core.types import Document, Run, RunStatus
from nonprofit_harness.guardrails.budget import BudgetedProvider, BudgetGuard
from nonprofit_harness.guardrails.redaction import Redactor
from nonprofit_harness.providers.base import ModelProvider
from nonprofit_harness.review.gate import (
    ReviewGate,
    hold_for_review,
    release_routine,
    take_custody,
)
from nonprofit_harness.storage.base import Stores
from nonprofit_harness.verification import GroundingVerifier
from nonprofit_harness.verification.types import Claim, Outcome, Verdict, VerificationReport

logger = logging.getLogger("nonprofit_harness.runner")

#: Metadata key recovery writes when it resolves a stranded run.
RECOVERY = "recovery"
_HARNESS_KEYS = {lease.EXECUTION, RECOVERY}


class _Superseded(Exception):
    """The stored run moved on (finished elsewhere, or decided) while this worker ran."""


@dataclass(slots=True)
class RecoveryStats:
    """Counts since this process started, so a stuck recovery is visible from outside."""

    passes: int = 0
    failed_as_abandoned: int = 0
    sent_to_review: int = 0
    errors: int = 0
    last_pass_at: str | None = None
    last_error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    worker_id: str = field(default_factory=lease.new_worker_id)
    recovery: RecoveryStats = field(default_factory=RecoveryStats)

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
        agent = self.registry.get(self.stores.runs.get(run_id).agent)
        run = self.stores.runs.update(run_id, self._claim)

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

        with lease.Heartbeat(
            self.stores.runs,
            run.id,
            worker=self.worker_id,
            lease_seconds=self.config.run_lease_seconds,
            max_seconds=self.config.run_timeout_seconds,
        ):
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
            run.usage = guard.spent
            try:
                return self._finish(run, agent, provider, guard)
            except _Superseded:
                return self.stores.runs.get(run.id)

    def _finish(
        self, run: Run, agent: Agent, provider: BudgetedProvider, guard: BudgetGuard
    ) -> Run:
        # The work exists and is paid for from here on. It is stored before
        # verification, which can call a model and so can fail, hang, or outlive the
        # process; whatever happens next, the work is not lost.
        run = self._land(run, self._hold_for_verification)

        # Before usage is banked, so cross-checking shows up in the run's own cost.
        self._verify_claims(run, provider)
        run.usage = guard.spent

        if agent.requires_review:
            return self._land(run, hold_for_review)
        reason = f"{agent.name} declares requires_review=False"
        return self._land(run, lambda stored: release_routine(stored, reason=reason))

    def _claim(self, run: Run) -> bool:
        run.status = RunStatus.RUNNING
        lease.claim(run, worker=self.worker_id, lease_seconds=self.config.run_lease_seconds)
        return True

    def _hold_for_verification(self, run: Run) -> None:
        take_custody(run)
        lease.extend(
            run,
            worker=self.worker_id,
            lease_seconds=self.config.run_lease_seconds,
            phase=lease.VERIFYING,
        )

    def _land(self, work: Run, finish: Callable[[Run], None]) -> Run:
        """Write this worker's copy of the run onto whatever is stored now.

        The runner holds one Run for the whole agent call, while the heartbeat and
        the reaper write to the stored one. A compare-and-set save would refuse it,
        so the result goes in through `update` instead, under one rule: completed
        work wins over an abandonment mark. If recovery failed the run as abandoned
        while the agent was in fact still working, the finished artifacts and usage
        land anyway and the abandonment stays on record in the run's metadata.

        A run that recovery sent to review, or that finished elsewhere, is left as
        it is: people may already be deciding on it.
        """

        def change(stored: Run) -> bool:
            if not _landable(stored):
                raise _Superseded(stored.status)
            if stored.status == RunStatus.FAILED:
                _revive(stored)
            stored.artifacts = copy.deepcopy(work.artifacts)
            stored.summary = work.summary
            stored.usage = work.usage
            stored.metadata.update(
                {k: v for k, v in work.metadata.items() if k not in _HARNESS_KEYS}
            )
            lease.extend(stored, worker=self.worker_id, lease_seconds=self.config.run_lease_seconds)
            finish(stored)
            return True

        try:
            return self.stores.runs.update(work.id, change)
        except _Superseded as exc:
            logger.warning(
                "Run %s is already %s; this worker's result for it was not written",
                work.id,
                exc,
            )
            raise

    def _verify_claims(self, run: Run, provider: BudgetedProvider) -> None:
        """Check claims, and never let a failure here cost the run its work.

        Verification reports to a person; it does not judge. So when it cannot finish,
        for any reason, the artifacts it did not reach are marked inconclusive with
        the reason, which holds them for review even when the agent opted out.
        """
        if not self.config.verify_claims:
            return
        pending = [artifact for artifact in run.artifacts if artifact.claims]
        if not pending:
            return

        try:
            sources = _sources_for(run)
            verifier = GroundingVerifier(
                provider=provider if self.config.verify_passes > 0 else None,
                passes=self.config.verify_passes,
                models=self.config.verify_models,
            )
            while pending:
                pending[0].verification = verifier.verify_all(pending[0].claims, sources)
                pending.pop(0)
            return
        except BudgetExceeded as exc:
            # The agent's work is already done and already paid for. Throwing the
            # run away because the checking ran out of budget would destroy more
            # than it protects, so what is left goes to a person instead.
            detail = str(exc)
            logger.warning("Verification stopped at the budget ceiling on run %s", run.id)
        except Exception as exc:  # noqa: BLE001 - a checking outage must not lose the work
            detail = f"{type(exc).__name__}: {exc}"
            logger.exception("Verification failed on run %s", run.id)
        for remaining in pending:
            remaining.verification = _stopped_short(remaining.claims, detail)

    def reap_abandoned(
        self, *, older_than_seconds: int | None = None, page_size: int = 200
    ) -> list[Run]:
        """Resolve runs left in `running` by a process that is no longer there.

        Runs execute in the web process, so an instance being recycled mid-run leaves a
        record nobody will ever update again. A poller would wait on it forever.

        Called at startup and then periodically, so a run that was too young to judge
        on one pass is judged on a later one. Every running run is examined, a page at
        a time, not only the newest.

        A run is due when its lease has lapsed: its worker stopped renewing it, so that
        worker is gone. A run another live worker holds is never touched. Runs written
        before leases existed have none, and fall back to the old rule: due once they
        have sat in `running` longer than `older_than_seconds`.

        Each run is resolved in one atomic update that re-checks it, so a run that
        finished between the listing and the write is left alone, and a second pass
        finds nothing left to do.
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(
            seconds=older_than_seconds
            if older_than_seconds is not None
            else self.config.run_timeout_seconds
        )
        stamp = now.isoformat()
        stats = self.recovery
        stats.passes += 1
        stats.last_pass_at = stamp

        examined = errors = 0
        resolved: list[Run] = []
        try:
            for candidate in self._running(page_size):
                examined += 1
                if _overdue(candidate, now, cutoff) is None:
                    continue
                try:
                    run = self.stores.runs.update(
                        candidate.id, lambda r: _resolve(r, now, cutoff, stamp)
                    )
                except Exception as exc:  # noqa: BLE001 - one bad record must not stop the pass
                    errors += 1
                    stats.last_error = f"{candidate.id}: {type(exc).__name__}: {exc}"
                    logger.exception("Recovery could not resolve run %s", candidate.id)
                    continue
                if run.metadata.get(RECOVERY, {}).get("at") == stamp:
                    resolved.append(run)
        except Exception as exc:  # noqa: BLE001 - reported below, retried next pass
            errors += 1
            stats.last_error = f"listing running runs: {type(exc).__name__}: {exc}"
            logger.exception("Recovery could not list running runs")

        failed = sum(1 for r in resolved if r.status == RunStatus.FAILED)
        stats.failed_as_abandoned += failed
        stats.sent_to_review += len(resolved) - failed
        stats.errors += errors
        logger.log(
            logging.WARNING if resolved or errors else logging.INFO,
            "Recovery pass: examined %d running run(s); failed %d as abandoned, "
            "sent %d to review, %d error(s)",
            examined,
            failed,
            len(resolved) - failed,
            errors,
        )
        return resolved

    def _running(self, page_size: int) -> Iterator[Run]:
        after: str | None = None
        while True:
            page = self.stores.runs.list(status=RunStatus.RUNNING, limit=page_size, after=after)
            yield from page
            if len(page) < page_size:
                return
            after = page[-1].id

    def _fail(self, run: Run, guard: BudgetGuard, message: str) -> Run:
        spent = guard.spent

        def change(stored: Run) -> bool:
            if not _landable(stored):
                raise _Superseded(stored.status)
            stored.status = RunStatus.FAILED
            stored.error = message
            stored.usage = spent
            return True

        try:
            return self.stores.runs.update(run.id, change)
        except _Superseded:
            return self.stores.runs.get(run.id)

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


def _landable(stored: Run) -> bool:
    """Whether this worker's result may still be written onto the stored run."""
    if stored.status == RunStatus.RUNNING:
        return True
    return (
        stored.status == RunStatus.FAILED
        and stored.metadata.get(RECOVERY, {}).get("outcome") == "failed"
    )


def _revive(run: Run) -> None:
    note = run.metadata[RECOVERY]
    note["superseded"] = (
        "The run finished after it was marked abandoned. Its completed work was kept."
    )
    logger.warning(
        "Run %s finished after recovery marked it abandoned; keeping its completed work",
        run.id,
    )
    run.status = RunStatus.RUNNING
    run.error = ""


def _overdue(run: Run, now: datetime, cutoff: datetime) -> str | None:
    """Why a running run counts as stranded, or None while it may still be alive."""
    expiry = lease.expires_at(run)
    if expiry is not None:
        if expiry >= now:
            return None
        return f"worker {lease.holder(run)} stopped renewing its lease at {expiry.isoformat()}"
    updated = run.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    if updated >= cutoff:
        return None
    return f"it was still marked running after {int((now - updated).total_seconds())}s"


def _resolve(run: Run, now: datetime, cutoff: datetime, stamp: str) -> bool:
    # Judged again on the stored copy: the run may have finished or renewed since it
    # was listed.
    reason = _overdue(run, now, cutoff) if run.status == RunStatus.RUNNING else None
    if reason is None:
        return False
    if lease.phase(run) == lease.VERIFYING and run.artifacts:
        _send_to_review(run, reason)
        outcome = "review"
    else:
        run.status = RunStatus.FAILED
        run.error = f"Abandoned. The process running it stopped before it finished: {reason}."
        outcome = "failed"
    run.metadata[RECOVERY] = {"at": stamp, "reason": reason, "outcome": outcome}
    return True


def _send_to_review(run: Run, reason: str) -> None:
    """The agent had finished; only checking was cut off. A person gets the work.

    Always review, even for an agent that opted out: nothing about this output was
    checked, and auto-release exists only for output the harness found routine.
    """
    detail = f"the process running this run stopped during verification ({reason})"
    for artifact in run.artifacts:
        if artifact.claims and artifact.verification is None:
            artifact.verification = _stopped_short(artifact.claims, detail)
    hold_for_review(run)
    run.error = (
        "Recovered: the agent finished, but its process stopped before verification "
        "completed. The work was sent to review with checking incomplete."
    )


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


__all__ = ["RECOVERY", "AgentRunner", "RecoveryStats"]
