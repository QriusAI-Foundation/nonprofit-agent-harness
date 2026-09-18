from __future__ import annotations

import pytest

from nonprofit_harness.config import HarnessConfig


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in list(dict(__import__("os").environ)):
        if key.startswith("HARNESS_"):
            monkeypatch.delenv(key, raising=False)


def test_defaults_are_offline_free_and_reviewed():
    config = HarnessConfig.from_env()

    assert config.provider == "echo"
    assert config.storage == "memory"
    assert config.auth_required is False
    assert config.redact_inputs is False


def test_a_zero_ceiling_means_zero_not_the_default(monkeypatch):
    monkeypatch.setenv("HARNESS_MAX_CALLS", "0")
    monkeypatch.setenv("HARNESS_MAX_TOKENS", "0")

    config = HarnessConfig.from_env()

    assert config.max_calls == 0
    assert config.max_tokens == 0


def test_a_zero_call_ceiling_actually_stops_a_run(runner, documents):
    runner.config.max_calls = 0
    run = runner.start("note", org_id="org_1", inputs=documents)

    assert run.status == "failed"
    assert run.usage.calls == 0


def test_a_ceiling_can_be_switched_off_explicitly(monkeypatch):
    monkeypatch.setenv("HARNESS_MAX_TOKENS", "unlimited")
    monkeypatch.setenv("HARNESS_MAX_CALLS", "none")

    config = HarnessConfig.from_env()

    assert config.max_tokens is None
    assert config.max_calls is None


def test_validate_warns_when_nothing_caps_a_run():
    config = HarnessConfig(max_cost_usd=None, max_tokens=None, max_calls=None)

    assert any("without limit" in problem for problem in config.validate())


def test_validate_warns_about_half_configured_auth():
    config = HarnessConfig(auth_required=True)
    problems = config.validate()

    assert any("GOOGLE_CLIENT_ID" in p for p in problems)
    assert any("JWT_SECRET" in p for p in problems)


def test_validate_warns_when_gcp_storage_has_no_bucket():
    config = HarnessConfig(storage="gcp", documents_bucket=None)

    assert any("DOCUMENTS_BUCKET" in p for p in config.validate())


def test_admin_emails_parse_from_a_comma_list(monkeypatch):
    monkeypatch.setenv("HARNESS_ADMIN_EMAILS", "a@x.org, b@y.org ,")

    assert HarnessConfig.from_env().admin_emails == ["a@x.org", "b@y.org"]
