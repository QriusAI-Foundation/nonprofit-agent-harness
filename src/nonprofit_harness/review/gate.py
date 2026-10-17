from __future__ import annotations

import logging

from nonprofit_harness.core.errors import (
    InvalidRequest,
    NotFound,
    ReviewConflict,
    ReviewRequired,
)
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
# Names with this prefix belong to the harness. A person who could sign as one could
# make a human approval look like a routine automatic release, or the reverse.
SYSTEM_REVIEWER_PREFIX = "system:"

logger = logging.getLogger("nonprofit_harness.review")

_STATUS_FOR = {
    ReviewDecision.APPROVE: ArtifactStatus.APPROVED,
    ReviewDecision.REJECT: ArtifactStatus.REJECTED,
}


class ReviewGate:
    """Holds agent output until a person signs it off.

    The sector reason: an unreviewed model output here can reach a beneficiary, a
    funder report, or a training room. The engineering consequence is that
    "released" is a state a human puts an artifact into, never a default.

    Every decision is recorded, including automatic ones, so an audit can always
    answer who released a given artifact.

    The gate, not the agent, owns decision state. Whatever status or review an agent
    put on its artifacts is discarded on the way in, and every decision after that
    is one atomic store operation, so two reviewers cannot overwrite each other.
    """

    def __init__(self, runs: RunStore) -> None:
        self._runs = runs

    def submit(self, run: Run) -> Run:
        _take_custody(run)
        for artifact in run.artifacts:
            artifact.status = ArtifactStatus.PENDING_REVIEW
        run.status = _settle_status(run)
        return self._runs.save(run)

    def auto_release(self, run: Run, *, reason: str = "agent opted out of review") -> Run:
        """Release without a reviewer, except where the harness found a problem.

        An artifact whose claims failed verification is sent to a person even when
        the agent opted out. Opting out of review is a statement that the output is
        routine; a citation that does not resolve is evidence that it is not. The
        rule lives here rather than in the runner so no caller can route around it.
        """
        _take_custody(run)
        for artifact in run.artifacts:
            if artifact.failed_verification:
                artifact.status = ArtifactStatus.PENDING_REVIEW
                continue
            _record(artifact, Review(ReviewDecision.APPROVE, AUTO_REVIEWER, note=reason))
        run.status = _settle_status(run)
        return self._runs.save(run)

    def approve(self, run_id: str, artifact_id: str, *, reviewer: str, note: str = "") -> Run:
        return self._decide(run_id, artifact_id, ReviewDecision.APPROVE, reviewer, note)

    def reject(self, run_id: str, artifact_id: str, *, reviewer: str, note: str = "") -> Run:
        return self._decide(run_id, artifact_id, ReviewDecision.REJECT, reviewer, note)

    def approve_all(self, run_id: str, *, reviewer: str, note: str = "") -> Run:
        _check_reviewer(reviewer)

        def change(run: Run) -> bool:
            pending = run.pending_review
            if not pending:
                raise InvalidRequest(f"Run {run_id!r} has nothing awaiting review")
            for artifact in pending:
                _record(artifact, Review(ReviewDecision.APPROVE, reviewer, note=note))
            run.status = _settle_status(run)
            return True

        return self._runs.update(run_id, change)

    def _decide(
        self, run_id: str, artifact_id: str, decision: ReviewDecision, reviewer: str, note: str
    ) -> Run:
        _check_reviewer(reviewer)

        def change(run: Run) -> bool:
            artifact = run.artifact(artifact_id)
            if artifact is None:
                raise NotFound(f"Run {run_id!r} has no artifact {artifact_id!r}")
            if not _record(artifact, Review(decision, reviewer, note=note)):
                return False
            run.status = _settle_status(run)
            return True

        return self._runs.update(run_id, change)

    @staticmethod
    def release(run: Run) -> list[Artifact]:
        """Return the artifacts that may leave the harness.

        Raises rather than silently filtering, so a caller that forgot about review
        finds out at the boundary instead of shipping a short list it did not expect.
        An approved status with no matching record is refused the same way: the
        record is the evidence that someone decided, and the status alone is not.
        """
        if run.pending_review:
            raise ReviewRequired(
                f"Run {run.id!r} still has {len(run.pending_review)} artifact(s) awaiting review"
            )
        if run.incoherent:
            ids = ", ".join(repr(a.id) for a in run.incoherent)
            raise ReviewRequired(
                f"Run {run.id!r} has artifact(s) {ids} whose status has no valid decision "
                "record, so they cannot be released"
            )
        return run.released


def _take_custody(run: Run) -> None:
    """Discard any decision state that arrived with the agent's result.

    Reset rather than reject: an agent that sets a status is wrong about whose job
    that is, but its work is still worth reviewing, and failing the run would throw
    away output that was already paid for. Resetting makes the agent's claim
    irrelevant, which is all the guarantee needs.

    Only a run that has not reached review yet is taken in. On a run that is
    already awaiting review or finished, the reset would erase decisions that
    people made.
    """
    if run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
        raise InvalidRequest(
            f"Run {run.id!r} is already {run.status}; only a new agent result can be "
            "submitted for review"
        )
    for artifact in run.artifacts:
        if artifact.status != ArtifactStatus.DRAFT or artifact.review is not None:
            logger.warning(
                "Run %s: discarded agent-supplied decision state on artifact %s "
                "(status=%s, review=%s)",
                run.id,
                artifact.id,
                artifact.status,
                "present" if artifact.review is not None else "none",
            )
        artifact.status = ArtifactStatus.DRAFT
        artifact.review = None


def _record(artifact: Artifact, review: Review) -> bool:
    """Apply one decision. Returns False when it repeats the recorded one exactly.

    The same decision by the same reviewer is a retry, so it succeeds without
    touching the original time or note. Anything else on a decided artifact is a
    conflict: the first decision stands, whoever asks second.
    """
    if artifact.status in (ArtifactStatus.DRAFT, ArtifactStatus.PENDING_REVIEW):
        artifact.status = _STATUS_FOR[review.decision]
        artifact.review = review
        return True

    recorded = artifact.review if artifact.decision_is_coherent else None
    if (
        recorded is not None
        and recorded.decision == review.decision
        and recorded.reviewer == review.reviewer
    ):
        return False
    if recorded is None:
        raise ReviewConflict(
            f"Artifact {artifact.id!r} is {artifact.status} without a valid decision "
            "record, so it cannot be reviewed again",
            artifact_id=artifact.id,
            status=str(artifact.status),
        )
    raise ReviewConflict(
        f"Artifact {artifact.id!r} was already {artifact.status} by {recorded.reviewer} "
        f"at {recorded.at.isoformat()}; this {review.decision} by {review.reviewer} "
        "was not applied",
        artifact_id=artifact.id,
        status=str(artifact.status),
        decided_by=recorded.reviewer,
        decided_at=recorded.at.isoformat(),
        requested=str(review.decision),
    )


def _check_reviewer(reviewer: str) -> None:
    if not reviewer or not reviewer.strip():
        raise InvalidRequest("A review needs a reviewer")
    if reviewer.strip().casefold().startswith(SYSTEM_REVIEWER_PREFIX):
        raise InvalidRequest(
            f"Reviewer names starting with {SYSTEM_REVIEWER_PREFIX!r} are reserved for the harness"
        )


def _settle_status(run: Run) -> RunStatus:
    if run.pending_review:
        return RunStatus.AWAITING_REVIEW
    return RunStatus.COMPLETED


__all__ = ["AUTO_REVIEWER", "SYSTEM_REVIEWER_PREFIX", "ReviewGate"]
