from __future__ import annotations

import math
import os
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

    def __post_init__(self) -> None:
        # NaN never compares greater than a ceiling and a negative rate subtracts
        # spend, so either one would quietly switch the cost ceiling off.
        for rate in (self.input_per_1m, self.output_per_1m):
            if not math.isfinite(rate) or rate < 0:
                raise ValueError(f"A model rate must be a finite number of 0 or more, not {rate}")

    @property
    def free(self) -> bool:
        return self.input_per_1m == 0 and self.output_per_1m == 0

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return round(
            (input_tokens / 1_000_000) * self.input_per_1m
            + (output_tokens / 1_000_000) * self.output_per_1m,
            8,
        )


#: Where a deployment states its prices without writing code. Read by every provider
#: that takes a `prices=` argument, when none is passed.
PRICES_ENV = "HARNESS_PRICES"


@dataclass
class PriceBook:
    """Model pricing, supplied by the deployer.

    Deliberately empty by default. Published rates move often enough that a
    hardcoded table goes stale silently, and a wrong number here becomes a wrong
    number in somebody's grant report. A call on a model the book does not know is
    recorded as unpriced, never as free: it still counts against token and call
    ceilings, and a dollar ceiling refuses it, because a ceiling that sees zero spend
    cannot stop anything.
    """

    rates: dict[str, ModelRate] = field(default_factory=dict)

    def set(self, model: str, input_per_1m: float, output_per_1m: float) -> PriceBook:
        self.rates[model] = ModelRate(input_per_1m, output_per_1m)
        return self

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float | None:
        """The cost in USD, or None when this book has no rate for the model."""
        rate = self.rates.get(model)
        return rate.cost(input_tokens, output_tokens) if rate else None

    def knows(self, model: str) -> bool:
        return model in self.rates

    def rate_for(self, model: str) -> ModelRate | None:
        return self.rates.get(model)

    def usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        *,
        requested: str | None = None,
    ) -> Usage:
        """Cost one call by the model the API says answered it.

        Priced by the returned name rather than the requested one, because that is the
        model that was billed. When they differ and only the requested name has a rate,
        the call is unpriced and the note says so: borrowing the requested rate would
        cost a dated snapshot or a fallback model at somebody else's price.
        """
        cost = self.cost(model, input_tokens, output_tokens)
        if cost is not None:
            return Usage(
                input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost, calls=1
            )
        note = model
        if requested and requested != model and self.knows(requested):
            note = f"{model} (requested {requested}, which is priced)"
        return Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            calls=1,
            unpriced_calls=1,
            unpriced_models=(note,),
        )

    @classmethod
    def parse(cls, text: str) -> PriceBook:
        """Read `model=input/output` pairs, comma separated, rates in USD per 1M tokens.

        Split on the last `=` and the last `/`, because model names carry `/` and `:`
        (`meta-llama/llama-4`, `llama3:8b`) and a rate never does.
        """
        book = cls()
        for entry in (item.strip() for item in text.split(",")):
            if not entry:
                continue
            model, sep, rates = entry.rpartition("=")
            input_rate, slash, output_rate = rates.rpartition("/")
            try:
                if not (sep and slash and model.strip()):
                    raise ValueError
                book.set(model.strip(), float(input_rate), float(output_rate))
            except ValueError:
                raise ValueError(
                    f"{PRICES_ENV} entry {entry!r} is not model=input/output with finite "
                    "rates of 0 or more, for example my-model=0.30/2.50"
                ) from None
        return book

    @classmethod
    def from_env(cls) -> PriceBook:
        return cls.parse(os.getenv(PRICES_ENV, ""))


def how_to_price(model: str) -> str:
    """The fix, spelled out, for any message that reports a missing price."""
    return (
        f"Set {PRICES_ENV}='{model}=<input>/<output>' (USD per 1M tokens), or pass "
        f"prices=PriceBook().set({model!r}, input_per_1m=..., output_per_1m=...) "
        "to the provider"
    )


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


__all__ = [
    "PRICES_ENV",
    "ModelProvider",
    "ModelRate",
    "ModelResponse",
    "PriceBook",
    "how_to_price",
    "scrub_secrets",
]
