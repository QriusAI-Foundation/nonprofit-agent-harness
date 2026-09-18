from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from nonprofit_harness.core.usage import Usage

#: Some providers put the key in the request URL, and an error can quote the URL it
#: failed on. That text reaches logs and, through the API's error handler, a response
#: body. Providers sending the key in a header are not immune either, since an error
#: can still echo the credential back.
_KEY_IN_URL = re.compile(r"([?&](?:key|api_key|apikey|access_token)=)[^&\s\"'>]+", re.IGNORECASE)

#: Shorter than this and a blind replace would mangle unrelated text.
_MIN_SECRET_LENGTH = 8


def scrub_secrets(text: str, secret: str | None = None) -> str:
    """Remove credentials from text before it is logged or returned.

    Two passes, because either alone leaves a gap. The pattern catches a key embedded
    in any URL, including one this process never held. The literal replacement catches
    the configured key wherever it appears, including outside a URL.

    Every provider must run its error text through this. It lives here rather than in
    one provider so that writing a new adapter does not mean rediscovering the problem.
    """
    cleaned = _KEY_IN_URL.sub(r"\1[redacted]", text)
    if secret and len(secret) >= _MIN_SECRET_LENGTH:
        cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


@dataclass(frozen=True, slots=True)
class ModelResponse:
    text: str
    model: str
    usage: Usage
    raw: Any = None


@dataclass(frozen=True, slots=True)
class ModelRate:
    """Price per one million tokens, in USD."""

    input_per_1m: float
    output_per_1m: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return round(
            (input_tokens / 1_000_000) * self.input_per_1m
            + (output_tokens / 1_000_000) * self.output_per_1m,
            8,
        )


@dataclass
class PriceBook:
    """Model pricing, supplied by the deployer.

    Deliberately empty by default. Published rates move often enough that a
    hardcoded table goes stale silently, and a wrong number here becomes a wrong
    number in somebody's grant report. Unpriced calls cost 0.0 and still count
    against token and call ceilings, so budget control works before any rate is set.
    """

    rates: dict[str, ModelRate] = field(default_factory=dict)

    def set(self, model: str, input_per_1m: float, output_per_1m: float) -> PriceBook:
        self.rates[model] = ModelRate(input_per_1m, output_per_1m)
        return self

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        rate = self.rates.get(model)
        return rate.cost(input_tokens, output_tokens) if rate else 0.0

    def knows(self, model: str) -> bool:
        return model in self.rates


@runtime_checkable
class ModelProvider(Protocol):
    """The one seam every model call goes through.

    Swapping Gemini for another model, or for a local one, means writing one class
    that satisfies this protocol. No agent changes.
    """

    name: str
    default_model: str

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> ModelResponse: ...


__all__ = ["ModelProvider", "ModelRate", "ModelResponse", "PriceBook", "scrub_secrets"]
