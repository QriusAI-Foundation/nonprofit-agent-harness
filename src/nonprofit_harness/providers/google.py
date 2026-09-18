from __future__ import annotations

import os
import time
from typing import Any

from nonprofit_harness.core.errors import ProviderError
from nonprofit_harness.core.usage import Usage
from nonprofit_harness.providers.base import ModelResponse, PriceBook

_MAX_RETRIES = 5
_INITIAL_BACKOFF_SECONDS = 5.0


class GoogleProvider:
    """Gemini access, through either Vertex AI or the Gemini API.

    Install with the `adk` extra. This is the default provider for deployments,
    and the one Google's own ADK agents use underneath, so an ADK agent and a
    plain harness agent share the same model path and the same cost accounting.
    """

    name = "google"

    def __init__(
        self,
        *,
        # A small, cheap model on purpose. Grant budgets are the constraint here, so
        # the default should be the one that costs least, not the one that scores best.
        # Check it against currently available models before a real deployment.
        model: str = "gemini-3.5-flash-lite",
        project: str | None = None,
        location: str | None = None,
        api_key: str | None = None,
        use_vertex: bool | None = None,
        prices: PriceBook | None = None,
        client: Any = None,
    ) -> None:
        self.default_model = model
        self.prices = prices or PriceBook()
        self._client = client
        if client is None:
            self._client = _build_client(
                project=project,
                location=location,
                api_key=api_key,
                use_vertex=use_vertex,
            )

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
        from google.genai import types

        used = model or self.default_model
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        if json_schema is not None:
            config.response_mime_type = "application/json"
            config.response_schema = json_schema

        response = self._with_retry(
            lambda: self._client.models.generate_content(
                model=used, contents=prompt, config=config
            )
        )

        meta = getattr(response, "usage_metadata", None)
        input_tokens = int(getattr(meta, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(meta, "candidates_token_count", 0) or 0)

        return ModelResponse(
            text=response.text or "",
            model=used,
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=self.prices.cost(used, input_tokens, output_tokens),
                calls=1,
            ),
            raw=response,
        )

    def _with_retry(self, call):
        from google.genai import errors as genai_errors

        delay = _INITIAL_BACKOFF_SECONDS
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return call()
            except genai_errors.APIError as exc:
                # 429 is a per-minute quota ceiling, which waiting actually clears.
                # Anything else will fail again just as fast, so surface it now.
                if exc.code != 429 or attempt == _MAX_RETRIES:
                    raise ProviderError(str(exc)) from exc
                time.sleep(delay)
                delay *= 2
        raise ProviderError("Exhausted retries without a response")


def _build_client(
    *,
    project: str | None,
    location: str | None,
    api_key: str | None,
    use_vertex: bool | None,
) -> Any:
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ProviderError(
            "GoogleProvider needs the `adk` extra: pip install 'nonprofit-agent-harness[adk]'"
        ) from exc

    key = api_key or os.getenv("GOOGLE_API_KEY")
    vertex = use_vertex if use_vertex is not None else not key
    if vertex:
        return genai.Client(
            vertexai=True,
            project=project or os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )
    return genai.Client(api_key=key)


__all__ = ["GoogleProvider"]
