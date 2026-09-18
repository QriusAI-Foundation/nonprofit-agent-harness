from nonprofit_harness.providers.base import (
    ModelProvider,
    ModelRate,
    ModelResponse,
    PriceBook,
    scrub_secrets,
)
from nonprofit_harness.providers.echo import EchoProvider

__all__ = [
    "EchoProvider",
    "ModelProvider",
    "ModelRate",
    "ModelResponse",
    "PriceBook",
    "known_providers",
    "load_provider",
    "scrub_secrets",
]

#: Aliases are here because people reach for the vendor name they know. Anything
#: speaking the OpenAI chat API routes to the same adapter with a different base URL.
_ALIASES = {
    "echo": "echo",
    "google": "google",
    "gemini": "google",
    "adk": "google",
    "vertex": "google",
    "openai": "openai",
    "openai-compatible": "openai",
    "groq": "openai",
    "together": "openai",
    "openrouter": "openai",
    "vllm": "openai",
    "ollama": "ollama",
    "local": "ollama",
    "anthropic": "anthropic",
    "claude": "anthropic",
}

#: Servers that speak the OpenAI API but default somewhere other than OpenAI.
_DEFAULT_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
    "local": "http://localhost:11434/v1",
    # Self-hosted, so it must not fall through to OpenAI's public endpoint.
    "vllm": "http://localhost:8000/v1",
}


def known_providers() -> list[str]:
    return sorted(_ALIASES)


def load_provider(name: str | None = None, **kwargs):
    """Build a provider by name. Defaults to the offline one so nothing costs money by accident."""
    import os

    requested = (name or os.getenv("HARNESS_PROVIDER") or "echo").strip().lower()
    resolved = _ALIASES.get(requested)

    if resolved is None:
        from nonprofit_harness.core.errors import InvalidRequest

        raise InvalidRequest(
            f"Unknown provider {requested!r}. Known: {', '.join(known_providers())}"
        )

    if resolved == "echo":
        return EchoProvider()

    if resolved == "google":
        from nonprofit_harness.providers.google import GoogleProvider

        return GoogleProvider(**kwargs)

    if resolved == "anthropic":
        from nonprofit_harness.providers.anthropic import AnthropicProvider

        return AnthropicProvider(**kwargs)

    from nonprofit_harness.providers.openai_compatible import OpenAIProvider

    # A self-hosted server usually ignores the key, but the header still has to exist.
    if requested in {"ollama", "local", "vllm"}:
        kwargs.setdefault("api_key", os.getenv("OPENAI_API_KEY") or "local")
    if requested in _DEFAULT_BASE_URLS:
        kwargs.setdefault("base_url", os.getenv("OPENAI_BASE_URL") or _DEFAULT_BASE_URLS[requested])
    return OpenAIProvider(**kwargs)
