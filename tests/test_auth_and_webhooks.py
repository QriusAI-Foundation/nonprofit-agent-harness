from __future__ import annotations

import time

import jwt
import pytest

from nonprofit_harness.api.app import create_app
from nonprofit_harness.api.routes.webhooks import clear_webhooks, register_webhook, verify_signature
from nonprofit_harness.auth import GoogleIdentity, Principal, SessionTokens, is_admin_email
from nonprofit_harness.config import HarnessConfig
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


# Authorization over HTTP. The client below runs the real app with auth required and
# two organisations, so every test here is a request a real caller could make.

SECRET = "test-secret-at-least-32-bytes-long!!"
ADMIN = "admin@harness.example"


def _secured_config(**overrides) -> HarnessConfig:
    settings = {
        "provider": "echo",
        "storage": "memory",
        "max_tokens": None,
        "max_calls": None,
        "auth_required": True,
        "google_client_id": "client-123",
        "jwt_secret": SECRET,
        "admin_emails": [ADMIN],
    }
    settings.update(overrides)
    return HarnessConfig(**settings)


@pytest.fixture
def secured(registry, stores, provider):
    from fastapi.testclient import TestClient

    app = create_app(config=_secured_config(), registry=registry, stores=stores, provider=provider)
    return TestClient(app)


def _as(email: str, org_id: str) -> dict[str, str]:
    token = SessionTokens(SECRET).issue(Principal(email=email, org_id=org_id))
    return {"authorization": f"Bearer {token}"}


ORG_A = _as("asha@a.example", "org_a")
ORG_B = _as("bilal@b.example", "org_b")
AS_ADMIN = _as(ADMIN, "org_admin")


def _run_in(client, headers, text="Quarterly programme update.") -> dict:
    response = client.post(
        "/v1/runs",
        json={"agent": "note", "inputs": [{"text": text, "name": "update.txt"}], "sync": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _approved_run_in(client, headers) -> dict:
    run = _run_in(client, headers)
    client.post(f"/v1/review/{run['id']}/approve-all", json={}, headers=headers)
    return run


def test_run_lookup_without_a_token_is_refused_when_auth_is_required(secured):
    run = _run_in(secured, ORG_B)

    response = secured.get(f"/v1/runs/{run['id']}")

    assert response.status_code == 401
    assert "Quarterly" not in response.text


def test_released_output_without_a_token_is_refused_when_auth_is_required(secured):
    run = _approved_run_in(secured, ORG_B)

    response = secured.get(f"/v1/review/{run['id']}/released")

    assert response.status_code == 401
    assert "Quarterly" not in response.text


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        SessionTokens("another-secret-at-least-32-bytes-long").issue(
            Principal(email="bilal@b.example", org_id="org_b")
        ),
    ],
    ids=["garbage", "wrong-secret"],
)
def test_an_invalid_token_cannot_read_output(secured, token):
    run = _approved_run_in(secured, ORG_B)
    headers = {"authorization": f"Bearer {token}"}

    assert secured.get(f"/v1/runs/{run['id']}", headers=headers).status_code == 401
    assert secured.get(f"/v1/review/{run['id']}/released", headers=headers).status_code == 401


def test_an_expired_token_cannot_read_output(secured):
    run = _approved_run_in(secured, ORG_B)
    expired = jwt.encode(
        {
            "iss": "nonprofit-agent-harness",
            "sub": "bilal@b.example",
            "org": "org_b",
            "iat": int(time.time()) - 100,
            "exp": int(time.time()) - 10,
        },
        SECRET,
        algorithm="HS256",
    )
    headers = {"authorization": f"Bearer {expired}"}

    assert secured.get(f"/v1/runs/{run['id']}", headers=headers).status_code == 401
    assert secured.get(f"/v1/review/{run['id']}/released", headers=headers).status_code == 401


def test_a_token_without_an_email_is_not_the_shared_workspace(secured):
    run = _run_in(secured, ORG_B)
    nameless = SessionTokens(SECRET).issue(Principal(email="", org_id="org_a"))

    response = secured.get(f"/v1/runs/{run['id']}", headers={"authorization": f"Bearer {nameless}"})

    assert response.status_code == 401


