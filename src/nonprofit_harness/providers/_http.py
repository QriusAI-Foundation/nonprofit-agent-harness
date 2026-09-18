"""Shared plumbing for providers that speak HTTP directly.

Written against `httpx`, which the harness already depends on, so an adapter for a new
vendor adds no install weight. A nonprofit with donated credits on one platform should
not have to install three SDKs to use them.
"""

from __future__ import annotations

import time
from typing import Any

from nonprofit_harness.core.errors import ProviderError
from nonprofit_harness.providers.base import scrub_secrets

MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2.0

#: Worth waiting out. A rate limit clears on its own and an upstream blip often does
#: too. Anything else fails just as fast on a second attempt, so retrying only delays
#: the error and spends the budget twice.
RETRYABLE = frozenset({429, 500, 502, 503, 504})


def post_json(
    client: Any,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    secret: str | None = None,
    max_retries: int = MAX_RETRIES,
    backoff: float = INITIAL_BACKOFF_SECONDS,
) -> dict[str, Any]:
    """POST and return the decoded body, retrying only what is worth retrying.

    Every error path runs through `scrub_secrets`, because a provider's own message can
    quote the request it failed on.
    """
    delay = backoff
    last = ""

    for attempt in range(max_retries + 1):
        try:
            response = client.post(url, headers=headers, json=payload)
        except Exception as exc:  # noqa: BLE001 - any transport failure, normalised
            raise ProviderError(scrub_secrets(f"{type(exc).__name__}: {exc}", secret)) from None

        status = getattr(response, "status_code", 200)
        if status < 400:
            try:
                return response.json()
            except Exception as exc:  # noqa: BLE001 - a non-JSON 200 is still a failure
                raise ProviderError(
                    scrub_secrets(f"Provider returned unreadable JSON: {exc}", secret)
                ) from None

        last = scrub_secrets(_body(response), secret)
        if status not in RETRYABLE or attempt == max_retries:
            raise ProviderError(f"Provider returned HTTP {status}: {last[:400]}")

        retry_after = _retry_after(response)
        time.sleep(retry_after if retry_after is not None else delay)
        delay *= 2

    raise ProviderError(f"Exhausted retries: {last[:400]}")


def _body(response: Any) -> str:
    try:
        return str(response.json())
    except Exception:  # noqa: BLE001 - fall back to raw text
        return str(getattr(response, "text", ""))


def _retry_after(response: Any) -> float | None:
    """Honour the server's own backoff when it states one."""
    headers = getattr(response, "headers", None) or {}
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
    except AttributeError:
        return None
    if not value:
        return None
    try:
        # Cap it. A server asking for an hour should surface as an error, not a hang.
        return min(float(value), 60.0)
    except (TypeError, ValueError):
        return None


def build_client(timeout: float) -> Any:
    import httpx

    return httpx.Client(timeout=timeout)


__all__ = ["MAX_RETRIES", "RETRYABLE", "build_client", "post_json"]
