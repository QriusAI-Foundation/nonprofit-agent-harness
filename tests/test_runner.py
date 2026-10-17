from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from nonprofit_harness import Agent, AgentResult, Citation, Claim, RunContext
from nonprofit_harness.api.schemas import RunOut
from nonprofit_harness.config import HarnessConfig
from nonprofit_harness.core import lease
from nonprofit_harness.core.errors import ProviderError, ReviewRequired
from nonprofit_harness.core.runner import AgentRunner
from nonprofit_harness.core.types import ArtifactStatus, Document, Run, RunStatus, Usage
from nonprofit_harness.providers.echo import EchoProvider
from nonprofit_harness.review.gate import AUTO_REVIEWER, ReviewGate
from nonprofit_harness.verification.types import Outcome


def test_run_produces_artifacts_and_waits_for_review(runner, documents):
    run = runner.start("note", org_id="org_1", inputs=documents)

    assert run.status == RunStatus.AWAITING_REVIEW
    assert len(run.artifacts) == 2
    assert all(a.status == ArtifactStatus.PENDING_REVIEW for a in run.artifacts)
    assert run.summary == "2 note(s)"


def test_usage_is_recorded_on_the_run(runner, documents):
    run = runner.start("note", org_id="org_1", inputs=documents)

    assert run.usage.calls == 2
    assert run.usage.input_tokens > 0
    assert run.usage.output_tokens > 0


def test_agent_can_opt_out_of_review_but_the_decision_is_still_recorded(runner, documents):
    run = runner.start("open", org_id="org_1", inputs=documents)

    assert run.status == RunStatus.COMPLETED
    assert all(a.status == ArtifactStatus.APPROVED for a in run.artifacts)
    assert all(a.review.reviewer == AUTO_REVIEWER for a in run.artifacts)


def test_a_failing_agent_becomes_a_failed_run_not_an_exception(runner, documents):
    run = runner.start("broken", org_id="org_1", inputs=documents)

    assert run.status == RunStatus.FAILED
    assert "broken on purpose" in run.error
    assert run.artifacts == []


def test_run_is_persisted_and_listable(runner, stores, documents):
    run = runner.start("note", org_id="org_1", inputs=documents)

    fetched = stores.runs.get(run.id)
    assert fetched.id == run.id
    assert len(stores.runs.list(org_id="org_1")) == 1
    assert stores.runs.list(org_id="org_other") == []


def test_agent_receives_only_its_context(runner, stores, documents):
    seen = {}

    class InspectingAgent(Agent):
        name = "inspecting"

        def run(self, ctx: RunContext) -> AgentResult:
            seen["org"] = ctx.org_id
            seen["run"] = ctx.run_id
            seen["option"] = ctx.option("tone", "neutral")
            return AgentResult(artifacts=[self.artifact("x", "y")])

    runner.registry.register(InspectingAgent())
    run = runner.start("inspecting", org_id="org_9", inputs=documents, options={"tone": "warm"})

    assert seen["org"] == "org_9"
    assert seen["run"] == run.id
    assert seen["option"] == "warm"


def test_concrete_agent_without_a_name_is_rejected_at_class_creation():
    with pytest.raises(TypeError, match="must set a class-level `name`"):

        class Nameless(Agent):
            def run(self, ctx: RunContext) -> AgentResult:
                return AgentResult()


# --- finished work survives verification failing ------------------------------------

SOURCE = "The literacy programme reached twelve villages during the third quarter."


class CitingNoteAgent(Agent):
    name = "citing-note"
    description = "Calls the model once, then makes one claim that cites the source."

    def run(self, ctx: RunContext) -> AgentResult:
        response = ctx.provider.generate("Summarise the report.")
        claim = Claim(
            statement="The programme reached twelve villages.",
            citations=[Citation(text="reached twelve villages")],
        )
        return AgentResult(
            artifacts=[self.artifact("brief", response.text, claims=[claim])],
            summary="1 brief",
        )


class UnreviewedCitingNoteAgent(CitingNoteAgent):
    name = "citing-note-unreviewed"
    requires_review = False


class OutageAfter(EchoProvider):
    """Answers the agent, then fails, as a provider outage during checking would."""

    def __init__(self, healthy_calls: int, on_outage=None) -> None:
        super().__init__()
        self._left = healthy_calls
        self._on_outage = on_outage or (lambda: None)

    def generate(self, prompt, **kwargs):
        if self._left <= 0:
            self._on_outage()
            raise ConnectionError("provider unavailable")
        self._left -= 1
        return super().generate(prompt, **kwargs)


@pytest.fixture
def source() -> list[Document]:
    return [Document(text=SOURCE, name="q3-report.txt")]


def _checking_runner(registry, stores, provider, **config) -> AgentRunner:
    """Cross-checking on, so verification calls the model and can meet an outage."""
    registry.register(CitingNoteAgent())
    registry.register(UnreviewedCitingNoteAgent())
    return AgentRunner(
        registry=registry,
        stores=stores,
        provider=provider,
        config=HarnessConfig(max_tokens=None, max_calls=None, verify_passes=1, **config),
        gate=ReviewGate(stores.runs),
    )


