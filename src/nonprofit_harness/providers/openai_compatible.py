"""Any server speaking the OpenAI chat-completions API.

One adapter, many vendors. OpenAI itself, and also Groq, Together, Fireworks,
OpenRouter, vLLM, LM Studio, and Ollama through its compatibility endpoint. Pointing at
a different one is a base URL, not a code change, which matters here: an organisation
holding donated credits on one platform, or required to keep data on its own hardware,
should not need a different harness.

    OpenAIProvider(model="...", base_url="http://localhost:11434/v1", api_key="ollama")

No SDK. The harness already depends on httpx, so this adds nothing to an install.
"""

from __future__ import annotations

import os
from typing import Any

from nonprofit_harness.core.errors import InvalidRequest, ProviderError
from nonprofit_harness.core.usage import Usage
from nonprofit_harness.providers._http import build_client, post_json
from nonprofit_harness.providers.base import ModelResponse, PriceBook

BASE_URL = "https://api.openai.com/v1"
KEY_ENV = "OPENAI_API_KEY"


class OpenAIProvider:
    """Chat completions against any OpenAI-compatible endpoint."""

    name = "openai"

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        prices: PriceBook | None = None,
        client: Any = None,
        max_output_tokens: int = 4096,
    ) -> None:
        # No default model. Every compatible server offers different ones, so guessing
        # produces a confusing 404 from the vendor instead of a clear error from here.
        self.default_model = model or os.getenv("HARNESS_MODEL") or ""
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or BASE_URL).rstrip("/")
        self.prices = prices or PriceBook()
        self.default_max_output_tokens = max_output_tokens
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
        used = model or self.default_model
        if not used:
            raise InvalidRequest(
                "OpenAIProvider needs a model. Pass model=, or set HARNESS_MODEL. "
                "Compatible servers each offer different models, so there is no default"
            )
        if not self._api_key:
            raise ProviderError(
                f"No API key. Set {KEY_ENV}, or pass api_key. A local server that "
                "ignores the key still needs a placeholder"
            )

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": used,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_output_tokens or self.default_max_output_tokens,
        }
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": json_schema, "strict": False},
            }

        body = post_json(
            self._client,
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            payload=payload,
            secret=self._api_key,
        )

        choices = body.get("choices") or []
        text = ""
        if choices:
            text = (choices[0].get("message") or {}).get("content") or ""

        usage = body.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)

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


__all__ = ["BASE_URL", "KEY_ENV", "OpenAIProvider"]