def test_org_a_cannot_read_org_b_run(secured):
    run = _run_in(secured, ORG_B)

    response = secured.get(f"/v1/runs/{run['id']}", headers=ORG_A)

    # The same answer as a run that does not exist, so the id is not confirmed.
    assert response.status_code == 404
    assert "Quarterly" not in response.text


def test_org_a_cannot_read_org_b_released_output(secured):
    run = _approved_run_in(secured, ORG_B)
    assert secured.get(f"/v1/review/{run['id']}/released", headers=ORG_B).status_code == 200

    response = secured.get(f"/v1/review/{run['id']}/released", headers=ORG_A)

    assert response.status_code == 404
    assert "Quarterly" not in response.text


def test_org_a_cannot_use_org_b_blob_as_input(secured):
    upload = secured.post(
        "/v1/uploads",
        files={"file": ("b-only.txt", b"Org B confidential figures.", "text/plain")},
        headers=ORG_B,
    ).json()

    response = secured.post(
        "/v1/runs",
        json={"agent": "note", "inputs": [{"blob_id": upload["id"]}], "sync": True},
        headers=ORG_A,
    )

    assert response.status_code == 404
    assert "confidential" not in response.text
    assert secured.get("/v1/runs", headers=ORG_A).json() == []


@pytest.mark.parametrize("action", ["approve", "reject", "approve-all"])
def test_org_a_cannot_decide_on_org_b_artifacts(secured, action):
    run = _run_in(secured, ORG_B)
    artifact_id = run["artifacts"][0]["id"]
    path = (
        f"/v1/review/{run['id']}/approve-all"
        if action == "approve-all"
        else f"/v1/review/{run['id']}/artifacts/{artifact_id}/{action}"
    )

    response = secured.post(path, json={"note": "not mine"}, headers=ORG_A)

    assert response.status_code == 404
    still = secured.get(f"/v1/runs/{run['id']}", headers=ORG_B).json()
    assert still["status"] == "awaiting_review"
    assert still["artifacts"][0]["review"] is None


def test_run_creation_cannot_land_in_another_org(secured):
    response = secured.post(
        "/v1/runs",
        json={"agent": "note", "inputs": [{"text": "Planted."}], "org_id": "org_b", "sync": True},
        headers=ORG_A,
    )

    assert response.status_code == 403
    assert secured.get("/v1/runs", headers=ORG_B).json() == []


def test_run_creation_lands_in_the_callers_org(secured):
    run = _run_in(secured, ORG_A)

    assert run["org_id"] == "org_a"


def test_an_admin_can_reach_another_orgs_run(secured):
    run = _run_in(secured, ORG_B)

    assert secured.get(f"/v1/runs/{run['id']}", headers=AS_ADMIN).status_code == 200
    approved = secured.post(f"/v1/review/{run['id']}/approve-all", json={}, headers=AS_ADMIN)
    assert approved.json()["status"] == "completed"


def test_an_admin_claim_in_a_token_does_not_make_an_admin(secured):
    run = _run_in(secured, ORG_B)
    forged = SessionTokens(SECRET).issue(
        Principal(email="asha@a.example", org_id="org_a", is_admin=True)
    )

    response = secured.get(f"/v1/runs/{run['id']}", headers={"authorization": f"Bearer {forged}"})

    assert response.status_code == 404


def test_a_member_completes_intake_to_release(secured):
    upload = secured.post(
        "/v1/uploads",
        files={"file": ("brief.txt", b"A short programme brief.", "text/plain")},
        headers=ORG_A,
    ).json()
    run = secured.post(
        "/v1/runs",
        json={"agent": "note", "inputs": [{"blob_id": upload["id"]}], "sync": True},
        headers=ORG_A,
    ).json()
    run_id, artifact_id = run["id"], run["artifacts"][0]["id"]

    assert secured.get(f"/v1/runs/{run_id}", headers=ORG_A).status_code == 200
    assert [r["id"] for r in secured.get("/v1/review/queue", headers=ORG_A).json()] == [run_id]
    secured.post(
        f"/v1/review/{run_id}/artifacts/{artifact_id}/approve",
        json={"note": "reads well"},
        headers=ORG_A,
    )
    released = secured.get(f"/v1/review/{run_id}/released", headers=ORG_A).json()

    assert released[0]["review"]["reviewer"] == "asha@a.example"