def test_a_provider_error_during_verification_keeps_the_artifacts_and_usage(
    registry, stores, source
):
    runner = _checking_runner(registry, stores, OutageAfter(healthy_calls=1))

    run = runner.start("citing-note", org_id="org_1", inputs=source)

    stored = stores.runs.get(run.id)
    assert len(stored.artifacts) == 1
    assert stored.artifacts[0].content
    assert stored.summary == "1 brief"
    # The agent's call, plus the verification call that failed: a failed call still
    # counts toward the ceiling.
    assert stored.usage.calls == 2


def test_a_billed_provider_error_during_verification_stays_in_the_run_s_usage(
    registry, stores, source
):
    class BilledOutage(OutageAfter):
        def generate(self, prompt, **kwargs):
            if self._left <= 0:
                raise ProviderError("refused", usage=Usage(calls=1, input_tokens=500))
            return super().generate(prompt, **kwargs)

    runner = _checking_runner(registry, stores, BilledOutage(healthy_calls=1))

    run = runner.start("citing-note", org_id="org_1", inputs=source)

    stored = stores.runs.get(run.id)
    assert stored.status == RunStatus.AWAITING_REVIEW
    assert stored.usage.calls == 2
    assert stored.usage.input_tokens > 500


def test_a_provider_error_during_verification_ends_in_review_not_running(registry, stores, source):
    runner = _checking_runner(registry, stores, OutageAfter(healthy_calls=1))

    run = runner.start("citing-note", org_id="org_1", inputs=source)

    assert stores.runs.get(run.id).status == RunStatus.AWAITING_REVIEW
    assert stores.runs.get(run.id).artifacts[0].status == ArtifactStatus.PENDING_REVIEW


def test_the_reviewer_sees_why_checking_was_incomplete(registry, stores, source):
    runner = _checking_runner(registry, stores, OutageAfter(healthy_calls=1))

    run = runner.start("citing-note", org_id="org_1", inputs=source)

    shown = RunOut.of(stores.runs.get(run.id))
    verdict = shown.artifacts[0].verification["verdicts"][0]
    assert verdict["outcome"] == str(Outcome.INCONCLUSIVE)
    assert "verification stopped" in verdict["reason"]
    assert "provider unavailable" in verdict["reason"]
    assert shown.failed_verification == 1


def test_auto_release_stays_blocked_after_a_verification_failure(registry, stores, source):
    runner = _checking_runner(registry, stores, OutageAfter(healthy_calls=1))

    run = runner.start("citing-note-unreviewed", org_id="org_1", inputs=source)

    stored = stores.runs.get(run.id)
    assert stored.status == RunStatus.AWAITING_REVIEW
    assert stored.artifacts[0].review is None
    with pytest.raises(ReviewRequired):
        ReviewGate.release(stored)


def test_the_work_is_stored_before_verification_can_fail(registry, stores, source):
    seen = {}

    def look_at_the_store():
        (stored,) = stores.runs.list(status=RunStatus.RUNNING)
        seen["artifacts"] = len(stored.artifacts)
        seen["calls"] = stored.usage.calls

    runner = _checking_runner(
        registry, stores, OutageAfter(healthy_calls=1, on_outage=look_at_the_store)
    )
    runner.start("citing-note", org_id="org_1", inputs=source)

    assert seen == {"artifacts": 1, "calls": 1}


# --- completed work against the reaper ----------------------------------------------


def _lapse_lease(run: Run) -> bool:
    run.metadata[lease.EXECUTION]["lease_expires_at"] = (
        datetime.now(UTC) - timedelta(seconds=1)
    ).isoformat()
    return True


def test_a_run_marked_abandoned_while_the_agent_ran_keeps_its_completed_work(
    runner, stores, documents
):
    class SlowAgent(Agent):
        name = "slow"

        def run(self, ctx: RunContext) -> AgentResult:
            # Another instance's reaper judges this run dead while the agent works.
            stores.runs.update(ctx.run_id, _lapse_lease)
            assert [r.id for r in runner.reap_abandoned()] == [ctx.run_id]
            assert stores.runs.get(ctx.run_id).status == RunStatus.FAILED
            response = ctx.provider.generate("still working")
            return AgentResult(artifacts=[self.artifact("note", response.text)], summary="ok")

    runner.registry.register(SlowAgent())

    run = runner.start("slow", org_id="org_1", inputs=documents)

    stored = stores.runs.get(run.id)
    assert stored.status == RunStatus.AWAITING_REVIEW
    assert len(stored.artifacts) == 1
    assert stored.usage.calls == 1
    assert stored.error == ""
    assert stored.metadata["recovery"]["outcome"] == "failed"
    assert "completed work was kept" in stored.metadata["recovery"]["superseded"]


