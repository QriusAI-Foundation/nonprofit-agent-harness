from __future__ import annotations


def test_healthz_reports_what_is_wired_up(client):
    body = client.get("/healthz").json()

    assert body["status"] == "ok"
    assert body["provider"] == "echo"
    assert body["storage"] == "memory"


def test_agents_are_listed_with_their_review_policy(client):
    agents = {a["name"]: a for a in client.get("/v1/agents").json()}

    assert agents["note"]["requires_review"] is True
    assert agents["open"]["requires_review"] is False


def test_a_run_goes_through_review_end_to_end(client):
    created = client.post(
        "/v1/runs",
        json={
            "agent": "note",
            "inputs": [{"text": "Quarterly programme update.", "name": "update.txt"}],
            "sync": True,
        },
    )
    assert created.status_code == 200
    run = created.json()
    assert run["status"] == "awaiting_review"
    assert run["pending_review"] == 1

    run_id = run["id"]
    artifact_id = run["artifacts"][0]["id"]

    blocked = client.get(f"/v1/review/{run_id}/released")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "review_required"

    queue = client.get("/v1/review/queue").json()
    assert [r["id"] for r in queue] == [run_id]

    approved = client.post(
        f"/v1/review/{run_id}/artifacts/{artifact_id}/approve", json={"note": "reads well"}
    ).json()
    assert approved["status"] == "completed"

    released = client.get(f"/v1/review/{run_id}/released").json()
    assert len(released) == 1
    assert released[0]["review"]["note"] == "reads well"


def test_an_async_run_is_accepted_with_202(client):
    response = client.post(
        "/v1/runs",
        json={"agent": "note", "inputs": [{"text": "Body text.", "name": "a.txt"}]},
    )

    assert response.status_code == 202
    run_id = response.json()["id"]
    # TestClient drains background tasks before returning, so the run has finished.
    assert client.get(f"/v1/runs/{run_id}").json()["status"] == "awaiting_review"


def test_a_run_needs_at_least_one_input(client):
    response = client.post("/v1/runs", json={"agent": "note", "inputs": [], "sync": True})

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"


def test_an_unknown_agent_is_a_404(client):
    response = client.post(
        "/v1/runs",
        json={"agent": "nope", "inputs": [{"text": "x"}], "sync": True},
    )

    assert response.status_code == 404


def test_an_unknown_run_is_a_404(client):
    assert client.get("/v1/runs/run_missing").status_code == 404


def test_uploading_a_file_then_running_against_it(client):
    upload = client.post(
        "/v1/uploads",
        files={"file": ("brief.txt", b"A short programme brief.", "text/plain")},
    )
    assert upload.status_code == 201
    blob = upload.json()
    assert blob["characters"] == len("A short programme brief.")

    run = client.post(
        "/v1/runs",
        json={"agent": "note", "inputs": [{"blob_id": blob["id"]}], "sync": True},
    ).json()

    assert run["artifacts"][0]["title"] == "Note on brief.txt"


def test_an_empty_upload_is_rejected(client):
    response = client.post("/v1/uploads", files={"file": ("empty.txt", b"", "text/plain")})

    assert response.status_code == 400


def test_readiness_scoring_over_http(client):
    instrument = client.get("/v1/readiness/instrument").json()
    assert instrument["id"] == "example-readiness"

    scored = client.post(
        "/v1/readiness/score",
        json={
            "answers": {
                "d1": "integrated_system",
                "d2": "adopted",
                "d3": 5,
                "p1": ["writes_reports", "manages_spreadsheets", "builds_dashboards"],
                "p2": "regularly",
                "p3": "planned_annually",
            }
        },
    ).json()

    assert scored["overall"] == 1.0
    assert scored["tier"] == "High"


def test_admin_config_never_echoes_a_secret(client):
    body = client.get("/v1/admin/config").json()

    assert set(body) >= {"provider", "storage", "budget", "warnings"}
    assert "jwt_secret" not in body
    assert body["jwt_secret_set"] is False


def test_me_reports_an_anonymous_caller_when_auth_is_off(client):
    body = client.get("/v1/auth/me").json()

    assert body["anonymous"] is True
    assert body["org_id"] == "org_default"
