"""Claude models through the Anthropic Messages API.

No SDK. The harness already depends on httpx, so this adds nothing to an install.

The Claude 5.x models reject `temperature`, `top_p` and `top_k` with HTTP 400, so this
adapter never sends them and every call runs at the model's own default sampling. The
`temperature` argument on `generate` is accepted to satisfy the provider protocol and is
ignored here. Depth is set with `effort` instead, and thinking is adaptive and on by
default, so there is nothing to switch on.
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
DEFAULT_MODEL = "claude-haiku-5-5"

#: Read when no effort is passed, so a deployment can set depth without code changes.
EFFORT_ENV = "ANTHROPIC_EFFORT"

#: The Messages API requires max_tokens, unlike most others, so there has to be a value
#: even when the caller does not care.
DEFAULT_MAX_OUTPUT_TOKENS = 4096


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = BASE_URL,
        timeout: float = 60.0,
        prices: PriceBook | None = None,
        client: Any = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        api_version: str = API_VERSION,
        effort: str | None = None,
    ) -> None:
        self.default_model = model or os.getenv("HARNESS_MODEL") or DEFAULT_MODEL
        self.base_url = base_url.rstrip("/")
        self.prices = prices or PriceBook()
        self.default_max_output_tokens = max_output_tokens
        self.api_version = api_version
        self.effort = effort or os.getenv(EFFORT_ENV) or None
        self._api_key = api_key or os.getenv(KEY_ENV)
        self._client = client or build_client(timeout)

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,  # ignored, see the module docstring
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
            "messages": [{"role": "user", "content": prompt}],
        }
        if instruction:
            payload["system"] = instruction
        if self.effort:
            payload["output_config"] = {"effort": self.effort}

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

        # A refusal can still carry partial text. Passing it on would put a fragment
        # into an artifact as if it were a complete answer.
        usage = self._usage(used, body)
        if body.get("stop_reason") == "refusal":
            category = _refusal_category(body)
            error = ProviderError(
                f"Model {body.get('model') or used} refused the request"
                + (f" (category: {category})" if category else "")
            )
            # The refused call was still billed. Kept on the error so whoever catches
            # it can count the spend instead of losing it.
            error.usage = usage
            raise error

        text = "".join(
            block.get("text", "")
            for block in (body.get("content") or [])
            if block.get("type") == "text"
        )

        return ModelResponse(text=text, model=body.get("model") or used, usage=usage, raw=body)

    def _usage(self, model: str, body: dict[str, Any]) -> Usage:
        usage = body.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        return Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=self.prices.cost(model, input_tokens, output_tokens),
            calls=1,
        )


def _refusal_category(body: dict[str, Any]) -> str | None:
    # `stop_details` is only populated on a refusal, and its category can be null.
    details = body.get("stop_details")
    if isinstance(details, dict) and details.get("category"):
        return str(details["category"])
    return None


__all__ = [
    "API_VERSION",
    "BASE_URL",
    "DEFAULT_MODEL",
    "EFFORT_ENV",
    "KEY_ENV",
    "AnthropicProvider",
]
