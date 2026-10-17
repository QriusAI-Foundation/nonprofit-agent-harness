from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

import pytest

from nonprofit_harness import Citation, Claim
from nonprofit_harness.config import HarnessConfig
from nonprofit_harness.core import lease
from nonprofit_harness.core.types import Artifact, Run, RunStatus
from nonprofit_harness.verification.types import Outcome

ELSEWHERE = "other-instance:1:abc123"


def _running(stores, *, lease_in: float, phase: str = lease.GENERATING, artifacts=()) -> Run:
    """A run some worker claimed, whose lease ends `lease_in` seconds from now."""
    run = Run(agent="note", org_id="org_1", status=RunStatus.RUNNING, artifacts=list(artifacts))
    run.metadata[lease.EXECUTION] = {
        "worker": ELSEWHERE,
        "lease_expires_at": (datetime.now(UTC) + timedelta(seconds=lease_in)).isoformat(),
        "phase": phase,
    }
    return stores.runs.save(run)


def test_a_run_whose_lease_lapsed_is_failed_as_abandoned(runner, stores):
    run = _running(stores, lease_in=-1)

    reaped = runner.reap_abandoned()

    stored = stores.runs.get(run.id)
    assert [r.id for r in reaped] == [run.id]
    assert stored.status == RunStatus.FAILED
    assert "Abandoned" in stored.error
    assert ELSEWHERE in stored.error
    assert stored.metadata["recovery"]["outcome"] == "failed"


def test_another_workers_leased_run_is_not_failed(runner, stores):
    run = _running(stores, lease_in=600)
    # Old enough to fall to the pre-lease rule, which must not apply to a leased run.
    stores.runs._runs[run.id].updated_at = datetime.now(UTC) - timedelta(days=2)

    assert runner.reap_abandoned(older_than_seconds=0) == []
    assert stores.runs.get(run.id).status == RunStatus.RUNNING


def test_a_second_reap_pass_changes_nothing(runner, stores):
    run = _running(stores, lease_in=-1)
    runner.reap_abandoned()
    after_first = stores.runs.get(run.id)

    assert runner.reap_abandoned() == []
    assert stores.runs.get(run.id).version == after_first.version
    assert stores.runs.get(run.id).error == after_first.error


def test_more_than_one_page_of_candidates_is_reaped(runner, stores):
    lapsed = [_running(stores, lease_in=-1) for _ in range(7)]
    live = [_running(stores, lease_in=600) for _ in range(2)]

    reaped = runner.reap_abandoned(page_size=3)

    assert {r.id for r in reaped} == {r.id for r in lapsed}
    # The oldest record sits past the first page, where a capped list() never looked.
    assert stores.runs.get(lapsed[0].id).status == RunStatus.FAILED
    assert all(stores.runs.get(r.id).status == RunStatus.RUNNING for r in live)


def test_a_run_that_finished_between_listing_and_writing_is_left_alone(runner, stores):
    run = _running(stores, lease_in=-1)
    listed = stores.runs.get(run.id)

    def finish(r):
        r.status = RunStatus.AWAITING_REVIEW
        return True

    stores.runs.update(run.id, finish)
    stores.runs.list = lambda **kwargs: [] if kwargs.get("after") else [listed]

    assert runner.reap_abandoned() == []
    assert stores.runs.get(run.id).status == RunStatus.AWAITING_REVIEW
    assert "recovery" not in stores.runs.get(run.id).metadata


def test_a_stranded_run_that_had_finished_generating_goes_to_review(runner, stores):
    claim = Claim(statement="It happened.", citations=[Citation(text="it happened")])
    artifact = Artifact(kind="brief", content="It happened.", claims=[claim])
    run = _running(stores, lease_in=-1, phase=lease.VERIFYING, artifacts=[artifact])

    runner.reap_abandoned()

    stored = stores.runs.get(run.id)
    assert stored.status == RunStatus.AWAITING_REVIEW
    assert stored.artifacts[0].verification.verdicts[0].outcome == Outcome.INCONCLUSIVE
    assert stored.metadata["recovery"]["outcome"] == "review"
    assert runner.recovery.sent_to_review == 1


def test_a_reap_failure_is_logged_and_counted(runner, stores, caplog):
    broken, fine = _running(stores, lease_in=-1), _running(stores, lease_in=-1)
    update = stores.runs.update

    def flaky(run_id, change):
        if run_id == broken.id:
            raise RuntimeError("write refused")
        return update(run_id, change)

    stores.runs.update = flaky

    with caplog.at_level(logging.INFO, logger="nonprofit_harness.runner"):
        reaped = runner.reap_abandoned()

    assert [r.id for r in reaped] == [fine.id]
    assert runner.recovery.errors == 1
    assert broken.id in runner.recovery.last_error
    assert f"Recovery could not resolve run {broken.id}" in caplog.text
    assert "failed 1 as abandoned, sent 0 to review, 1 error(s)" in caplog.text


def test_a_listing_failure_is_counted_not_raised(runner, stores):
    def explode(**kwargs):
        raise RuntimeError("storage is down")

    stores.runs.list = explode

    assert runner.reap_abandoned() == []
    assert runner.recovery.errors == 1
    assert "storage is down" in runner.recovery.last_error


def test_every_pass_logs_its_counts(runner, stores, caplog):
    _running(stores, lease_in=600)

    with caplog.at_level(logging.INFO, logger="nonprofit_harness.runner"):
        runner.reap_abandoned()

    assert "Recovery pass: examined 1 running run(s); failed 0 as abandoned" in caplog.text


def test_a_skipped_run_is_reaped_after_its_lease_lapses_without_a_restart(
    registry, stores, provider
):
    from fastapi.testclient import TestClient

    from nonprofit_harness.api.app import create_app

    run = _running(stores, lease_in=0.5)
    config = HarnessConfig(max_tokens=None, max_calls=None, reap_interval_seconds=0.05)

    with TestClient(create_app(config=config, registry=registry, stores=stores, provider=provider)):
        # Too young at startup, so the startup pass left it.
        assert stores.runs.get(run.id).status == RunStatus.RUNNING
        deadline = time.monotonic() + 5
        while stores.runs.get(run.id).status == RunStatus.RUNNING:
            assert time.monotonic() < deadline, "the periodic reaper never resolved the run"
            time.sleep(0.05)

    assert stores.runs.get(run.id).status == RunStatus.FAILED


def test_the_admin_config_reports_recovery_counts(stores, client):
    _running(stores, lease_in=-1)

    with client:
        body = client.get("/v1/admin/config").json()

    assert body["recovery"]["failed_as_abandoned"] == 1
    assert body["recovery"]["errors"] == 0
    assert body["recovery"]["lease_seconds"] == 120


@pytest.mark.parametrize(
    ("raw", "expected"), [(None, 300.0), ("0", 0.0), ("off", 0.0), ("30", 30.0)]
)
def test_the_reap_interval_reads_from_the_environment(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("HARNESS_REAP_INTERVAL_SECONDS", raising=False)
    else:
        monkeypatch.setenv("HARNESS_REAP_INTERVAL_SECONDS", raw)

    assert HarnessConfig.from_env().reap_interval_seconds == expected
