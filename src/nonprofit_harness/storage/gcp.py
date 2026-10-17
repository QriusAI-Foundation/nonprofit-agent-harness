from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from nonprofit_harness.core.errors import NotFound, StaleRun, StorageError
from nonprofit_harness.core.types import Run, RunStatus
from nonprofit_harness.storage.base import Org, RunChange, StoredBlob, Stores, User
from nonprofit_harness.storage.serde import run_from_dict, run_to_dict

RUNS = "harness_runs"
ORGS = "harness_orgs"
USERS = "harness_users"
SETTINGS = "harness_settings"
SETTINGS_DOC = "singleton"


class FirestoreRunStore:
    """Runs as Firestore documents, each write inside a transaction.

    Several Cloud Run instances can serve reviews of the same run at once, so a
    plain read-then-set lets the later writer erase the earlier one's decision. A
    transaction makes Firestore abort and retry the later one against fresh data.

    `transactional` is google.cloud.firestore.transactional unless a test passes a
    stand-in; it is imported late so the module loads without the `gcp` extra.
    """

    def __init__(
        self,
        client: Any,
        collection: str = RUNS,
        *,
        transactional: Callable[[Callable[..., Run]], Callable[..., Run]] | None = None,
    ) -> None:
        self._client = client
        self._collection = collection
        self._transactional = transactional

    def save(self, run: Run) -> Run:
        ref = self._ref(run.id)

        def attempt(transaction: Any) -> Run:
            snapshot = ref.get(transaction=transaction)
            found = (snapshot.to_dict().get("version", 0) or 0) if snapshot.exists else 0
            if run.version != found:
                raise StaleRun(run.id, run.version, found)
            return self._write(transaction, ref, run)

        written = self._in_transaction(attempt)
        # Only after the commit: a retried attempt must see the version it was read at.
        run.version = written.version
        run.updated_at = written.updated_at
        return run

    def get(self, run_id: str) -> Run:
        snapshot = self._ref(run_id).get()
        if not snapshot.exists:
            raise NotFound(f"No run {run_id!r}")
        return run_from_dict(snapshot.to_dict())

    def update(self, run_id: str, change: RunChange) -> Run:
        ref = self._ref(run_id)

        def attempt(transaction: Any) -> Run:
            snapshot = ref.get(transaction=transaction)
            if not snapshot.exists:
                raise NotFound(f"No run {run_id!r}")
            run = run_from_dict(snapshot.to_dict())
            if change(run) is False:
                return run
            return self._write(transaction, ref, run)

        return self._in_transaction(attempt)

    def _ref(self, run_id: str) -> Any:
        return self._client.collection(self._collection).document(run_id)

    @staticmethod
    def _write(transaction: Any, ref: Any, run: Run) -> Run:
        written = run_from_dict(run_to_dict(run))
        written.version = run.version + 1
        written.touch()
        transaction.set(ref, run_to_dict(written))
        return written

    def _in_transaction(self, attempt: Callable[[Any], Run]) -> Run:
        transactional = self._transactional
        if transactional is None:  # pragma: no cover - needs the `gcp` extra
            from google.cloud.firestore import transactional
        return transactional(attempt)(self._client.transaction())

    def list(
        self,
        *,
        org_id: str | None = None,
        status: RunStatus | None = None,
        limit: int = 50,
        after: str | None = None,
    ) -> list[Run]:
        query = self._client.collection(self._collection)
        if org_id:
            query = query.where("org_id", "==", org_id)
        if status:
            query = query.where("status", "==", str(status))
        query = query.order_by("created_at", direction="DESCENDING")
        if after:
            # A snapshot cursor resumes at that document's created_at and name, even
            # when the document no longer matches the status filter.
            cursor = self._ref(after).get()
            if not cursor.exists:
                raise NotFound(f"No run {after!r}")
            query = query.start_after(cursor)
        query = query.limit(limit)

        try:
            return [run_from_dict(doc.to_dict()) for doc in query.stream()]
        except Exception as exc:  # noqa: BLE001 - narrowed immediately below
            raise _index_hint(exc) from exc


def _index_hint(exc: Exception) -> Exception:
    """Turn Firestore's missing-index error into something actionable.

    Filtering on a field and ordering by a different one needs a composite index, which
    Firestore does not create on its own. The in-memory backend has no such rule, so
    this surfaces on a real deployment and never in a test. Firestore's own message
    carries a link that creates the index, so the useful thing is to keep that message
    rather than replace it.
    """
    detail = str(exc)
    if "FAILED_PRECONDITION" not in detail and "requires an index" not in detail:
        return exc
    return StorageError(
        "Firestore needs a composite index for this query. Either open the link in the "
        "message below, or apply the index definitions in deployment/terraform. "
        f"Original error: {detail}"
    )


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
