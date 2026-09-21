# Reliable Data Intake Pipeline

A FastAPI integration pipeline for turning inconsistent third-party JSON into validated, normalized, duplicate-safe application records.

This synthetic project demonstrates backend patterns at the boundary between external API/webhook payloads and an internal system: provider adapters, input validation, canonical normalization, conservative identity matching, idempotent intake, review routing, and relational persistence.

The fictional system receives contact records from three synthetic providers. Each provider uses a different JSON shape. The intake boundary keeps provider-specific mapping inside adapters, applies deterministic validation and normalization, resolves identity conservatively, and records an explicit outcome:

- `ACCEPTED` — enough stable identity data exists for automatic persistence.
- `REVIEW_REQUIRED` — the record is processable, but incomplete or conflicting.
- `REJECTED` — the record cannot be safely processed.
- `DUPLICATE` — the source key or normalized identity already exists, so the existing record is reused.

## The business problem

External systems rarely describe the same entity in exactly the same way. Field names differ, optional values are blank or malformed, events are replayed, and two records may look similar without being the same person. Passing those inconsistencies directly into downstream systems creates duplicates and silently invented data.

This project shows a small, self-contained intake boundary for that problem: provider-specific payloads are converted into one canonical shape, checked for safe processing, deduplicated using conservative identity evidence, and routed to an explicit outcome instead of being silently dropped or guessed.

## Architecture

```text
Provider Alpha / Beta / Gamma
              |
              v
        FastAPI intake
              |
              v
       Provider adapter
              |
              v
      Candidate validation
              |
              v
    Canonical normalization
              |
              v
    Identity + fingerprinting
              |
       +------+------+
       |             |
       v             v
    Accepted     Review queue
       |             |
       +------+------+
              v
       SQLite repository
       (PostgreSQL-shaped schema)
              |
              v
        Import summary
```

## Validation and normalization

Each adapter maps its provider’s fields into a `ProviderCandidate`. The shared normalization step then:

- trims and collapses whitespace in text fields;
- case-folds email addresses for comparison and storage;
- validates the source record ID, email shape, and minimum name identity;
- preserves non-fatal mapping issues as review reasons; and
- creates a SHA-256 identity fingerprint only when the email or full name/company identity is complete.

Raw provider payloads are not persisted. The import item audit row stores the source ID, decision, canonical record ID when available, and safe reason codes.

## Deduplication and idempotency

The pipeline has separate protections for source replay and entity deduplication:

- `UNIQUE(source, source_record_id)` prevents one provider record from creating multiple canonical records.
- A normalized email is the strongest cross-provider identity signal.
- Exact name/company identity can deduplicate records that both lack email.
- Same-name/company records with different emails, and partial matches, go to review rather than being merged.
- An optional `Idempotency-Key` returns the original import summary and import ID on replay; it does not create a second import job.

## Routing outcomes

Every item receives one explicit decision:

- `ACCEPTED`: valid email identity is available and no conflicting match exists; the canonical record is persisted.
- `REVIEW_REQUIRED`: the record is processable but needs human or downstream review, such as a missing email, non-fatal mapping issue, ambiguity, or identity conflict; a review-state record is persisted.
- `REJECTED`: required source identity, email validity, minimum identity evidence, or JSON object shape is unsafe; no canonical record is persisted, but the decision remains in the import summary and item table.
- `DUPLICATE`: the source key or normalized identity already exists; the existing canonical record is returned and no new one is created.

The `/reviews` endpoint lists review-state canonical records.

## Example

Provider Alpha:

```json
{
  "record_id": "alpha-1001",
  "email": "  Riley@example.test ",
  "first_name": " Riley ",
  "last_name": " Chen",
  "company": "Northstar Labs"
}
```

Provider Beta represents the same contact differently:

```json
{
  "contactId": "beta-2207",
  "contactEmail": "RILEY@EXAMPLE.TEST",
  "fullName": "Riley Chen",
  "organization": {"name": "Northstar Labs"}
}
```

Both normalize to the same email identity. The second intake is recorded as a duplicate and does not create another canonical record. A record with only a partial name or a conflicting identity is persisted in `REVIEW_REQUIRED` state instead of being merged on a guess.

## Engineering decisions

### Provider isolation

Provider-specific field names and shape handling live in `app/adapters/`. The rest of the pipeline consumes one `ProviderCandidate` shape.

### Deterministic before AI

This demonstration intentionally uses deterministic transformations for known mappings, validation, normalization, and identity matching. There is no AI dependency in the intake path.

### Explicit uncertainty

Missing email, incomplete identity fields, and conflicting matches produce review reasons. The pipeline does not fabricate missing values or aggressively merge similar records.

### Idempotent ingestion

The database enforces uniqueness on `(source, source_record_id)`. An optional `Idempotency-Key` replays the same import summary without creating another import job. Cross-provider duplicates are detected by normalized identity evidence.

### Database guarantees

The local demo uses SQLite so it runs without a hosted account. `schema.sql` uses standard relational tables, constraints, indexes, and a JSON column shape that can be adapted to PostgreSQL. The repository isolates database access from the service layer.

## API usage

Start the server and open `/docs` for generated OpenAPI documentation.

```text
POST /ingest/{provider}
GET  /records
GET  /records/{id}
GET  /reviews
GET  /imports/{id}
GET  /health
```

Example request:

```bash
curl -X POST http://127.0.0.1:8000/ingest/provider_alpha \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-alpha-1001' \
  --data @examples/provider_alpha.json
```

Use `provider_beta`, `provider_gamma`, or a JSON array for a small batch. The API also accepts `{ "records": [...] }`. Example payloads are in `examples/`.

An import response reports the import ID, status, item decisions, counts, and safe reason codes. `GET /imports/{id}` returns the persisted summary. Records are available through `/records`; filter them with `?status=ACCEPTED` or `?status=REVIEW_REQUIRED`.

Malformed JSON and unsupported providers return controlled `422` responses. Missing resources return `404`; database failures return `503`.

## Running locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The default database is `data/intake.db`. Set `DATABASE_PATH` to use another local path. No external service or credential is required.

## Tests and validation

```bash
pytest -q
```

The test suite covers provider mapping, normalization, malformed and missing fields, accepted/review/rejected routing, exact replay, cross-provider deduplication, conservative ambiguity handling, API errors, and persistence. The project has no external service dependency for its tests; each test uses an isolated temporary SQLite database.

## What this demonstrates

- Python backend structure and type hints
- FastAPI REST/webhook-style intake
- Pydantic response contracts
- Provider adapter boundaries
- JSON schema variation handling
- Canonical data modeling
- Deterministic normalization
- Conservative identity matching
- Fingerprints, uniqueness, and idempotency
- Explicit review and rejection states
- Relational persistence abstraction
- Controlled error responses
- Automated tests for workflow invariants

## Limitations

This is a synthetic demonstration project. It contains no client data, production credentials, real provider payloads, or proprietary application code. SQLite is used for zero-friction local execution; `schema.sql` is relational and PostgreSQL-shaped, but a production deployment would still need a production database, migrations, connection pooling, and operational backups. The identity rules are intentionally conservative and deterministic: they do not resolve every ambiguous person, update existing records from later source corrections, or replace a human review workflow. Authentication, authorization, rate limiting, queue-backed asynchronous processing, monitoring, and deployment configuration are outside this example’s scope.
