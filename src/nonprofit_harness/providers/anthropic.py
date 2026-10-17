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
        self.prices = prices if prices is not None else PriceBook.from_env()
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

        payload: dict[str, Any] = {
            "model": used,
            "max_tokens": max_output_tokens or self.default_max_output_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system

        output_config: dict[str, Any] = {}
        if self.effort:
            output_config["effort"] = self.effort
        if json_schema is not None:
            try:
                # Enforced by the API rather than requested in the prompt. Asking in
                # the prompt worked on the larger models, but Haiku 5.5 often replied
                # with the schema itself instead of an answer.
                strict = strict_schema(json_schema)
                output_config["format"] = {"type": "json_schema", "schema": strict}
            except NotStrict:
                # A free-form map cannot be expressed, and closing it would force the
                # model to return it empty. Asking is weaker but loses nothing.
                schema_text = json.dumps(json_schema, separators=(",", ":"))
                payload["system"] = (
                    f"{system or ''}\n\nReply with JSON only, matching this schema. "
                    f"No prose, no code fence.\n{schema_text}"
                ).strip()
        if output_config:
            payload["output_config"] = output_config

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
        answered = body.get("model") or used
        usage = self._usage(answered, used, body)
        if body.get("stop_reason") == "refusal":
            category = _refusal_category(body)
            # The refused call was still billed. Kept on the error so the budget
            # wrapper counts the spend instead of losing it.
            raise ProviderError(
                f"Model {answered} refused the request"
                + (f" (category: {category})" if category else ""),
                usage=usage,
            )

        text = "".join(
            block.get("text", "")
            for block in (body.get("content") or [])
            if block.get("type") == "text"
        )

        return ModelResponse(text=text, model=answered, usage=usage, raw=body)

    def _usage(self, answered: str, requested: str, body: dict[str, Any]) -> Usage:
        usage = body.get("usage") or {}
        return self.prices.usage(
            answered,
            int(usage.get("input_tokens") or 0),
            int(usage.get("output_tokens") or 0),
            requested=requested,
        )


#: Constraints structured outputs reject. Dropped rather than sent, so a schema written
#: for another provider still works here; the caller validates what comes back anyway.
_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "uniqueItems",
    }
)


class NotStrict(ValueError):
    """The schema holds something structured outputs cannot express."""


def strict_schema(schema: Any) -> Any:
    """A copy of `schema` in the form structured outputs accepts.

    Every object must say `additionalProperties: false`, and some constraints are not
    supported at all. Only schema positions are rewritten: a property that happens to be
    named `maximum`, or an `enum` value that is an object, passes through untouched.
    Raises `NotStrict` for a free-form map (`additionalProperties` given as a schema),
    which closing would silently turn into an object that must stay empty.
    """
    if not isinstance(schema, dict):
        return schema
    if isinstance(schema.get("additionalProperties"), dict):
        raise NotStrict("additionalProperties as a schema (a free-form map)")
    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _UNSUPPORTED_KEYWORDS:
            continue
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            cleaned[key] = {name: strict_schema(sub) for name, sub in value.items()}
        elif key in _SCHEMA_LISTS and isinstance(value, list):
            cleaned[key] = [strict_schema(sub) for sub in value]
        elif key in _SCHEMA_VALUES:
            cleaned[key] = strict_schema(value)
        else:
            cleaned[key] = value
    kind = cleaned.get("type")
    is_object = kind == "object" or (isinstance(kind, list) and "object" in kind)
    if is_object or "properties" in cleaned:
        cleaned["additionalProperties"] = False
    return cleaned


_SCHEMA_MAPS = frozenset(
    {"properties", "$defs", "definitions", "patternProperties", "dependentSchemas"}
)
_SCHEMA_LISTS = frozenset({"anyOf", "allOf", "oneOf", "prefixItems"})
_SCHEMA_VALUES = frozenset({"items", "not", "if", "then", "else", "contains", "propertyNames"})


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
    "NotStrict",
    "strict_schema",
]
