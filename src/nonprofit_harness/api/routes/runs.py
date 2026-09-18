from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Response, UploadFile, status

from nonprofit_harness.api.deps import AppContext, get_ctx, get_principal
from nonprofit_harness.api.schemas import AgentOut, BlobOut, RunCreate, RunOut
from nonprofit_harness.auth import Principal
from nonprofit_harness.core.errors import InvalidRequest
from nonprofit_harness.core.types import Document, RunStatus
from nonprofit_harness.documents import extract

router = APIRouter(tags=["runs"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.get("/agents", response_model=list[AgentOut])
def list_agents(ctx: AppContext = Depends(get_ctx)) -> list[AgentOut]:
    return [AgentOut(**agent.describe()) for agent in ctx.registry.all()]


@router.post("/uploads", response_model=BlobOut, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = File(...),
    ctx: AppContext = Depends(get_ctx),
    principal: Principal = Depends(get_principal),
) -> BlobOut:
    data = await file.read()
    if not data:
        raise InvalidRequest("Uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidRequest(f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit")

    media_type = file.content_type or "application/octet-stream"
    document = extract(data, media_type=media_type, name=file.filename or "upload")
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


@router.post("/runs", response_model=RunOut)
def create_run(
    body: RunCreate,
    background: BackgroundTasks,
    response: Response,
    ctx: AppContext = Depends(get_ctx),
    principal: Principal = Depends(get_principal),
) -> RunOut:
    org_id = body.org_id or principal.org_id
    documents = [_to_document(item, ctx) for item in body.inputs]
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
def get_run(run_id: str, ctx: AppContext = Depends(get_ctx)) -> RunOut:
    return RunOut.of(ctx.stores.runs.get(run_id))


def _to_document(item, ctx: AppContext) -> Document:
    if item.blob_id:
        meta = ctx.stores.blobs.meta(item.blob_id)
        raw = ctx.stores.blobs.get(item.blob_id)
        return extract(raw, media_type=meta.media_type, name=meta.name)
    if not item.text.strip():
        raise InvalidRequest("Each input needs either text or a blob_id")
    return Document(text=item.text, name=item.name, media_type=item.media_type)


__all__ = ["router"]
