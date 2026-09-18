"""Provider adapters, exercised against recorded responses rather than live APIs.

The suite must stay offline, so every test here drives a fake HTTP client shaped like
the real vendor responses.
"""

from __future__ import annotations

import pytest

from nonprofit_harness.core.errors import InvalidRequest, ProviderError
from nonprofit_harness.providers import known_providers, load_provider
from nonprofit_harness.providers.anthropic import AnthropicProvider
from nonprofit_harness.providers.base import PriceBook, scrub_secrets
from nonprofit_harness.providers.openai_compatible import OpenAIProvider

OPENAI_BODY = {
    "model": "gpt-test",
    "choices": [{"message": {"role": "assistant", "content": "A short brief."}}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 45},
}

ANTHROPIC_BODY = {
    "model": "claude-test",
    "content": [{"type": "text", "text": "A short brief."}],
    "usage": {"input_tokens": 120, "output_tokens": 45},
}


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeHttp:
    def __init__(self, *responses):
        self._responses = list(responses) or [FakeResponse(OPENAI_BODY)]
        self.calls: list[dict] = []

    def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]


# --- OpenAI-compatible --------------------------------------------------------------


def test_it_builds_a_chat_completion_and_reads_the_reply():
    http = FakeHttp()
    provider = OpenAIProvider(model="gpt-test", api_key="sk-test-key-value", client=http)

    response = provider.generate("Summarise this.", system="Be brief.")

    assert response.text == "A short brief."
    call = http.calls[0]
    assert call["url"] == "https://api.openai.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-test-key-value"
    assert call["json"]["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Summarise this."},
    ]


def test_usage_is_recorded_so_budget_ceilings_apply():
    provider = OpenAIProvider(model="gpt-test", api_key="sk-test-key-value", client=FakeHttp())

    usage = provider.generate("x").usage

    assert usage.input_tokens == 120
    assert usage.output_tokens == 45
    assert usage.calls == 1


def test_a_price_book_turns_tokens_into_cost():
    prices = PriceBook().set("gpt-test", input_per_1m=1000.0, output_per_1m=2000.0)
    provider = OpenAIProvider(
        model="gpt-test", api_key="sk-test-key-value", client=FakeHttp(), prices=prices
    )

    # 120 in at $1000/1M = $0.12, 45 out at $2000/1M = $0.09
    assert provider.generate("x").usage.cost_usd == pytest.approx(0.21)


def test_a_system_prompt_is_optional():
    http = FakeHttp()
    OpenAIProvider(model="m", api_key="sk-test-key-value", client=http).generate("x")

    assert http.calls[0]["json"]["messages"] == [{"role": "user", "content": "x"}]


def test_a_json_schema_becomes_a_response_format():
    http = FakeHttp()
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}

    OpenAIProvider(model="m", api_key="sk-test-key-value", client=http).generate(
        "x", json_schema=schema
    )

    fmt = http.calls[0]["json"]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["schema"] == schema


def test_a_missing_model_is_a_clear_error_not_a_vendor_404():
    provider = OpenAIProvider(api_key="sk-test-key-value", client=FakeHttp())

    with pytest.raises(InvalidRequest, match="needs a model"):
        provider.generate("x")


def test_a_missing_key_is_reported_before_any_request():
    http = FakeHttp()
    provider = OpenAIProvider(model="m", api_key=None, client=http)
    provider._api_key = None

    with pytest.raises(ProviderError, match="No API key"):
        provider.generate("x")
    assert http.calls == []


def test_a_base_url_points_the_same_adapter_at_another_server():
    http = FakeHttp()
    provider = OpenAIProvider(
        model="llama", api_key="ollama", base_url="http://localhost:11434/v1", client=http
    )

    provider.generate("x")

    assert http.calls[0]["url"] == "http://localhost:11434/v1/chat/completions"


def test_an_empty_choice_list_yields_empty_text_rather_than_an_index_error():
    http = FakeHttp(FakeResponse({"choices": [], "usage": {}}))

    provider = OpenAIProvider(model="m", api_key="sk-test-key-value", client=http)

    assert provider.generate("x").text == ""


# --- Anthropic ----------------------------------------------------------------------


def test_the_messages_api_shape_is_used():
    http = FakeHttp(FakeResponse(ANTHROPIC_BODY))
    provider = AnthropicProvider(api_key="sk-ant-test-value", client=http)

    response = provider.generate("Summarise this.", system="Be brief.")

    assert response.text == "A short brief."
    call = http.calls[0]
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["headers"]["x-api-key"] == "sk-ant-test-value"
    assert call["headers"]["anthropic-version"] == "2023-06-01"
    assert call["json"]["system"] == "Be brief."
    assert call["json"]["messages"] == [{"role": "user", "content": "Summarise this."}]


def test_max_tokens_is_always_sent_because_the_api_requires_it():
    http = FakeHttp(FakeResponse(ANTHROPIC_BODY))

    AnthropicProvider(api_key="sk-ant-test-value", client=http).generate("x")

    assert http.calls[0]["json"]["max_tokens"] > 0


