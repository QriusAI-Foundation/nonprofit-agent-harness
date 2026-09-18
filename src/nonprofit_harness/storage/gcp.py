from __future__ import annotations

import uuid
from typing import Any

from nonprofit_harness.core.errors import NotFound
from nonprofit_harness.core.types import Run, RunStatus
from nonprofit_harness.storage.base import Org, StoredBlob, Stores, User
from nonprofit_harness.storage.serde import run_from_dict, run_to_dict

RUNS = "harness_runs"
ORGS = "harness_orgs"
USERS = "harness_users"
SETTINGS = "harness_settings"
SETTINGS_DOC = "singleton"


class FirestoreRunStore:
    def __init__(self, client: Any, collection: str = RUNS) -> None:
        self._client = client
        self._collection = collection

    def save(self, run: Run) -> Run:
        run.touch()
        self._client.collection(self._collection).document(run.id).set(run_to_dict(run))
        return run

    def get(self, run_id: str) -> Run:
        snapshot = self._client.collection(self._collection).document(run_id).get()
        if not snapshot.exists:
            raise NotFound(f"No run {run_id!r}")
        return run_from_dict(snapshot.to_dict())

    def list(
        self, *, org_id: str | None = None, status: RunStatus | None = None, limit: int = 50
    ) -> list[Run]:
        query = self._client.collection(self._collection)
        if org_id:
            query = query.where("org_id", "==", org_id)
        if status:
            query = query.where("status", "==", str(status))
        query = query.order_by("created_at", direction="DESCENDING").limit(limit)
        return [run_from_dict(doc.to_dict()) for doc in query.stream()]


class GcsBlobStore:
    def __init__(self, client: Any, bucket: str, firestore_client: Any = None) -> None:
        self._client = client
        self._bucket_name = bucket
        self._bucket = client.bucket(bucket)
        self._firestore = firestore_client

    def put(
        self, *, org_id: str, name: str, data: bytes, media_type: str = "application/octet-stream"
    ) -> StoredBlob:
        blob_id = f"blob_{uuid.uuid4().hex[:16]}"
        path = f"{org_id}/{blob_id}/{name}"
        blob = self._bucket.blob(path)
        blob.upload_from_string(data, content_type=media_type)
        meta = StoredBlob(
            id=blob_id,
            name=name,
            media_type=media_type,
            size=len(data),
            uri=f"gs://{self._bucket_name}/{path}",
            org_id=org_id,
        )
        if self._firestore is not None:
            self._firestore.collection("harness_blobs").document(blob_id).set(
                {
                    "id": meta.id,
                    "name": meta.name,
                    "media_type": meta.media_type,
                    "size": meta.size,
                    "uri": meta.uri,
                    "org_id": meta.org_id,
                    "path": path,
                    "created_at": meta.created_at,
                }
            )
        return meta

    def _record(self, blob_id: str) -> dict[str, Any]:
        if self._firestore is None:
            raise NotFound("Blob lookup needs a Firestore client for metadata")
        snapshot = self._firestore.collection("harness_blobs").document(blob_id).get()
        if not snapshot.exists:
            raise NotFound(f"No blob {blob_id!r}")
        return snapshot.to_dict()

    def get(self, blob_id: str) -> bytes:
        return self._bucket.blob(self._record(blob_id)["path"]).download_as_bytes()

    def meta(self, blob_id: str) -> StoredBlob:
        record = self._record(blob_id)
        return StoredBlob(
            id=record["id"],
            name=record["name"],
            media_type=record["media_type"],
            size=record["size"],
            uri=record["uri"],
            org_id=record["org_id"],
            created_at=record["created_at"],
        )

    def list(self, *, org_id: str, limit: int = 100) -> list[StoredBlob]:
        if self._firestore is None:
            return []
        query = (
            self._firestore.collection("harness_blobs")
            .where("org_id", "==", org_id)
            .order_by("created_at", direction="DESCENDING")
            .limit(limit)
        )
        return [
            StoredBlob(
                id=d["id"],
                name=d["name"],
                media_type=d["media_type"],
                size=d["size"],
                uri=d["uri"],
                org_id=d["org_id"],
                created_at=d["created_at"],
            )
            for d in (doc.to_dict() for doc in query.stream())
        ]


