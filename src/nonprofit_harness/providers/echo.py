from __future__ import annotations

import hashlib
import json
from typing import Any

from nonprofit_harness.core.usage import Usage
from nonprofit_harness.providers.base import ModelResponse


class EchoProvider:
    """A deterministic provider that calls no network.

    This is what makes `git clone && make test` work with no cloud account, no API
    key, and no spend. Tests and local development run against it; production swaps
    in a real provider without an agent noticing.
    """

    name = "echo"
    default_model = "echo-1"

    def __init__(self, *, canned: dict[str, str] | None = None, prefix: str = "") -> None:
        self._canned = canned or {}
        self._prefix = prefix
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append({"prompt": prompt, "system": system, "model": used})

        for needle, canned in self._canned.items():
            if needle in prompt:
                text = canned
                break
        else:
            text = self._synthesize(prompt, json_schema)

        return ModelResponse(
            text=text,
            model=used,
            usage=Usage(
                input_tokens=_estimate_tokens(prompt) + _estimate_tokens(system or ""),
                output_tokens=_estimate_tokens(text),
                cost_usd=0.0,
                calls=1,
            ),
        )

    def _synthesize(self, prompt: str, json_schema: dict[str, Any] | None) -> str:
        if json_schema is not None:
            return json.dumps(_skeleton_for(json_schema))
        digest = hashlib.sha256(prompt.encode()).hexdigest()[:8]
        return f"{self._prefix}[echo:{digest}] {prompt.strip()[:400]}"


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _skeleton_for(schema: dict[str, Any]) -> Any:
    kind = schema.get("type", "object")
    if kind == "object":
        props = schema.get("properties", {})
        return {key: _skeleton_for(sub) for key, sub in props.items()}
    if kind == "array":
        return [_skeleton_for(schema["items"])] if "items" in schema else []
    if kind == "integer":
        return 0
    if kind == "number":
        return 0.0
    if kind == "boolean":
        return False
    return schema.get("enum", ["echo"])[0] if schema.get("enum") else "echo"


__all__ = ["EchoProvider"]
