from __future__ import annotations

import copy
import threading
import uuid
from typing import Any

from nonprofit_harness.core.errors import NotFound, StaleRun
from nonprofit_harness.core.types import Run, RunStatus
from nonprofit_harness.storage.base import Org, RunChange, StoredBlob, Stores, User


class MemoryRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        # The API serves requests from a thread pool, so two reviews of one run can
        # really interleave here. One lock is enough for a store that lives in one
        # process and holds nothing slow.
        self._lock = threading.Lock()

    def save(self, run: Run) -> Run:
        with self._lock:
            stored = self._runs.get(run.id)
            found = stored.version if stored is not None else 0
            if run.version != found:
                raise StaleRun(run.id, run.version, found)
            self._write(run)
        return run

    def get(self, run_id: str) -> Run:
        with self._lock:
            return copy.deepcopy(self._stored(run_id))

    def update(self, run_id: str, change: RunChange) -> Run:
        with self._lock:
            run = copy.deepcopy(self._stored(run_id))
            if change(run) is not False:
                self._write(run)
            return run

    def _stored(self, run_id: str) -> Run:
        try:
            return self._runs[run_id]
        except KeyError:
            raise NotFound(f"No run {run_id!r}") from None

    def _write(self, run: Run) -> None:
        run.version += 1
        run.touch()
        self._runs[run.id] = copy.deepcopy(run)

    def list(
        self,
        *,
        org_id: str | None = None,
        status: RunStatus | None = None,
        limit: int = 50,
        after: str | None = None,
    ) -> list[Run]:
        with self._lock:
            cursor = _position(self._stored(after)) if after else None
            found = [
                copy.deepcopy(r)
                for r in self._runs.values()
                if (org_id is None or r.org_id == org_id)
                and (status is None or r.status == status)
                and (cursor is None or _position(r) < cursor)
            ]
        found.sort(key=_position, reverse=True)
        return found[:limit]


def _position(run: Run) -> tuple:
    # The id breaks ties, as Firestore's document name does, so two runs created in
    # the same microsecond cannot both sit on a page boundary and one be skipped.
    return (run.created_at, run.id)


class MemoryBlobStore:
    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self._meta: dict[str, StoredBlob] = {}

    def put(
        self, *, org_id: str, name: str, data: bytes, media_type: str = "application/octet-stream"
    ) -> StoredBlob:
        blob_id = f"blob_{uuid.uuid4().hex[:16]}"
        meta = StoredBlob(
            id=blob_id,
            name=name,
            media_type=media_type,
            size=len(data),
            uri=f"memory://{org_id}/{blob_id}",
            org_id=org_id,
        )
        self._data[blob_id] = data
        self._meta[blob_id] = meta
        return meta

    def get(self, blob_id: str) -> bytes:
        try:
            return self._data[blob_id]
        except KeyError:
            raise NotFound(f"No blob {blob_id!r}") from None

    def meta(self, blob_id: str) -> StoredBlob:
        try:
            return self._meta[blob_id]
        except KeyError:
            raise NotFound(f"No blob {blob_id!r}") from None

    def list(self, *, org_id: str, limit: int = 100) -> list[StoredBlob]:
        found = [m for m in self._meta.values() if m.org_id == org_id]
        found.sort(key=lambda m: m.created_at, reverse=True)
        return found[:limit]


class MemoryOrgStore:
    def __init__(self) -> None:
        self._orgs: dict[str, Org] = {}

    def save(self, org: Org) -> Org:
        self._orgs[org.id] = org
        return org

    def get(self, org_id: str) -> Org:
        try:
            return self._orgs[org_id]
        except KeyError:
            raise NotFound(f"No org {org_id!r}") from None

    def list(self, *, limit: int = 100) -> list[Org]:
        return list(self._orgs.values())[:limit]


class MemoryUserStore:
    def __init__(self) -> None:
        self._users: dict[str, User] = {}

    def save(self, user: User) -> User:
        self._users[user.id] = user
        return user

    def get(self, user_id: str) -> User:
        try:
            return self._users[user_id]
        except KeyError:
            raise NotFound(f"No user {user_id!r}") from None

    def get_by_email(self, email: str) -> User | None:
        return next((u for u in self._users.values() if u.email.lower() == email.lower()), None)


class MemorySettingsStore:
    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._values: dict[str, Any] = dict(initial or {})

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._values[key] = value

    def all(self) -> dict[str, Any]:
        return dict(self._values)


def memory_stores() -> Stores:
    return Stores(
        runs=MemoryRunStore(),
        blobs=MemoryBlobStore(),
        orgs=MemoryOrgStore(),
        users=MemoryUserStore(),
        settings=MemorySettingsStore(),
    )


__all__ = [
    "MemoryBlobStore",
    "MemoryOrgStore",
    "MemoryRunStore",
    "MemorySettingsStore",
    "MemoryUserStore",
    "memory_stores",
]
