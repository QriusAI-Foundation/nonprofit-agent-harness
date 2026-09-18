"""Claude models through the Anthropic Messages API.

No SDK. The harness already depends on httpx, so this adds nothing to an install.
"""

from __future__ import annotations

import json
import os
from typing import Any

from nonprofit_harness.core.errors import ProviderError
from nonprofit_harness.core.usage import Usage
from nonprofit_harness.providers._http import build_client, post_json
from nonprofit_harness.providers.base import ModelResponse, PriceBook

BASE_URL = "https://api.anthropic.com/v1"
KEY_ENV = "ANTHROPIC_API_KEY"
API_VERSION = "2023-06-01"

#: A small model by default, because grant budgets are the constraint here rather than
#: benchmark scores. Check it against currently available models before deploying.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

#: The Messages API requires max_tokens, unlike most others, so there has to be a value
#: even when the caller does not care.
DEFAULT_MAX_OUTPUT_TOKENS = 4096


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        base_url: str = BASE_URL,
        timeout: float = 60.0,
        prices: PriceBook | None = None,
        client: Any = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        api_version: str = API_VERSION,
    ) -> None:
        self.default_model = model
        self.base_url = base_url.rstrip("/")
        self.prices = prices or PriceBook()
        self.default_max_output_tokens = max_output_tokens
        self.api_version = api_version
        self._api_key = api_key or os.getenv(KEY_ENV)
        self._client = client or build_client(timeout)

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> ModelResponse:
        if not self._api_key:
            raise ProviderError(f"No API key. Set {KEY_ENV}, or pass api_key")

        used = model or self.default_model
        instruction = system or ""

        if json_schema is not None:
            # The Messages API has no response_format equivalent, so the schema is
            # asked for rather than enforced. Callers must still validate what comes
            # back. Said plainly because a silent difference in strictness between
            # providers is how an agent starts failing only on one of them.
            schema_text = json.dumps(json_schema, separators=(",", ":"))
            instruction = (
                f"{instruction}\n\nReply with JSON only, matching this schema. "
                f"No prose, no code fence.\n{schema_text}"
            ).strip()

        payload: dict[str, Any] = {
            "model": used,
            "max_tokens": max_output_tokens or self.default_max_output_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if instruction:
            payload["system"] = instruction

        body = post_json(
            self._client,
            f"{self.base_url}/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": self.api_version,
                "Content-Type": "application/json",
            },
            payload=payload,
            secret=self._api_key,
        )

        text = "".join(
            block.get("text", "")
            for block in (body.get("content") or [])
            if block.get("type") == "text"
        )

        usage = body.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)

        return ModelResponse(
            text=text,
            model=body.get("model") or used,
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=self.prices.cost(used, input_tokens, output_tokens),
                calls=1,
            ),
            raw=body,
        )


__all__ = ["API_VERSION", "BASE_URL", "DEFAULT_MODEL", "KEY_ENV", "AnthropicProvider"]
