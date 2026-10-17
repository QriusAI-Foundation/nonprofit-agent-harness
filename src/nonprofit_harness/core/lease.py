"""Execution ownership: which worker is running a run, and until when it vouches for it.

A run in `running` looks the same whether its process is busy or dead. The lease is
how a live process says "still mine": it renews an expiry time in the run's metadata,
and the reaper resolves a run only once that time has passed. A dead process cannot
renew, so its runs come due; a live one on another instance never does.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from nonprofit_harness.core.types import Run, RunStatus
from nonprofit_harness.storage.base import RunStore

logger = logging.getLogger("nonprofit_harness.lease")

#: Metadata key the runner owns. An agent's own metadata never overwrites it.
EXECUTION = "execution"

GENERATING = "generating"
#: The agent has returned and its work is stored. A run that strands here has
#: something worth reviewing, so recovery sends it to a person instead of failing it.
VERIFYING = "verifying"


def new_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


def claim(run: Run, *, worker: str, lease_seconds: int) -> None:
    now = datetime.now(UTC)
    run.metadata[EXECUTION] = {
        "worker": worker,
        "started_at": now.isoformat(),
        "lease_expires_at": (now + timedelta(seconds=lease_seconds)).isoformat(),
        "phase": GENERATING,
    }


def extend(run: Run, *, worker: str, lease_seconds: int, phase: str | None = None) -> None:
    execution = run.metadata.setdefault(EXECUTION, {})
    execution["worker"] = worker
    execution["lease_expires_at"] = (
        datetime.now(UTC) + timedelta(seconds=lease_seconds)
    ).isoformat()
    if phase is not None:
        execution["phase"] = phase


def expires_at(run: Run) -> datetime | None:
    raw = run.metadata.get(EXECUTION, {}).get("lease_expires_at")
    if not raw:
        return None
    expiry = datetime.fromisoformat(raw)
    return expiry if expiry.tzinfo else expiry.replace(tzinfo=UTC)


def holder(run: Run) -> str:
    return run.metadata.get(EXECUTION, {}).get("worker", "unknown")


def phase(run: Run) -> str:
    return run.metadata.get(EXECUTION, {}).get("phase", GENERATING)


class Heartbeat:
    """Renews one run's lease from a background thread while the agent works.

    A thread rather than a hook on model calls: one model call can outlast a lease,
    and an agent doing slow work between calls is still alive.

    Renewal stops after `max_seconds`. A run that has not finished by then is treated
    as hung: its lease lapses and the reaper fails it, which is what
    HARNESS_RUN_TIMEOUT_SECONDS has always promised. If it does finish later, the
    runner still keeps its work (see `AgentRunner._land`).
    """

    def __init__(
        self, runs: RunStore, run_id: str, *, worker: str, lease_seconds: int, max_seconds: int
    ) -> None:
        self._runs = runs
        self._run_id = run_id
        self._worker = worker
        self._lease_seconds = lease_seconds
        self._max_seconds = max_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, name=f"lease-{run_id}", daemon=True)

    def __enter__(self) -> Heartbeat:
        self._thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self._stop.set()
        self._thread.join()

    def _beat(self) -> None:
        deadline = time.monotonic() + self._max_seconds
        # A third of the lease leaves two missed renewals of slack before it lapses.
        while not self._stop.wait(self._lease_seconds / 3):
            if time.monotonic() >= deadline:
                logger.warning(
                    "Run %s passed %ss; no longer renewing its lease, so it will be reaped",
                    self._run_id,
                    self._max_seconds,
                )
                return
            try:
                self._runs.update(self._run_id, self._renew)
            except Exception:  # noqa: BLE001 - the next beat retries; the lease has slack
                logger.exception("Could not renew the lease on run %s", self._run_id)

    def _renew(self, run: Run) -> bool:
        # Never revive a run the reaper or a person has already moved on.
        if run.status != RunStatus.RUNNING or holder(run) != self._worker:
            return False
        extend(run, worker=self._worker, lease_seconds=self._lease_seconds)
        return True


__all__ = [
    "EXECUTION",
    "GENERATING",
    "VERIFYING",
    "Heartbeat",
    "claim",
    "expires_at",
    "extend",
    "holder",
    "new_worker_id",
    "phase",
]
