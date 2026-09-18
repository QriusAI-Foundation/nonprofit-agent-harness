from __future__ import annotations

import os

from nonprofit_harness.storage.base import (
    BlobStore,
    Org,
    OrgStore,
    RunStore,
    SettingsStore,
    StoredBlob,
    Stores,
    User,
    UserStore,
)
from nonprofit_harness.storage.memory import memory_stores

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
    "load_stores",
    "memory_stores",
]


def load_stores(backend: str | None = None, **kwargs) -> Stores:
    """Build the storage surface. Defaults to memory so a fresh clone runs with no cloud."""
    chosen = (backend or os.getenv("HARNESS_STORAGE") or "memory").lower()
    if chosen == "memory":
        return memory_stores()
    if chosen in {"gcp", "firestore", "google"}:
        from nonprofit_harness.storage.gcp import gcp_stores

        return gcp_stores(**kwargs)

    from nonprofit_harness.core.errors import InvalidRequest

    raise InvalidRequest(f"Unknown storage backend {chosen!r}. Known: memory, gcp")
