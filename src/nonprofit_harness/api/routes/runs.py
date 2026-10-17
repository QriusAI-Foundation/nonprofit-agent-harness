from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Response, UploadFile, status

from nonprofit_harness.api.deps import (
    AppContext,
    authorized_blob,
    authorized_run,
    get_ctx,
    get_principal,
    org_for_new_run,
)
from nonprofit_harness.api.schemas import AgentOut, BlobOut, RunCreate, RunOut
from nonprofit_harness.auth import Principal
from nonprofit_harness.core.errors import InvalidRequest
from nonprofit_harness.core.types import Document, Run, RunStatus
from nonprofit_harness.documents import ExtractionLimits, extract

router = APIRouter(tags=["runs"])

#: Small enough that a refused upload holds at most this much past the limit.
_READ_CHUNK = 64 * 1024


@router.get("/agents", response_model=list[AgentOut])
def list_agents(ctx: AppContext = Depends(get_ctx)) -> list[AgentOut]:
    return [AgentOut(**agent.describe()) for agent in ctx.registry.all()]


@router.post("/uploads", response_model=BlobOut, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = File(...),
    ctx: AppContext = Depends(get_ctx),
    principal: Principal = Depends(get_principal),
) -> BlobOut:
    limits = ExtractionLimits.from_config(ctx.config)
    data = await _read_capped(file, limits)
    if not data:
        raise InvalidRequest("Uploaded file is empty")

    media_type = file.content_type or "application/octet-stream"
    # Extract before storing, so a file that fails a limit or will not parse leaves
    # no blob behind for a later run to trip over.
    document = extract(data, media_type=media_type, name=file.filename or "upload", limits=limits)
    blob = ctx.stores.blobs.put(
        org_id=principal.org_id,
        name=file.filename or "upload",
        data=data,
        media_type=media_type,
    )
    return BlobOut(
        id=blob.id,
        name=blob.name,
        media_type=blob.media_type,
        size=blob.size,
        characters=len(document.text),
    )


async def _read_capped(file: UploadFile, limits: ExtractionLimits) -> bytes:
    """Read an upload, refusing it as soon as it passes the size limit.

    Reading everything first and checking after meant an oversized file was held in
    memory whole before being refused.
    """
    name = file.filename or "upload"
    if file.size is not None:
        limits.check_size(file.size, name)
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_READ_CHUNK):
        total += len(chunk)
        limits.check_size(total, name)
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/runs", response_model=RunOut)
def create_run(
    body: RunCreate,
    background: BackgroundTasks,
    response: Response,
    ctx: AppContext = Depends(get_ctx),
    principal: Principal = Depends(get_principal),
) -> RunOut:
    org_id = org_for_new_run(body.org_id, principal, ctx)
    documents = [_to_document(item, ctx, principal) for item in body.inputs]
    if not documents:
        raise InvalidRequest("A run needs at least one input document")

    run = ctx.runner.create(body.agent, org_id=org_id, inputs=documents, options=body.options)

    if body.sync:
        return RunOut.of(ctx.runner.execute(run.id))

    background.add_task(ctx.runner.execute, run.id)
    response.status_code = status.HTTP_202_ACCEPTED
    return RunOut.of(run)


@router.get("/runs", response_model=list[RunOut])
def list_runs(
    status_filter: str | None = None,
    limit: int = 50,
    ctx: AppContext = Depends(get_ctx),
    principal: Principal = Depends(get_principal),
) -> list[RunOut]:
    parsed = RunStatus(status_filter) if status_filter else None
    runs = ctx.stores.runs.list(org_id=principal.org_id, status=parsed, limit=limit)
    return [RunOut.of(run) for run in runs]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run: Run = Depends(authorized_run)) -> RunOut:
    return RunOut.of(run)


def _to_document(item, ctx: AppContext, principal: Principal) -> Document:
    if item.blob_id:
        meta = authorized_blob(item.blob_id, ctx, principal)
        raw = ctx.stores.blobs.get(item.blob_id)
        return extract(
            raw,
            media_type=meta.media_type,
            name=meta.name,
            limits=ExtractionLimits.from_config(ctx.config),
        )
    if not item.text.strip():
        raise InvalidRequest("Each input needs either text or a blob_id")
    return Document(text=item.text, name=item.name, media_type=item.media_type)


__all__ = ["router"]
