from __future__ import annotations

import copy

import pytest

from nonprofit_harness.core.errors import NotFound, StaleRun
from nonprofit_harness.core.types import Artifact, ArtifactStatus, Document, Run, RunStatus, Usage
from nonprofit_harness.storage.gcp import FirestoreRunStore
from nonprofit_harness.storage.memory import MemoryRunStore, memory_stores
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


def test_listing_pages_with_a_cursor_that_survives_a_status_change():
    """The reaper moves runs out of `running` while it pages through them."""
    stores = memory_stores()
    for _ in range(5):
        stores.runs.save(Run(agent="note", org_id="org_1", status=RunStatus.RUNNING))

    first = stores.runs.list(status=RunStatus.RUNNING, limit=2)
    for run in first:
        stores.runs.update(run.id, lambda r: setattr(r, "status", RunStatus.FAILED) or True)
    rest = stores.runs.list(status=RunStatus.RUNNING, limit=10, after=first[-1].id)

    assert len(rest) == 3
    assert {r.id for r in first}.isdisjoint(r.id for r in rest)


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


# --- versioned writes (audit F06) -----------------------------------------------------


def test_every_write_bumps_the_version():
    runs = MemoryRunStore()
    run = runs.save(Run(agent="note", org_id="org_1"))
    assert run.version == 1

    run.summary = "changed"
    runs.save(run)

    assert runs.get(run.id).version == 2


def test_a_stale_copy_cannot_overwrite_a_newer_save():
    runs = MemoryRunStore()
    run = runs.save(Run(agent="note", org_id="org_1"))
    first, second = runs.get(run.id), runs.get(run.id)
    first.summary = "first writer"
    runs.save(first)

    second.summary = "second writer"
    with pytest.raises(StaleRun) as raised:
        runs.save(second)

    assert raised.value.status_code == 409
    assert runs.get(run.id).summary == "first writer"


def test_an_update_that_changes_nothing_writes_nothing():
    runs = MemoryRunStore()
    run = runs.save(Run(agent="note", org_id="org_1"))

    runs.update(run.id, lambda r: False)

    assert runs.get(run.id).version == run.version


def test_an_update_that_raises_writes_nothing():
    runs = MemoryRunStore()
    run = runs.save(Run(agent="note", org_id="org_1"))

    def change(r):
        r.summary = "half done"
        raise ValueError("refused")

    with pytest.raises(ValueError):
        runs.update(run.id, change)

    assert runs.get(run.id).summary == ""


def test_the_version_survives_serialisation_and_old_records_start_at_zero():
    run = Run(agent="note", org_id="org_1", version=7)
    data = run_to_dict(run)

    assert run_from_dict(data).version == 7
    del data["version"]
    assert run_from_dict(data).version == 0


# A stand-in for Firestore. It shows the store's own logic (version check, commit only
# on success, NotFound) but not Firestore's real contention handling, which needs a
# live Firestore or its emulator.


class _Snapshot:
    def __init__(self, data):
        self.exists = data is not None
        self._data = data

    def to_dict(self):
        return copy.deepcopy(self._data)


class _Ref:
    def __init__(self, docs, doc_id):
        self._docs, self.id = docs, doc_id

    def get(self, transaction=None):
        return _Snapshot(self._docs.get(self.id))


class _Transaction:
    def __init__(self, docs):
        self.docs, self.writes = docs, []

    def set(self, ref, data):
        self.writes.append((ref.id, copy.deepcopy(data)))


class _Query:
    """Enough of a Firestore query to check how `list` pages, not Firestore itself."""

    def __init__(self, docs):
        self._docs, self._filters, self._after, self._limit = docs, [], None, None

    def where(self, field, _op, value):
        self._filters.append((field, value))
        return self

    def order_by(self, field, direction):
        assert (field, direction) == ("created_at", "DESCENDING")
        return self

    def start_after(self, snapshot):
        data = snapshot.to_dict()
        self._after = (data["created_at"], data["id"])
        return self

    def limit(self, count):
        self._limit = count
        return self

    def stream(self):
        found = [
            d
            for d in self._docs.values()
            if all(d.get(f) == v for f, v in self._filters)
            and (self._after is None or (d["created_at"], d["id"]) < self._after)
        ]
        found.sort(key=lambda d: (d["created_at"], d["id"]), reverse=True)
        return [_Snapshot(d) for d in found[: self._limit]]


class _Client:
    def __init__(self):
        self.docs = {}

    def collection(self, _name):
        return self

    def where(self, *args):
        return _Query(self.docs).where(*args)

    def order_by(self, *args, **kwargs):
        return _Query(self.docs).order_by(*args, **kwargs)

    def document(self, doc_id):
        return _Ref(self.docs, doc_id)

    def transaction(self):
        return _Transaction(self.docs)


def _transactional(attempt):
    def run(transaction):
        result = attempt(transaction)
        for doc_id, data in transaction.writes:
            transaction.docs[doc_id] = data
        return result

    return run


@pytest.fixture
def firestore_runs():
    return FirestoreRunStore(_Client(), transactional=_transactional)


def test_firestore_refuses_a_stale_save_and_keeps_the_newer_one(firestore_runs):
    run = firestore_runs.save(Run(agent="note", org_id="org_1"))
    first, second = firestore_runs.get(run.id), firestore_runs.get(run.id)
    first.summary = "first writer"
    firestore_runs.save(first)

    second.summary = "second writer"
    with pytest.raises(StaleRun):
        firestore_runs.save(second)

    assert firestore_runs.get(run.id).summary == "first writer"
    assert firestore_runs.get(run.id).version == 2


def test_firestore_update_applies_the_change_and_bumps_the_version(firestore_runs):
    run = firestore_runs.save(Run(agent="note", org_id="org_1"))

    def change(r):
        r.summary = "decided"
        return True

    updated = firestore_runs.update(run.id, change)

    assert updated.version == 2
    assert firestore_runs.get(run.id).summary == "decided"
    with pytest.raises(NotFound):
        firestore_runs.update("run_missing", change)


def test_firestore_listing_resumes_after_the_cursor_run(firestore_runs):
    for _ in range(5):
        firestore_runs.save(Run(agent="note", org_id="org_1", status=RunStatus.RUNNING))

    first = firestore_runs.list(status=RunStatus.RUNNING, limit=2)
    rest = firestore_runs.list(status=RunStatus.RUNNING, limit=10, after=first[-1].id)

    assert len(first) == 2
    assert len(rest) == 3
    assert {r.id for r in first}.isdisjoint(r.id for r in rest)
    with pytest.raises(NotFound):
        firestore_runs.list(status=RunStatus.RUNNING, after="run_missing")
