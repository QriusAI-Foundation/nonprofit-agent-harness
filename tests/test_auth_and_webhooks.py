from __future__ import annotations

import time

import jwt
import pytest

from nonprofit_harness.api.routes.webhooks import clear_webhooks, register_webhook, verify_signature
from nonprofit_harness.auth import Principal, SessionTokens, is_admin_email
from nonprofit_harness.core.errors import Unauthorized


@pytest.fixture
def tokens() -> SessionTokens:
    return SessionTokens("test-secret-at-least-32-bytes-long!!", ttl_seconds=60)


def test_a_session_token_round_trips(tokens):
    issued = tokens.issue(Principal(email="asha@example.org", org_id="org_1", is_admin=True))
    principal = tokens.verify(issued)

    assert principal.email == "asha@example.org"
    assert principal.org_id == "org_1"
    assert principal.is_admin is True


def test_a_token_signed_with_another_secret_is_refused(tokens):
    other = SessionTokens("other-secret-at-least-32-bytes-long")
    forged = other.issue(Principal(email="a@b.c", org_id="org_1"))

    with pytest.raises(Unauthorized, match="Invalid session token"):
        tokens.verify(forged)


def test_an_expired_token_is_refused(tokens):
    expired = jwt.encode(
        {
            "iss": "nonprofit-agent-harness",
            "sub": "a@b.c",
            "org": "org_1",
            "iat": int(time.time()) - 100,
            "exp": int(time.time()) - 10,
        },
        "test-secret-at-least-32-bytes-long!!",
        algorithm="HS256",
    )

    with pytest.raises(Unauthorized, match="expired"):
        tokens.verify(expired)


def test_a_secretless_session_signer_is_rejected_at_construction():
    with pytest.raises(ValueError, match="secret is required"):
        SessionTokens("")


def test_the_admin_allowlist_is_exact_and_case_insensitive():
    allowlist = ["Asha@Example.org"]

    assert is_admin_email("asha@example.org", allowlist) is True
    assert is_admin_email("ASHA@EXAMPLE.ORG", allowlist) is True
    assert is_admin_email("asha@evil.org", allowlist) is False
    assert is_admin_email("", allowlist) is False


def test_webhook_signature_verification():
    body = b'{"event":"submitted"}'
    good = __import__("hmac").new(b"shh", body, __import__("hashlib").sha256).hexdigest()

    assert verify_signature("shh", body, good) is True
    assert verify_signature("shh", body, f"sha256={good}") is True
    assert verify_signature("shh", body, "deadbeef") is False


def test_an_unknown_webhook_source_is_acknowledged_not_rejected(client):
    response = client.post("/v1/webhooks/unconfigured", json={"any": "payload"})

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_a_registered_webhook_runs_its_handler(client):
    received = {}

    def handler(payload):
        received.update(payload)
        return {"stored": True}

    register_webhook("intake", handler)
    try:
        response = client.post("/v1/webhooks/intake", json={"org": "org_1"})
        assert response.json()["result"] == {"stored": True}
        assert received == {"org": "org_1"}
    finally:
        clear_webhooks()


def test_a_signed_webhook_refuses_a_bad_signature(client):
    register_webhook("secure", lambda payload: None, secret="shh")
    try:
        response = client.post(
            "/v1/webhooks/secure", json={"a": 1}, headers={"x-signature": "nope"}
        )
        assert response.status_code == 401
    finally:
        clear_webhooks()


def test_a_webhook_can_name_its_own_signature_header(client):
    import hashlib
    import hmac

    body = b'{"a":1}'
    signature = hmac.new(b"shh", body, hashlib.sha256).hexdigest()

    register_webhook("vendor", lambda payload: "ok", secret="shh", signature_header="x-vendor-sig")
    try:
        accepted = client.post(
            "/v1/webhooks/vendor", content=body, headers={"x-vendor-sig": signature}
        )
        assert accepted.status_code == 200

        # The generic headers are not consulted once a specific one is named.
        refused = client.post(
            "/v1/webhooks/vendor", content=body, headers={"x-signature": signature}
        )
        assert refused.status_code == 401
    finally:
        clear_webhooks()
