from __future__ import annotations

from app.services.normalization import normalize_candidate
from app.adapters.base import ProviderCandidate


def alpha_record(**overrides):
    record = {
        "record_id": "alpha-1",
        "email": "person@example.test",
        "first_name": "Person",
        "last_name": "Example",
        "company": "Example Labs",
    }
    record.update(overrides)
    return record


def test_valid_provider_alpha_record(client):
    response = client.post("/ingest/provider_alpha", json=alpha_record())
    assert response.status_code == 201
    body = response.json()
    assert body["accepted_count"] == 1
    assert body["status"] == "succeeded"
    records = client.get("/records").json()
    assert len(records) == 1
    assert records[0]["email"] == "person@example.test"


def test_valid_provider_beta_record(client):
    response = client.post("/ingest/provider_beta", json={
        "contactId": "beta-1",
        "contactEmail": "BETA@EXAMPLE.TEST",
        "fullName": "Beta Person",
        "organization": {"name": "Example Labs"},
    })
    assert response.status_code == 201
    assert response.json()["accepted_count"] == 1


def test_provider_gamma_variation_routes_missing_email_to_review(client):
    response = client.post("/ingest/provider_gamma", json={
        "ref": "gamma-1",
        "mail": "",
        "name": "Morgan Lee",
        "org": "Orbit Works",
        "metadata": {"unrelated": True},
    })
    assert response.status_code == 201
    body = response.json()
    assert body["review_count"] == 1
    assert body["items"][0]["reasons"] == ["missing_email"]
    assert len(client.get("/reviews").json()) == 1


def test_malformed_record_is_rejected(client):
    response = client.post("/ingest/provider_alpha", json=alpha_record(email="not-an-email"))
    assert response.status_code == 201
    body = response.json()
    assert body["rejected_count"] == 1
    assert body["items"][0]["decision"] == "REJECTED"
    assert client.get("/records").json() == []


def test_missing_required_source_id_is_rejected(client):
    response = client.post("/ingest/provider_alpha", json=alpha_record(record_id=None))
    assert response.status_code == 201
    assert "missing_source_record_id" in response.json()["items"][0]["reasons"]


def test_normalization_is_deterministic():
    candidate = normalize_candidate(ProviderCandidate(
        source_record_id=" x ", email="  PERSON@Example.Test ", first_name="  Pat ", last_name=" Doe ", company_name=" Example  Labs ",
    ))
    assert candidate.source_record_id == "x"
    assert candidate.email == "person@example.test"
    assert candidate.first_name == "Pat"
    assert candidate.company_name == "Example Labs"
    assert candidate.validation_reasons == []


def test_exact_repeat_does_not_create_duplicate_canonical_record(client):
    first = client.post("/ingest/provider_alpha", json=alpha_record())
    second = client.post("/ingest/provider_alpha", json=alpha_record())
    assert first.json()["accepted_count"] == 1
    assert second.json()["duplicate_count"] == 1
    assert second.json()["items"][0]["reasons"] == ["same_source_record"]
    assert len(client.get("/records").json()) == 1


def test_cross_provider_duplicate_uses_normalized_email(client):
    client.post("/ingest/provider_alpha", json=alpha_record())
    response = client.post("/ingest/provider_beta", json={
        "contactId": "beta-duplicate",
        "contactEmail": "PERSON@EXAMPLE.TEST",
        "fullName": "Person Example",
        "organization": {"name": "Example Labs"},
    })
    assert response.json()["duplicate_count"] == 1
    assert len(client.get("/records").json()) == 1


def test_similar_but_conflicting_identity_requires_review(client):
    client.post("/ingest/provider_alpha", json=alpha_record(
        email="first@example.test", first_name="Jordan", last_name="Lee", company="Orbit Works"
    ))
    response = client.post("/ingest/provider_beta", json={
        "contactId": "beta-conflict",
        "contactEmail": "second@example.test",
        "fullName": "Jordan Lee",
        "organization": {"name": "Orbit Works"},
    })
    assert response.json()["review_count"] == 1
    assert response.json()["items"][0]["reasons"] == ["identity_conflict_different_email"]
    assert len(client.get("/records").json()) == 2


