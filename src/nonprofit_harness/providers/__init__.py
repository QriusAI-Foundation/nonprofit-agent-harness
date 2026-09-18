from nonprofit_harness.providers.base import ModelProvider, ModelRate, ModelResponse, PriceBook
from nonprofit_harness.providers.echo import EchoProvider

__all__ = [
    "EchoProvider",
    "ModelProvider",
    "ModelRate",
    "ModelResponse",
    "PriceBook",
    "load_provider",
]


def load_provider(name: str | None = None, **kwargs):
    """Build a provider by name. Defaults to the offline one so nothing costs money by accident."""
    import os

    chosen = (name or os.getenv("HARNESS_PROVIDER") or "echo").lower()
    if chosen == "echo":
        return EchoProvider()
    if chosen in {"google", "gemini", "adk", "vertex"}:
        from nonprofit_harness.providers.google import GoogleProvider

        return GoogleProvider(**kwargs)

    from nonprofit_harness.core.errors import InvalidRequest

    raise InvalidRequest(f"Unknown provider {chosen!r}. Known: echo, google")