class FirestoreOrgStore:
    def __init__(self, client: Any) -> None:
        self._client = client

    def save(self, org: Org) -> Org:
        self._client.collection(ORGS).document(org.id).set(
            {
                "id": org.id,
                "name": org.name,
                "metadata": org.metadata,
                "created_at": org.created_at,
            }
        )
        return org

    def get(self, org_id: str) -> Org:
        snapshot = self._client.collection(ORGS).document(org_id).get()
        if not snapshot.exists:
            raise NotFound(f"No org {org_id!r}")
        data = snapshot.to_dict()
        return Org(
            name=data["name"],
            id=data["id"],
            metadata=data.get("metadata", {}) or {},
            created_at=data["created_at"],
        )

    def list(self, *, limit: int = 100) -> list[Org]:
        docs = self._client.collection(ORGS).limit(limit).stream()
        return [
            Org(
                name=d["name"],
                id=d["id"],
                metadata=d.get("metadata", {}) or {},
                created_at=d["created_at"],
            )
            for d in (doc.to_dict() for doc in docs)
        ]


class FirestoreUserStore:
    def __init__(self, client: Any) -> None:
        self._client = client

    def save(self, user: User) -> User:
        self._client.collection(USERS).document(user.id).set(
            {
                "id": user.id,
                "email": user.email.lower(),
                "name": user.name,
                "org_id": user.org_id,
                "is_admin": user.is_admin,
                "metadata": user.metadata,
                "created_at": user.created_at,
            }
        )
        return user

    def _hydrate(self, data: dict[str, Any]) -> User:
        return User(
            email=data["email"],
            org_id=data["org_id"],
            id=data["id"],
            name=data.get("name", ""),
            is_admin=data.get("is_admin", False),
            metadata=data.get("metadata", {}) or {},
            created_at=data["created_at"],
        )

    def get(self, user_id: str) -> User:
        snapshot = self._client.collection(USERS).document(user_id).get()
        if not snapshot.exists:
            raise NotFound(f"No user {user_id!r}")
        return self._hydrate(snapshot.to_dict())

    def get_by_email(self, email: str) -> User | None:
        docs = list(
            self._client.collection(USERS).where("email", "==", email.lower()).limit(1).stream()
        )
        return self._hydrate(docs[0].to_dict()) if docs else None


class FirestoreSettingsStore:
    def __init__(self, client: Any) -> None:
        self._client = client

    def _doc(self):
        return self._client.collection(SETTINGS).document(SETTINGS_DOC)

    def all(self) -> dict[str, Any]:
        snapshot = self._doc().get()
        return snapshot.to_dict() if snapshot.exists else {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.all().get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._doc().set({key: value}, merge=True)


def gcp_stores(*, project: str | None = None, bucket: str | None = None) -> Stores:
    """Build the production storage surface. Needs the `gcp` extra."""
    try:
        from google.cloud import firestore, storage
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "GCP storage needs the `gcp` extra: pip install 'nonprofit-agent-harness[gcp]'"
        ) from exc

    import os

    project = project or os.getenv("GOOGLE_CLOUD_PROJECT")
    bucket = bucket or os.getenv("HARNESS_DOCUMENTS_BUCKET")
    if not bucket:
        raise RuntimeError("Set HARNESS_DOCUMENTS_BUCKET to use GCP storage")

    firestore_client = firestore.Client(project=project)
    storage_client = storage.Client(project=project)
    return Stores(
        runs=FirestoreRunStore(firestore_client),
        blobs=GcsBlobStore(storage_client, bucket, firestore_client=firestore_client),
        orgs=FirestoreOrgStore(firestore_client),
        users=FirestoreUserStore(firestore_client),
        settings=FirestoreSettingsStore(firestore_client),
    )


__all__ = [
    "FirestoreOrgStore",
    "FirestoreRunStore",
    "FirestoreSettingsStore",
    "FirestoreUserStore",
    "GcsBlobStore",
    "gcp_stores",
]