def test_auth_off_local_mode_still_needs_no_token(client):
    created = client.post(
        "/v1/runs",
        json={"agent": "note", "inputs": [{"text": "Local."}], "org_id": "org_x", "sync": True},
    ).json()

    # One shared workspace: no token, any org the caller names, and readable back.
    assert created["org_id"] == "org_x"
    assert client.get(f"/v1/runs/{created['id']}").status_code == 200
    client.post(f"/v1/review/{created['id']}/approve-all", json={})
    assert client.get(f"/v1/review/{created['id']}/released").status_code == 200


# Sign-in. Google is stubbed: what is under test is what the harness does with an
# identity once Google has vouched for it.


@pytest.fixture
def google(monkeypatch):
    def verify(credential, *, client_id):
        return GoogleIdentity(email=credential, email_verified=True, name="Signed In")

    monkeypatch.setattr("nonprofit_harness.api.routes.auth.verify_google_id_token", verify)


def _sign_in(client, email, org_id=None):
    body = {"credential": email}
    if org_id is not None:
        body["org_id"] = org_id
    return client.post("/v1/auth/google", json=body)


def test_sign_in_cannot_choose_an_org_from_the_body(secured, stores, google):
    response = _sign_in(secured, "eve@evil.example", org_id="org_b")

    assert response.status_code == 403
    assert stores.users.get_by_email("eve@evil.example") is None


def test_sign_in_cannot_move_an_enrolled_member(secured, stores, google):
    secured.put("/v1/admin/members/asha@a.example", json={"org_id": "org_a"}, headers=AS_ADMIN)

    response = _sign_in(secured, "asha@a.example", org_id="org_b")

    assert response.status_code == 403
    assert stores.users.get_by_email("asha@a.example").org_id == "org_a"


def test_sign_in_issues_the_membership_on_record(secured, google):
    enrolled = secured.put(
        "/v1/admin/members/Asha@A.example",
        json={"org_id": "org_a", "org_name": "Org A"},
        headers=AS_ADMIN,
    )
    assert enrolled.status_code == 200

    signed_in = _sign_in(secured, "asha@a.example").json()
    matching = _sign_in(secured, "asha@a.example", org_id="org_a")

    assert signed_in["user"]["org_id"] == "org_a"
    assert matching.status_code == 200
    me = secured.get(
        "/v1/auth/me", headers={"authorization": f"Bearer {signed_in['token']}"}
    ).json()
    assert me["org_id"] == "org_a"
    orgs = secured.get("/v1/admin/orgs", headers=AS_ADMIN).json()
    assert {"id": "org_a", "name": "Org A"}.items() <= orgs[0].items()


def test_a_first_sign_in_joins_the_default_org(secured, google):
    body = _sign_in(secured, "new@somewhere.example").json()

    assert body["user"]["org_id"] == "org_default"


def test_a_mixed_case_google_email_is_stored_so_it_is_found_again(secured, stores, google):
    _sign_in(secured, "Asha@A.Example")

    assert stores.users.get_by_email("asha@a.example").email == "asha@a.example"


def test_without_a_default_org_only_enrolled_users_and_admins_sign_in(
    registry, stores, provider, google
):
    from fastapi.testclient import TestClient

    app = create_app(
        config=_secured_config(default_org=""), registry=registry, stores=stores, provider=provider
    )
    closed = TestClient(app)

    assert _sign_in(closed, "stranger@somewhere.example").status_code == 403
    assert _sign_in(closed, ADMIN).status_code == 200


def test_only_an_admin_can_set_membership(secured):
    response = secured.put(
        "/v1/admin/members/asha@a.example", json={"org_id": "org_b"}, headers=ORG_A
    )

    assert response.status_code == 403