def test_several_text_blocks_are_joined():
    body = {**ANTHROPIC_BODY, "content": [
        {"type": "text", "text": "One. "},
        {"type": "thinking", "text": "ignored"},
        {"type": "text", "text": "Two."},
    ]}
    http = FakeHttp(FakeResponse(body))

    text = AnthropicProvider(api_key="sk-ant-test-value", client=http).generate("x").text

    assert text == "One. Two."


def test_a_schema_is_requested_in_the_system_prompt():
    """The Messages API has no response_format, so this is asked for, not enforced."""
    http = FakeHttp(FakeResponse(ANTHROPIC_BODY))

    AnthropicProvider(api_key="sk-ant-test-value", client=http).generate(
        "x", json_schema={"type": "object"}
    )

    system = http.calls[0]["json"]["system"]
    assert "JSON only" in system
    assert '"type":"object"' in system
    assert "response_format" not in http.calls[0]["json"]


def test_anthropic_usage_is_recorded():
    http = FakeHttp(FakeResponse(ANTHROPIC_BODY))

    usage = AnthropicProvider(api_key="sk-ant-test-value", client=http).generate("x").usage

    assert (usage.input_tokens, usage.output_tokens) == (120, 45)


# --- shared HTTP behaviour ----------------------------------------------------------


def test_a_rate_limit_is_retried_then_succeeds():
    http = FakeHttp(
        FakeResponse({"error": "slow down"}, status_code=429, headers={"retry-after": "0"}),
        FakeResponse(OPENAI_BODY),
    )

    response = OpenAIProvider(model="m", api_key="sk-test-key-value", client=http).generate("x")

    assert response.text == "A short brief."
    assert len(http.calls) == 2


def test_a_client_error_is_not_retried():
    """It fails the same way twice and spends the budget doing it."""
    http = FakeHttp(FakeResponse({"error": "bad request"}, status_code=400))

    with pytest.raises(ProviderError, match="HTTP 400"):
        OpenAIProvider(model="m", api_key="sk-test-key-value", client=http).generate("x")

    assert len(http.calls) == 1


def test_retries_are_bounded():
    http = FakeHttp(FakeResponse({"e": "busy"}, status_code=503, headers={"retry-after": "0"}))

    with pytest.raises(ProviderError, match="HTTP 503"):
        OpenAIProvider(model="m", api_key="sk-test-key-value", client=http).generate("x")

    assert len(http.calls) <= 6


def test_a_transport_failure_becomes_a_provider_error():
    class Broken:
        def post(self, *a, **k):
            raise OSError("connection refused")

    with pytest.raises(ProviderError, match="connection refused"):
        OpenAIProvider(model="m", api_key="sk-test-key-value", client=Broken()).generate("x")


def test_a_non_json_success_is_a_failure_not_a_crash():
    http = FakeHttp(FakeResponse(ValueError("not json")))

    with pytest.raises(ProviderError, match="unreadable JSON"):
        OpenAIProvider(model="m", api_key="sk-test-key-value", client=http).generate("x")


def test_a_key_echoed_by_the_provider_is_scrubbed_from_the_error():
    """Every adapter runs error text through the same scrubber, not just Google's."""
    secret = "sk-test-0123456789abcdef"
    http = FakeHttp(FakeResponse({"error": f"invalid key {secret}"}, status_code=401))

    with pytest.raises(ProviderError) as caught:
        OpenAIProvider(model="m", api_key=secret, client=http).generate("x")

    assert secret not in str(caught.value)
    assert "[redacted]" in str(caught.value)


def test_the_scrubber_is_shared_rather_than_per_provider():
    from nonprofit_harness.providers.google import scrub_secrets as from_google

    assert from_google is scrub_secrets


# --- the registry -------------------------------------------------------------------


def test_offline_is_still_the_default():
    assert type(load_provider()).__name__ == "EchoProvider"


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("openai", "OpenAIProvider"),
        ("groq", "OpenAIProvider"),
        ("together", "OpenAIProvider"),
        ("openrouter", "OpenAIProvider"),
        ("ollama", "OpenAIProvider"),
        ("local", "OpenAIProvider"),
        ("vllm", "OpenAIProvider"),
        ("anthropic", "AnthropicProvider"),
        ("claude", "AnthropicProvider"),
    ],
)
def test_vendor_aliases_resolve(alias, expected, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder-for-construction")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder-for-construction")

    assert type(load_provider(alias)).__name__ == expected


@pytest.mark.parametrize(
    ("alias", "host"),
    [
        ("groq", "api.groq.com"),
        ("openrouter", "openrouter.ai"),
        ("ollama", "localhost:11434"),
        ("vllm", "localhost:8000"),
    ],
)
def test_each_vendor_gets_its_own_endpoint(alias, host, monkeypatch):
    """A self-hosted alias must never fall through to a public endpoint."""
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder-for-construction")

    assert host in load_provider(alias).base_url


def test_a_self_hosted_alias_supplies_a_placeholder_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert load_provider("ollama")._api_key


def test_an_unknown_provider_lists_what_is_available():
    with pytest.raises(InvalidRequest) as caught:
        load_provider("gpt5-turbo-ultra")

    assert "anthropic" in str(caught.value)
    assert "ollama" in str(caught.value)


def test_the_provider_list_is_reported():
    names = known_providers()

    assert {"echo", "google", "openai", "anthropic", "ollama"} <= set(names)
