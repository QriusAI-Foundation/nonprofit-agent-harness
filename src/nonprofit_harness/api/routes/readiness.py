from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from nonprofit_harness.api.deps import AppContext, get_ctx
from nonprofit_harness.api.schemas import ReadinessScoreIn
from nonprofit_harness.readiness import score

router = APIRouter(prefix="/readiness", tags=["readiness"])


@router.get("/instrument")
def instrument(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return ctx.instrument.to_dict()


@router.post("/score")
def score_answers(body: ReadinessScoreIn, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return score(ctx.instrument, body.answers).to_dict()


__all__ = ["router"]
