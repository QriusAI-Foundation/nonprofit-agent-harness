from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nonprofit_harness import __version__
from nonprofit_harness.api.deps import AppContext
from nonprofit_harness.api.routes import admin, auth, readiness, review, runs, webhooks
from nonprofit_harness.auth import SessionTokens
from nonprofit_harness.config import HarnessConfig
from nonprofit_harness.core.errors import HarnessError
from nonprofit_harness.core.registry import AgentRegistry
from nonprofit_harness.core.registry import registry as default_registry
from nonprofit_harness.core.runner import AgentRunner
from nonprofit_harness.providers import load_provider
from nonprofit_harness.providers.base import ModelProvider
from nonprofit_harness.readiness.instrument import Instrument, example_instrument
from nonprofit_harness.review.gate import ReviewGate
from nonprofit_harness.storage import load_stores
from nonprofit_harness.storage.base import Stores

logger = logging.getLogger("nonprofit_harness")

API_PREFIX = "/v1"


def create_app(
    *,
    config: HarnessConfig | None = None,
    registry: AgentRegistry | None = None,
    stores: Stores | None = None,
    provider: ModelProvider | None = None,
    instrument: Instrument | None = None,
) -> FastAPI:
    """Build the API.

    Every collaborator can be passed in, which is what lets the test suite run the
    real application against in-memory storage and an offline provider instead of
    testing a parallel, simplified version of it.
    """
    config = config or HarnessConfig.from_env()
    registry = registry or default_registry
    stores = stores or load_stores(config.storage)
    provider = provider or load_provider(config.provider, **_provider_kwargs(config))
    instrument = instrument or example_instrument()

    for warning in config.validate():
        logger.warning("config: %s", warning)

    gate = ReviewGate(stores.runs)
    ctx = AppContext(
        config=config,
        registry=registry,
        stores=stores,
        runner=AgentRunner(
            registry=registry, stores=stores, provider=provider, config=config, gate=gate
        ),
        gate=gate,
        instrument=instrument,
        tokens=SessionTokens(config.jwt_secret, ttl_seconds=config.jwt_ttl_seconds)
        if config.jwt_secret
        else None,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # A recycled instance leaves its in-flight runs marked running forever, so the
        # replacement resolves them. Failures here must not stop the app booting: a
        # reachable service with stale records beats no service at all.
        try:
            ctx.runner.reap_abandoned()
        except Exception:  # noqa: BLE001 - startup must not depend on storage health
            logger.exception("Could not reap abandoned runs at startup")
        yield

    app = FastAPI(
        title="Nonprofit Agent Harness",
        version=__version__,
        description=(
            "Run agents with a human review gate, a per-run budget ceiling, "
            "and readiness scoring."
        ),
        lifespan=lifespan,
    )
    app.state.ctx = ctx

    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(HarnessError)
    async def harness_error_handler(_: Request, exc: HarnessError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"error": str(exc), "code": exc.code}
        )

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "agents": len(registry),
            "provider": getattr(provider, "name", "unknown"),
            "storage": config.storage,
        }

    for module in (runs, review, readiness, auth, admin, webhooks):
        app.include_router(module.router, prefix=API_PREFIX)

    return app


def _provider_kwargs(config: HarnessConfig) -> dict[str, Any]:
    if config.provider in {"google", "gemini", "adk", "vertex"} and config.model:
        return {"model": config.model}
    return {}


__all__ = ["API_PREFIX", "create_app"]
