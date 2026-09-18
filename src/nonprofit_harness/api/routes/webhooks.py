from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request

from nonprofit_harness.core.errors import Unauthorized

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

Handler = Callable[[dict[str, Any]], Any]

#: Checked in order when a registration does not name its own header.
DEFAULT_SIGNATURE_HEADERS = ("x-signature", "x-hub-signature-256", "x-webhook-signature")


@dataclass(frozen=True, slots=True)
class WebhookRoute:
    handler: Handler
    secret: str | None = None
    signature_header: str | None = None

    def headers_to_check(self) -> tuple[str, ...]:
        return (self.signature_header,) if self.signature_header else DEFAULT_SIGNATURE_HEADERS


_handlers: dict[str, WebhookRoute] = {}


def register_webhook(
    source: str,
    handler: Handler,
    *,
    secret: str | None = None,
    signature_header: str | None = None,
) -> None:
    """Attach a handler for one inbound source.

    Form tools, CRMs, and donation platforms all post differently and each names its
    signature header differently, so the harness ships the plumbing (routing,
    signature checking, error shape) and leaves both the header name and the payload
    parsing to whoever knows their own vendor.
    """
    _handlers[source] = WebhookRoute(handler, secret, signature_header)


def clear_webhooks() -> None:
    _handlers.clear()


def verify_signature(secret: str, body: bytes, provided: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    candidate = provided.strip()
    if "=" in candidate:
        candidate = candidate.split("=", 1)[1]
    return hmac.compare_digest(expected, candidate.lower())


@router.post("/{source}")
async def receive(source: str, request: Request) -> dict[str, Any]:
    route = _handlers.get(source)
    if route is None:
        # Unknown sources are acknowledged rather than rejected, so a vendor does
        # not disable the endpoint for repeated failures while it is being wired up.
        return {"status": "ignored", "source": source}

    body = await request.body()

    if route.secret:
        provided = next(
            (
                value
                for value in (request.headers.get(h) for h in route.headers_to_check())
                if value
            ),
            "",
        )
        if not provided or not verify_signature(route.secret, body, provided):
            raise Unauthorized(f"Webhook signature for {source!r} did not verify")

    payload = await request.json()
    result = route.handler(payload)
    return {"status": "ok", "source": source, "result": result}


__all__ = [
    "DEFAULT_SIGNATURE_HEADERS",
    "WebhookRoute",
    "clear_webhooks",
    "register_webhook",
    "router",
    "verify_signature",
]
