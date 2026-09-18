from __future__ import annotations

import pytest

from nonprofit_harness import Agent, AgentResult, Citation, Claim, RunContext
from nonprofit_harness.core.types import ArtifactStatus, Document, RunStatus

SOURCE = (
    "The literacy programme reached twelve villages during the third quarter. "
    "Two facilitators resigned in August and have not yet been replaced."
)


class CitingAgent(Agent):
    name = "citing"
    description = "Makes a claim and cites the source for it."

    def run(self, ctx: RunContext) -> AgentResult:
        return AgentResult(
            artifacts=[
                self.artifact(
                    "brief",
                    "The programme reached twelve villages.",
                    claims=[
                        Claim(
                            statement="The programme reached twelve villages.",
                            citations=[Citation(text="reached twelve villages")],
                        )
                    ],
                )
            ]
        )


class FabricatingAgent(Agent):
    name = "fabricating"
    description = "Cites something that is not in the source."

    def run(self, ctx: RunContext) -> AgentResult:
        return AgentResult(
            artifacts=[
                self.artifact(
                    "brief",
                    "The programme reached ninety villages.",
                    claims=[
                        Claim(
                            statement="The programme reached ninety villages.",
                            citations=[Citation(text="reached ninety villages")],
                        )
                    ],
                )
            ]
        )


class UnreviewedFabricatingAgent(FabricatingAgent):
    name = "fabricating-unreviewed"
    requires_review = False


class UnreviewedCitingAgent(CitingAgent):
    name = "citing-unreviewed"
    requires_review = False


@pytest.fixture
def inputs() -> list[Document]:
    return [Document(text=SOURCE, name="q3-report.txt")]


@pytest.fixture(autouse=True)
def register(runner):
    for agent in (
        CitingAgent(),
        FabricatingAgent(),
        UnreviewedFabricatingAgent(),
        UnreviewedCitingAgent(),
    ):
        runner.registry.register(agent)


def test_a_well_cited_artifact_verifies(runner, inputs):
    run = runner.start("citing", org_id="org_1", inputs=inputs)
    artifact = run.artifacts[0]

    assert artifact.verification is not None
    assert artifact.verification.ok
    assert not artifact.failed_verification
    assert run.status == RunStatus.AWAITING_REVIEW


def test_a_fabricated_citation_is_flagged_for_the_reviewer(runner, inputs):
    run = runner.start("fabricating", org_id="org_1", inputs=inputs)
    artifact = run.artifacts[0]

    assert artifact.failed_verification
    assert run.unverified == [artifact]
    assert "citation not found" in artifact.verification.summary()


def test_verification_does_not_fail_the_run_it_routes_it_to_a_person(runner, inputs):
    run = runner.start("fabricating", org_id="org_1", inputs=inputs)

    assert run.status == RunStatus.AWAITING_REVIEW
    assert run.error == ""
    assert len(run.pending_review) == 1


def test_an_agent_cannot_auto_release_an_artifact_that_failed_verification(runner, inputs):
    run = runner.start("fabricating-unreviewed", org_id="org_1", inputs=inputs)

    assert run.status == RunStatus.AWAITING_REVIEW
    assert run.artifacts[0].status == ArtifactStatus.PENDING_REVIEW
    assert run.artifacts[0].review is None


def test_a_clean_artifact_still_auto_releases(runner, inputs):
    run = runner.start("citing-unreviewed", org_id="org_1", inputs=inputs)

    assert run.status == RunStatus.COMPLETED
    assert run.artifacts[0].status == ArtifactStatus.APPROVED


def test_a_reviewer_can_still_approve_a_flagged_artifact(runner, inputs):
    run = runner.start("fabricating", org_id="org_1", inputs=inputs)

    run = runner.gate.approve(
        run.id, run.artifacts[0].id, reviewer="asha@example.org", note="checked by hand"
    )

    assert run.status == RunStatus.COMPLETED
    assert runner.gate.release(run)


def test_claims_are_only_checked_against_this_run_s_own_inputs(runner):
    run = runner.start(
        "citing",
        org_id="org_1",
        inputs=[Document(text="An unrelated budget note.", name="other.txt")],
    )

    assert run.artifacts[0].failed_verification


def test_verification_can_be_switched_off(runner, inputs):
    runner.config.verify_claims = False
    run = runner.start("fabricating", org_id="org_1", inputs=inputs)

    assert run.artifacts[0].verification is None
    assert run.status == RunStatus.AWAITING_REVIEW


def test_citation_checking_spends_nothing(runner, inputs):
    run = runner.start("citing", org_id="org_1", inputs=inputs)

    # The agent itself made no model call, and verification must not add one.
    assert run.usage.calls == 0


def test_verification_survives_storage(runner, stores, inputs):
    run = runner.start("fabricating", org_id="org_1", inputs=inputs)

    restored = stores.runs.get(run.id)
    artifact = restored.artifacts[0]

    assert artifact.failed_verification
    assert artifact.claims[0].citations[0].text == "reached ninety villages"
    assert artifact.verification.summary() == run.artifacts[0].verification.summary()


def test_the_api_shows_a_reviewer_what_failed(client):
    run = client.post(
        "/v1/runs",
        json={
            "agent": "fabricating",
            "inputs": [{"text": SOURCE, "name": "q3-report.txt"}],
            "sync": True,
        },
    ).json()

    assert run["failed_verification"] == 1
    artifact = run["artifacts"][0]
    assert artifact["verification"]["ok"] is False
    assert artifact["verification"]["verdicts"][0]["outcome"] == "citation_not_found"
    assert artifact["claims"][0]["citations"][0]["text"] == "reached ninety villages"
