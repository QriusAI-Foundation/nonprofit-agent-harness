from __future__ import annotations

import pytest

from nonprofit_harness.core.errors import InvalidRequest, NotFound, ReviewRequired
from nonprofit_harness.core.types import ArtifactStatus, RunStatus


def test_nothing_is_released_until_a_person_approves_it(runner, documents):
    run = runner.start("note", org_id="org_1", inputs=documents)

    with pytest.raises(ReviewRequired):
        runner.gate.release(run)


def test_approving_every_artifact_completes_the_run(runner, documents):
    run = runner.start("note", org_id="org_1", inputs=documents)

    for artifact in list(run.artifacts):
        run = runner.gate.approve(run.id, artifact.id, reviewer="asha@example.org", note="ok")

    assert run.status == RunStatus.COMPLETED
    assert len(runner.gate.release(run)) == 2
    assert all(a.review.reviewer == "asha@example.org" for a in run.artifacts)


def test_a_rejected_artifact_is_never_released(runner, documents):
    run = runner.start("note", org_id="org_1", inputs=documents)
    first, second = run.artifacts

    run = runner.gate.reject(run.id, first.id, reviewer="asha@example.org", note="inaccurate")
    run = runner.gate.approve(run.id, second.id, reviewer="asha@example.org")

    assert run.status == RunStatus.COMPLETED
    released = runner.gate.release(run)
    assert [a.id for a in released] == [second.id]
    assert run.artifact(first.id).status == ArtifactStatus.REJECTED


def test_a_partly_reviewed_run_stays_in_the_queue(runner, documents):
    run = runner.start("note", org_id="org_1", inputs=documents)

    run = runner.gate.approve(run.id, run.artifacts[0].id, reviewer="asha@example.org")

    assert run.status == RunStatus.AWAITING_REVIEW
    assert len(run.pending_review) == 1


def test_an_artifact_cannot_be_reviewed_twice(runner, documents):
    run = runner.start("note", org_id="org_1", inputs=documents)
    artifact_id = run.artifacts[0].id

    runner.gate.approve(run.id, artifact_id, reviewer="asha@example.org")
    with pytest.raises(InvalidRequest, match="already"):
        runner.gate.approve(run.id, artifact_id, reviewer="asha@example.org")


def test_a_review_needs_a_reviewer(runner, documents):
    run = runner.start("note", org_id="org_1", inputs=documents)

    with pytest.raises(InvalidRequest, match="needs a reviewer"):
        runner.gate.approve(run.id, run.artifacts[0].id, reviewer="")


def test_reviewing_an_unknown_artifact_is_not_found(runner, documents):
    run = runner.start("note", org_id="org_1", inputs=documents)

    with pytest.raises(NotFound):
        runner.gate.approve(run.id, "art_missing", reviewer="asha@example.org")


def test_approve_all_clears_the_queue(runner, documents):
    run = runner.start("note", org_id="org_1", inputs=documents)

    run = runner.gate.approve_all(run.id, reviewer="asha@example.org", note="batch")

    assert run.status == RunStatus.COMPLETED
    assert len(runner.gate.release(run)) == 2
