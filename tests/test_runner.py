from __future__ import annotations

import pytest

from nonprofit_harness import Agent, AgentResult, RunContext
from nonprofit_harness.core.types import ArtifactStatus, RunStatus
from nonprofit_harness.review.gate import AUTO_REVIEWER


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
