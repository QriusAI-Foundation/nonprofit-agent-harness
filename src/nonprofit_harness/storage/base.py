from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from nonprofit_harness.core.types import Run, RunStatus


@dataclass(frozen=True, slots=True)
class StoredBlob:
    id: str
    name: str
    media_type: str
    size: int
    uri: str
    org_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class Org:
    name: str
    id: str = field(default_factory=lambda: f"org_{uuid.uuid4().hex[:12]}")
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class User:
    email: str
    org_id: str
    id: str = field(default_factory=lambda: f"usr_{uuid.uuid4().hex[:12]}")
    name: str = ""
    is_admin: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class RunStore(Protocol):
    def save(self, run: Run) -> Run: ...
    def get(self, run_id: str) -> Run: ...
    def list(
        self, *, org_id: str | None = None, status: RunStatus | None = None, limit: int = 50
    ) -> list[Run]: ...


@runtime_checkable
class BlobStore(Protocol):
    def put(
        self, *, org_id: str, name: str, data: bytes, media_type: str = "application/octet-stream"
    ) -> StoredBlob: ...
    def get(self, blob_id: str) -> bytes: ...
    def meta(self, blob_id: str) -> StoredBlob: ...
    def list(self, *, org_id: str, limit: int = 100) -> list[StoredBlob]: ...


@runtime_checkable
class OrgStore(Protocol):
    def save(self, org: Org) -> Org: ...
    def get(self, org_id: str) -> Org: ...
    def list(self, *, limit: int = 100) -> list[Org]: ...


@runtime_checkable
class UserStore(Protocol):
    def save(self, user: User) -> User: ...
    def get_by_email(self, email: str) -> User | None: ...
    def get(self, user_id: str) -> User: ...


@runtime_checkable
class SettingsStore(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...
    def all(self) -> dict[str, Any]: ...


@dataclass(slots=True)
class Stores:
    """The full storage surface, passed around as one object."""

    runs: RunStore
    blobs: BlobStore
    orgs: OrgStore
    users: UserStore
    settings: SettingsStore


__all__ = [
    "BlobStore",
    "Org",
    "OrgStore",
    "RunStore",
    "SettingsStore",
    "StoredBlob",
    "Stores",
    "User",
    "UserStore",
]
