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


def test_invalid_records_envelope_is_controlled(client):
    response = client.post("/ingest/provider_alpha", json={"records": "not-a-list"})
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_envelope"


def test_oversized_batch_is_controlled(client):
    response = client.post("/ingest/provider_alpha", json={"records": [{}] * 101})
    assert response.status_code == 413
    assert response.json()["error"] == "batch_too_large"


def test_idempotency_rejects_changed_payload_and_provider(client):
    first_payload = {"record_id": "keyed", "email": "keyed@example.test", "first_name": "K", "last_name": "Person"}
    client.post("/ingest/provider_alpha", json=first_payload, headers={"Idempotency-Key": "same"})
    changed = dict(first_payload, email="other@example.test")
    response = client.post("/ingest/provider_alpha", json=changed, headers={"Idempotency-Key": "same"})
    assert response.status_code == 409
    assert response.json()["error"] == "idempotency_conflict"
    response = client.post("/ingest/provider_beta", json={"contactId": "keyed", "contactEmail": "keyed@example.test", "fullName": "K Person"}, headers={"Idempotency-Key": "same"})
    assert response.status_code == 409


def test_idempotency_ignores_object_key_order(client):
    a = {"record_id": "order", "email": "order@example.test", "first_name": "Order", "last_name": "Person"}
    b = {"last_name": "Person", "first_name": "Order", "email": "order@example.test", "record_id": "order"}
    first = client.post("/ingest/provider_alpha", json=a, headers={"Idempotency-Key": "order"})
    replay = client.post("/ingest/provider_alpha", json=b, headers={"Idempotency-Key": "order"})
    assert replay.status_code == 200
    assert replay.json()["import_id"] == first.json()["import_id"]



def test_openapi_document_is_available(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["version"] == "1.0.0"