def test_ambiguous_partial_match_is_not_merged(client):
    client.post("/ingest/provider_alpha", json=alpha_record(
        email="known@example.test", first_name="Avery", last_name="Stone", company="Known Co"
    ))
    response = client.post("/ingest/provider_gamma", json={
        "ref": "gamma-ambiguous",
        "mail": "new@example.test",
        "name": "Avery Stone",
        "org": "Different Co",
    })
    assert response.json()["review_count"] == 1
    assert response.json()["items"][0]["reasons"] == ["ambiguous_identity_match"]


def test_idempotency_key_replays_original_import(client):
    payload = alpha_record(record_id="alpha-idempotent")
    first = client.post("/ingest/provider_alpha", json=payload, headers={"Idempotency-Key": "request-1"})
    second = client.post("/ingest/provider_alpha", json=payload, headers={"Idempotency-Key": "request-1"})
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert second.json()["import_id"] == first.json()["import_id"]
    assert len(client.get("/records").json()) == 1


def test_batch_contains_accepted_review_and_rejected_items(client):
    response = client.post("/ingest/provider_gamma", json={"records": [
        {"ref": "g-accepted", "mail": "ok@example.test", "name": "Ok Person", "org": "Example Co"},
        {"ref": "g-review", "mail": "", "name": "Review Person", "org": "Example Co"},
        {"ref": "g-rejected", "mail": "broken", "name": "Bad Person", "org": "Example Co"},
    ]})
    body = response.json()
    assert body["accepted_count"] == 1
    assert body["review_count"] == 1
    assert body["rejected_count"] == 1
    assert body["status"] == "partial"


def test_duplicate_identity_precedes_nonfatal_mapping_issue(client):
    client.post("/ingest/provider_alpha", json=alpha_record())
    response = client.post("/ingest/provider_alpha", json=alpha_record(record_id="alpha-2", first_name=12))
    item = response.json()["items"][0]
    assert item["decision"] == "DUPLICATE"
    assert item["record_id"]
    assert len(client.get("/records").json()) == 1


def test_processing_failure_rolls_back_items_and_records_and_keeps_failed_job(app, client, monkeypatch):
    repository = app.state.service.repository
    original = repository.insert_item
    calls = 0

    def failing_insert(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise __import__("app.repositories.records", fromlist=["PersistenceError"]).PersistenceError("test fault")
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, "insert_item", failing_insert)
    response = client.post("/ingest/provider_alpha", json={"records": [alpha_record(record_id="tx-1"), alpha_record(record_id="tx-2", email="second@example.test")]})
    assert response.status_code == 503
    jobs = list(app.state.connection.execute("SELECT id, status FROM import_jobs"))
    assert len(jobs) == 1 and jobs[0]["status"] == "failed"
    assert app.state.connection.execute("SELECT COUNT(*) FROM canonical_records").fetchone()[0] == 0
    assert app.state.connection.execute("SELECT COUNT(*) FROM import_items").fetchone()[0] == 0
    assert client.get(f"/imports/{jobs[0]['id']}").json()["status"] == "failed"
    monkeypatch.setattr(repository, "insert_item", original)


def test_unique_conflict_raises_persistence_error_not_empty_id(client, app):
    from app.repositories.records import PersistenceError

    service = app.state.service
    payload = alpha_record(record_id="unique-1")
    first = client.post("/ingest/provider_alpha", json=payload)
    existing_id = first.json()["items"][0]["record_id"]
    candidate = normalize_candidate(ProviderCandidate(source_record_id="unique-2", email=payload["email"], first_name=payload["first_name"], last_name=payload["last_name"], company_name=payload["company"]))
    # A direct conflicting insert must be explicit; normal service flow resolves it as DUPLICATE.
    from app.models import RecordStatus
    try:
        service._persist_record("provider_alpha", candidate, RecordStatus.ACCEPTED, [], candidate.identity_fingerprint)
    except PersistenceError:
        pass
    else:
        raise AssertionError("unique fingerprint collision was not surfaced")
    assert existing_id
