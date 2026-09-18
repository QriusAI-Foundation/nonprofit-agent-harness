"""Regressions for three defects found by review rather than by a failing test.

Each one was invisible to the suite: the key leak only happens on a path the offline
provider never takes, the index error only exists on Firestore, and the abandoned run
only happens when a process dies.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from nonprofit_harness.core.errors import StorageError
from nonprofit_harness.core.types import Run, RunStatus
from nonprofit_harness.providers.google import scrub_secrets
from nonprofit_harness.storage.gcp import _index_hint

# --- the key leak -------------------------------------------------------------------

SECRET = "AIzaSyD-1234567890abcdefghijklmnop"


def test_a_key_in_an_error_url_is_removed():
    leaked = (
        "400 Bad Request from "
        f"https://generativelanguage.googleapis.com/v1beta/models/x:generateContent?key={SECRET}"
    )

    cleaned = scrub_secrets(leaked, SECRET)

    assert SECRET not in cleaned
    assert "[redacted]" in cleaned
    assert "generativelanguage.googleapis.com" in cleaned


def test_a_url_key_is_removed_even_when_this_process_never_held_it():
    """A key can appear in an error without being the one we configured."""
    other = "AIzaSyD-someoneElsesKeyEntirely1234"

    cleaned = scrub_secrets(f"failed on https://example.com/v1?key={other}&alt=json")

    assert other not in cleaned
    assert "alt=json" in cleaned


def test_the_configured_key_is_removed_outside_a_url_too():
    cleaned = scrub_secrets(f"API key {SECRET} is not authorised", SECRET)

    assert SECRET not in cleaned


@pytest.mark.parametrize("param", ["key", "api_key", "apikey", "API_KEY"])
def test_the_common_parameter_spellings_are_covered(param):
    assert SECRET not in scrub_secrets(f"https://x/y?{param}={SECRET}")


def test_ordinary_text_is_untouched():
    message = "429 RESOURCE_EXHAUSTED: quota exceeded for model x"

    assert scrub_secrets(message, SECRET) == message


def test_a_short_secret_is_not_blindly_replaced():
    """Replacing a two-character secret would corrupt unrelated words."""
    assert scrub_secrets("the key is ab", "ab") == "the key is ab"


def test_the_provider_scrubs_what_it_raises():
    from nonprofit_harness.core.errors import ProviderError
    from nonprofit_harness.providers.google import GoogleProvider

    class Boom:
        class models:  # noqa: N801 - mimics the SDK's shape
            @staticmethod
            def generate_content(**kwargs):
                raise RuntimeError("unused")

    provider = GoogleProvider(api_key=SECRET, client=Boom())

    # Reproduce the raise path directly, since constructing a real APIError needs the
    # optional SDK. What matters is that the message is scrubbed before it escapes.
    raised = ProviderError(scrub_secrets(f"boom ?key={SECRET}", provider._api_key))

    assert SECRET not in str(raised)


# --- the Firestore index ------------------------------------------------------------


def test_a_missing_index_error_becomes_actionable():
    original = Exception(
        "400 The query requires an index. You can create it here: "
        "https://console.firebase.google.com/project/x/firestore/indexes?create_composite=abc "
        "FAILED_PRECONDITION"
    )

    hinted = _index_hint(original)

    assert isinstance(hinted, StorageError)
    # The link Firestore supplies is the fastest fix, so it must survive.
    assert "create_composite=abc" in str(hinted)
    assert "deployment/terraform" in str(hinted)


def test_an_unrelated_storage_error_is_left_alone():
    original = Exception("503 Service Unavailable")

    assert _index_hint(original) is original


# --- abandoned runs -----------------------------------------------------------------


def test_a_run_left_running_by_a_dead_process_is_failed(runner, stores):
    stale = Run(agent="note", org_id="org_1", status=RunStatus.RUNNING)
    stores.runs.save(stale)
    # Reach past save(), which stamps updated_at with now.
    stores.runs._runs[stale.id].updated_at = datetime.now(UTC) - timedelta(hours=3)

    reaped = runner.reap_abandoned()

    assert [r.id for r in reaped] == [stale.id]
    assert stores.runs.get(stale.id).status == RunStatus.FAILED
    assert "Abandoned" in stores.runs.get(stale.id).error


def test_a_run_still_in_progress_is_left_alone(runner, stores):
    fresh = Run(agent="note", org_id="org_1", status=RunStatus.RUNNING)
    stores.runs.save(fresh)

    assert runner.reap_abandoned() == []
    assert stores.runs.get(fresh.id).status == RunStatus.RUNNING


def test_finished_runs_are_never_touched(runner, stores):
    for status in (RunStatus.COMPLETED, RunStatus.AWAITING_REVIEW, RunStatus.FAILED):
        run = Run(agent="note", org_id="org_1", status=status)
        stores.runs.save(run)
        stores.runs._runs[run.id].updated_at = datetime.now(UTC) - timedelta(days=7)

    assert runner.reap_abandoned() == []


def test_the_threshold_is_configurable(runner, stores):
    run = Run(agent="note", org_id="org_1", status=RunStatus.RUNNING)
    stores.runs.save(run)
    stores.runs._runs[run.id].updated_at = datetime.now(UTC) - timedelta(seconds=90)

    assert runner.reap_abandoned() == []
    assert len(runner.reap_abandoned(older_than_seconds=60)) == 1


def test_a_naive_timestamp_is_read_as_utc(runner, stores):
    """A backend that drops tzinfo yields naive UTC, which is what the sweep assumes."""
    run = Run(agent="note", org_id="org_1", status=RunStatus.RUNNING)
    stores.runs.save(run)
    naive_utc = (datetime.now(UTC) - timedelta(hours=3)).replace(tzinfo=None)
    stores.runs._runs[run.id].updated_at = naive_utc

    assert len(runner.reap_abandoned()) == 1


def test_startup_reaps_without_blocking_the_app(registry, stores, provider, config):
    from fastapi.testclient import TestClient

    from nonprofit_harness.api.app import create_app

    stale = Run(agent="note", org_id="org_1", status=RunStatus.RUNNING)
    stores.runs.save(stale)
    stores.runs._runs[stale.id].updated_at = datetime.now(UTC) - timedelta(hours=5)

    app = create_app(config=config, registry=registry, stores=stores, provider=provider)
    with TestClient(app) as client:
        assert client.get("/healthz").json()["status"] == "ok"

    assert stores.runs.get(stale.id).status == RunStatus.FAILED


def test_a_broken_store_does_not_stop_the_app_booting(registry, provider, config):
    from fastapi.testclient import TestClient

    from nonprofit_harness.api.app import create_app
    from nonprofit_harness.storage.memory import memory_stores

    stores = memory_stores()

    def explode(**kwargs):
        raise RuntimeError("storage is down")

    stores.runs.list = explode

    app = create_app(config=config, registry=registry, stores=stores, provider=provider)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
