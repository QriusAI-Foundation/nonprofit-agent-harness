from __future__ import annotations

from nonprofit_harness.core.errors import InvalidRequest, NotFound, ReviewRequired
from nonprofit_harness.core.types import (
    Artifact,
    ArtifactStatus,
    Review,
    ReviewDecision,
    Run,
    RunStatus,
)
from nonprofit_harness.storage.base import RunStore

AUTO_REVIEWER = "system:auto-release"


class ReviewGate:
    """Holds agent output until a person signs it off.

    The sector reason: an unreviewed model output here can reach a beneficiary, a
    funder report, or a training room. The engineering consequence is that
    "released" is a state a human puts an artifact into, never a default.

    Every decision is recorded, including automatic ones, so an audit can always
    answer who released a given artifact.
    """

    def __init__(self, runs: RunStore) -> None:
        self._runs = runs

    def submit(self, run: Run) -> Run:
        for artifact in run.artifacts:
            if artifact.status == ArtifactStatus.DRAFT:
                artifact.status = ArtifactStatus.PENDING_REVIEW
        run.status = (
            RunStatus.AWAITING_REVIEW if run.pending_review else self._settle_status(run)
        )
        return self._runs.save(run)

    def auto_release(self, run: Run, *, reason: str = "agent opted out of review") -> Run:
        """Release without a reviewer, except where the harness found a problem.

        An artifact whose claims failed verification is sent to a person even when
        the agent opted out. Opting out of review is a statement that the output is
        routine; a citation that does not resolve is evidence that it is not. The
        rule lives here rather than in the runner so no caller can route around it.
        """
        for artifact in run.artifacts:
            if artifact.status not in (ArtifactStatus.DRAFT, ArtifactStatus.PENDING_REVIEW):
                continue
            if artifact.failed_verification:
                artifact.status = ArtifactStatus.PENDING_REVIEW
                continue
            artifact.status = ArtifactStatus.APPROVED
            artifact.review = Review(
                decision=ReviewDecision.APPROVE, reviewer=AUTO_REVIEWER, note=reason
            )
        run.status = self._settle_status(run)
        return self._runs.save(run)

    def approve(self, run_id: str, artifact_id: str, *, reviewer: str, note: str = "") -> Run:
        return self._decide(run_id, artifact_id, ReviewDecision.APPROVE, reviewer, note)

    def reject(self, run_id: str, artifact_id: str, *, reviewer: str, note: str = "") -> Run:
        return self._decide(run_id, artifact_id, ReviewDecision.REJECT, reviewer, note)

    def approve_all(self, run_id: str, *, reviewer: str, note: str = "") -> Run:
        run = self._runs.get(run_id)
        pending = run.pending_review
        if not pending:
            raise InvalidRequest(f"Run {run_id!r} has nothing awaiting review")
        for artifact in pending:
            artifact.status = ArtifactStatus.APPROVED
            artifact.review = Review(
                decision=ReviewDecision.APPROVE, reviewer=reviewer, note=note
            )
        run.status = self._settle_status(run)
        return self._runs.save(run)

    def _decide(
        self, run_id: str, artifact_id: str, decision: ReviewDecision, reviewer: str, note: str
    ) -> Run:
        if not reviewer:
            raise InvalidRequest("A review needs a reviewer")
        run = self._runs.get(run_id)
        artifact = run.artifact(artifact_id)
        if artifact is None:
            raise NotFound(f"Run {run_id!r} has no artifact {artifact_id!r}")
        if artifact.status not in (ArtifactStatus.PENDING_REVIEW, ArtifactStatus.DRAFT):
            raise InvalidRequest(
                f"Artifact {artifact_id!r} is already {artifact.status}, "
                "so it cannot be reviewed again"
            )

        artifact.status = (
            ArtifactStatus.APPROVED
            if decision == ReviewDecision.APPROVE
            else ArtifactStatus.REJECTED
        )
        artifact.review = Review(decision=decision, reviewer=reviewer, note=note)
        run.status = self._settle_status(run)
        return self._runs.save(run)

    @staticmethod
    def _settle_status(run: Run) -> RunStatus:
        if run.pending_review:
            return RunStatus.AWAITING_REVIEW
        return RunStatus.COMPLETED

    @staticmethod
    def release(run: Run) -> list[Artifact]:
        """Return the artifacts that may leave the harness.

        Raises rather than silently filtering, so a caller that forgot about review
        finds out at the boundary instead of shipping a short list it did not expect.
        """
        if run.pending_review:
            raise ReviewRequired(
                f"Run {run.id!r} still has {len(run.pending_review)} artifact(s) awaiting review"
            )
        return run.released


__all__ = ["AUTO_REVIEWER", "ReviewGate"]
