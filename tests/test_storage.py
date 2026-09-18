from __future__ import annotations

import pytest

from nonprofit_harness.core.errors import NotFound
from nonprofit_harness.core.types import Artifact, ArtifactStatus, Document, Run, RunStatus, Usage
from nonprofit_harness.storage.memory import memory_stores
from nonprofit_harness.storage.serde import run_from_dict, run_to_dict


def test_a_run_survives_a_serialisation_round_trip():
    run = Run(agent="note", org_id="org_1", status=RunStatus.AWAITING_REVIEW)
    run.inputs = [Document(text="body", name="a.txt")]
    run.artifacts = [
        Artifact(kind="note", content="text", title="T", status=ArtifactStatus.PENDING_REVIEW)
    ]
    run.usage = Usage(input_tokens=10, output_tokens=5, cost_usd=0.01, calls=1)

    restored = run_from_dict(run_to_dict(run))

    assert restored.id == run.id
    assert restored.status == RunStatus.AWAITING_REVIEW
    assert restored.artifacts[0].status == ArtifactStatus.PENDING_REVIEW
    assert restored.usage.cost_usd == 0.01
    assert restored.inputs[0].name == "a.txt"


def test_the_memory_store_hands_back_copies_not_references():
    stores = memory_stores()
    run = stores.runs.save(Run(agent="note", org_id="org_1"))

    fetched = stores.runs.get(run.id)
    fetched.summary = "mutated outside the store"

    assert stores.runs.get(run.id).summary == ""


def test_listing_filters_by_org_and_status():
    stores = memory_stores()
    stores.runs.save(Run(agent="note", org_id="org_1", status=RunStatus.COMPLETED))
    stores.runs.save(Run(agent="note", org_id="org_1", status=RunStatus.FAILED))
    stores.runs.save(Run(agent="note", org_id="org_2", status=RunStatus.COMPLETED))

    assert len(stores.runs.list(org_id="org_1")) == 2
    assert len(stores.runs.list(org_id="org_1", status=RunStatus.FAILED)) == 1
    assert len(stores.runs.list(status=RunStatus.COMPLETED)) == 2


def test_a_missing_run_raises_not_found():
    with pytest.raises(NotFound):
        memory_stores().runs.get("run_nope")


def test_blobs_round_trip_with_metadata():
    stores = memory_stores()
    blob = stores.blobs.put(org_id="org_1", name="a.txt", data=b"hello", media_type="text/plain")

    assert stores.blobs.get(blob.id) == b"hello"
    assert stores.blobs.meta(blob.id).size == 5
    assert [b.id for b in stores.blobs.list(org_id="org_1")] == [blob.id]
    assert stores.blobs.list(org_id="org_2") == []


def test_users_are_found_by_email_case_insensitively():
    from nonprofit_harness.storage.base import User

    stores = memory_stores()
    stores.users.save(User(email="Asha@Example.org", org_id="org_1"))

    assert stores.users.get_by_email("asha@example.org") is not None
    assert stores.users.get_by_email("someone@else.org") is None