def test_a_run_stranded_during_verification_goes_to_review_with_its_work(registry, stores, source):
    holder = {}

    def another_instance_reaps():
        (stored,) = stores.runs.list(status=RunStatus.RUNNING)
        stores.runs.update(stored.id, _lapse_lease)
        holder["runner"].reap_abandoned()

    runner = _checking_runner(
        registry, stores, OutageAfter(healthy_calls=1, on_outage=another_instance_reaps)
    )
    holder["runner"] = runner

    run = runner.start("citing-note-unreviewed", org_id="org_1", inputs=source)

    stored = stores.runs.get(run.id)
    assert run.status == stored.status == RunStatus.AWAITING_REVIEW
    assert stored.artifacts[0].status == ArtifactStatus.PENDING_REVIEW
    assert stored.usage.calls == 1
    # Recovery's verdict, not the late worker's ("provider unavailable"): a run already
    # in front of a person is not overwritten.
    reason = stored.artifacts[0].verification.verdicts[0].reason
    assert "stopped during verification" in reason
    assert "provider unavailable" not in reason
    # The note goes to metadata, which the API shows. A non-empty error reads as failed.
    assert stored.error == ""
    note = RunOut.of(stored).metadata["recovery"]
    assert note["outcome"] == "review"
    assert "stopped before verification completed" in note["note"]


def test_the_heartbeat_renews_the_lease_while_the_agent_works(registry, stores, documents):
    renewed = {}

    class PatientAgent(Agent):
        name = "patient"

        def run(self, ctx: RunContext) -> AgentResult:
            first = lease.expires_at(stores.runs.get(ctx.run_id))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if lease.expires_at(stores.runs.get(ctx.run_id)) != first:
                    renewed["yes"] = True
                    break
                time.sleep(0.05)
            return AgentResult(artifacts=[self.artifact("note", "done")])

    registry.register(PatientAgent())
    runner = AgentRunner(
        registry=registry,
        stores=stores,
        provider=EchoProvider(),
        config=HarnessConfig(max_tokens=None, max_calls=None, run_lease_seconds=1),
    )

    runner.start("patient", org_id="org_1", inputs=documents)

    assert renewed == {"yes": True}


def test_a_hung_run_stops_renewing_its_lease_after_the_run_timeout(stores):
    run = stores.runs.save(Run(agent="note", org_id="org_1", status=RunStatus.RUNNING))
    run = stores.runs.update(run.id, lambda r: lease.claim(r, worker="me", lease_seconds=1) or True)
    before = lease.expires_at(run)

    with lease.Heartbeat(stores.runs, run.id, worker="me", lease_seconds=1, max_seconds=0):
        time.sleep(0.6)

    assert lease.expires_at(stores.runs.get(run.id)) == before


def test_a_brief_store_outage_does_not_lose_the_finished_work(runner, stores, documents):
    update = stores.runs.update
    outage = {"left": 1}

    def flaky(run_id, change):
        if outage["left"] and lease.phase(stores.runs.get(run_id)) == lease.GENERATING:
            stored = stores.runs.get(run_id)
            if stored.status == RunStatus.RUNNING and not stored.artifacts:
                outage["left"] -= 1
                raise ConnectionError("store unavailable")
        return update(run_id, change)

    stores.runs.update = flaky
    runner.registry.register(_ReturnsWork())

    run = runner.start("returns-work", org_id="org_1", inputs=documents)

    assert outage["left"] == 0
    assert stores.runs.get(run.id).status == RunStatus.AWAITING_REVIEW
    assert len(stores.runs.get(run.id).artifacts) == 1


class _ReturnsWork(Agent):
    name = "returns-work"

    def run(self, ctx: RunContext) -> AgentResult:
        return AgentResult(
            artifacts=[self.artifact("note", "done")],
            metadata={"execution": "agent says hi", "source": "agent"},
        )


def test_an_agent_cannot_overwrite_the_harness_s_execution_record(
    runner, stores, documents, caplog
):
    runner.registry.register(_ReturnsWork())

    run = runner.start("returns-work", org_id="org_1", inputs=documents)

    stored = stores.runs.get(run.id)
    assert stored.metadata["source"] == "agent"
    assert stored.metadata["execution"]["worker"] == runner.worker_id
    assert "harness-owned key(s) execution" in caplog.text


@pytest.mark.parametrize(
    "change",
    [
        lambda r: setattr(r, "status", RunStatus.FAILED),
        lambda r: r.metadata[lease.EXECUTION].update(worker="someone-else"),
    ],
    ids=["no-longer-running", "held-by-another-worker"],
)
def test_the_heartbeat_never_renews_a_run_it_no_longer_owns(stores, change):
    run = stores.runs.save(Run(agent="note", org_id="org_1", status=RunStatus.RUNNING))
    stores.runs.update(run.id, lambda r: lease.claim(r, worker="me", lease_seconds=1) or True)
    run = stores.runs.update(run.id, lambda r: change(r) or True)
    before = (run.version, lease.expires_at(run))

    with lease.Heartbeat(stores.runs, run.id, worker="me", lease_seconds=1, max_seconds=60):
        time.sleep(0.6)

    after = stores.runs.get(run.id)
    assert (after.version, lease.expires_at(after)) == before
