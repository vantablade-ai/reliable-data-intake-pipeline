from __future__ import annotations


def test_unsupported_provider_is_controlled(client):
    response = client.post("/ingest/unknown_provider", json={"id": "x"})
    assert response.status_code == 422
    assert response.json()["detail"] == "unsupported provider"


def test_malformed_json_is_controlled(client):
    response = client.post(
        "/ingest/provider_alpha",
        content='{"record_id":',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"


def test_import_and_record_lookup(client):
    response = client.post("/ingest/provider_alpha", json={
        "record_id": "lookup-1",
        "email": "lookup@example.test",
        "first_name": "Lookup",
        "last_name": "Person",
        "company": "Example Co",
    })
    import_id = response.json()["import_id"]
    record_id = response.json()["items"][0]["record_id"]
    assert client.get(f"/imports/{import_id}").status_code == 200
    assert client.get(f"/records/{record_id}").json()["status"] == "ACCEPTED"
    assert client.get("/records", params={"status": "REVIEW_REQUIRED"}).json() == []


def test_unknown_resource_returns_404(client):
    assert client.get("/records/not-a-record").status_code == 404
    assert client.get("/imports/not-an-import").status_code == 404
