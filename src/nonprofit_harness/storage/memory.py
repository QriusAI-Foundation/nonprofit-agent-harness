from __future__ import annotations

import copy
import uuid
from typing import Any

from nonprofit_harness.core.errors import NotFound
from nonprofit_harness.core.types import Run, RunStatus
from nonprofit_harness.storage.base import Org, StoredBlob, Stores, User


class MemoryRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def save(self, run: Run) -> Run:
        run.touch()
        self._runs[run.id] = copy.deepcopy(run)
        return run

    def get(self, run_id: str) -> Run:
        try:
            return copy.deepcopy(self._runs[run_id])
        except KeyError:
            raise NotFound(f"No run {run_id!r}") from None

    def list(
        self, *, org_id: str | None = None, status: RunStatus | None = None, limit: int = 50
    ) -> list[Run]:
        found = [
            copy.deepcopy(r)
            for r in self._runs.values()
            if (org_id is None or r.org_id == org_id) and (status is None or r.status == status)
        ]
        found.sort(key=lambda r: r.created_at, reverse=True)
        return found[:limit]


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
