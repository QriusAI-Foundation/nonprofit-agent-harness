from __future__ import annotations

from fastapi import APIRouter, Depends

from nonprofit_harness.api.deps import AppContext, get_ctx, get_principal, reviewer_name
from nonprofit_harness.api.schemas import ArtifactOut, ReviewDecisionIn, RunOut
from nonprofit_harness.auth import Principal

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/queue", response_model=list[RunOut])
def queue(
    limit: int = 50,
    ctx: AppContext = Depends(get_ctx),
    principal: Principal = Depends(get_principal),
) -> list[RunOut]:
    """Everything waiting on a person."""
    from nonprofit_harness.core.types import RunStatus

    runs = ctx.stores.runs.list(
        org_id=principal.org_id, status=RunStatus.AWAITING_REVIEW, limit=limit
    )
    return [RunOut.of(run) for run in runs]


@router.post("/{run_id}/artifacts/{artifact_id}/approve", response_model=RunOut)
def approve(
    run_id: str,
    artifact_id: str,
    body: ReviewDecisionIn,
    ctx: AppContext = Depends(get_ctx),
    principal: Principal = Depends(get_principal),
) -> RunOut:
    run = ctx.gate.approve(
        run_id, artifact_id, reviewer=reviewer_name(principal), note=body.note
    )
    return RunOut.of(run)


@router.post("/{run_id}/artifacts/{artifact_id}/reject", response_model=RunOut)
def reject(
    run_id: str,
    artifact_id: str,
    body: ReviewDecisionIn,
    ctx: AppContext = Depends(get_ctx),
    principal: Principal = Depends(get_principal),
) -> RunOut:
    run = ctx.gate.reject(run_id, artifact_id, reviewer=reviewer_name(principal), note=body.note)
    return RunOut.of(run)


@router.post("/{run_id}/approve-all", response_model=RunOut)
def approve_all(
    run_id: str,
    body: ReviewDecisionIn,
    ctx: AppContext = Depends(get_ctx),
    principal: Principal = Depends(get_principal),
) -> RunOut:
    run = ctx.gate.approve_all(run_id, reviewer=reviewer_name(principal), note=body.note)
    return RunOut.of(run)


@router.get("/{run_id}/released", response_model=list[ArtifactOut])
def released(run_id: str, ctx: AppContext = Depends(get_ctx)) -> list[ArtifactOut]:
    """Only what a human approved. Errors if anything is still pending."""
    run = ctx.stores.runs.get(run_id)
    return [ArtifactOut.of(a) for a in ctx.gate.release(run)]


__all__ = ["router"]
