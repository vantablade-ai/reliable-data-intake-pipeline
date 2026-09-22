# Architecture notes

## API boundary

`POST /ingest/{provider}` accepts a JSON object, a list, or an object whose `records` member is a list. Provider selection and envelope validation happen before creating an import job. Batches are limited to 100 candidates by default; `MAX_BATCH_SIZE` configures the bound. Malformed JSON and invalid envelopes return 422; oversized batches return 413. The API translates expected domain and persistence failures into controlled responses.

## Adapter and canonical boundaries

The adapter registry selects Alpha, Beta, or Gamma. Adapters own provider field names, nested organization/name handling, and parse-time field type reasons. They return `ProviderCandidate`; downstream code does not branch on provider-specific fields. Normalization trims and collapses whitespace, case-folds email for comparison/storage, and validates source ID, email syntax, and minimum name identity. Raw payloads are never stored.

## Decisions and uncertainty

Hard invalidity is rejected first. The service next checks source replay, then targeted identity evidence, then non-fatal mapping reasons and missing email. Valid known duplicates therefore win over soft mapping issues. Outcomes are explicit: `ACCEPTED`, `REVIEW_REQUIRED`, `REJECTED`, or `DUPLICATE`.

Source replay is a lookup by `(source, source_record_id)`. Entity matching uses indexed queries for normalized email, exact first/last/company, and candidates sharing any of at least two supplied identity components. Exact name/company with no email on either row is a duplicate. The same full identity with conflicting non-empty emails requires review. Partial overlap with no safe equality proof also requires review. The service interprets returned candidates; no probabilistic matching is used.

The SHA-256 identity fingerprint is based on normalized email or complete normalized first/last/company identity. It is a deterministic uniqueness aid, not a security token. Uncertain conflict/ambiguity reviews omit it so persistence cannot imply a merge.

## Idempotency

The service hashes canonical JSON containing provider and payload, serialized with sorted object keys and compact separators. This makes JSON object key order irrelevant. The import job stores the digest and optional unique `Idempotency-Key`, not the request body. Same key and digest returns the original persisted summary; a changed provider or digest raises an idempotency conflict and creates no new job. The HTTP response is 409.

## Persistence and transaction boundary

SQLite is the only executed persistence backend. `IntakeRepository.transaction()` wraps canonical record writes, import-item audit writes, and final import counts/status. Repository write methods inside it do not commit independently. A newly created job is committed before processing so it remains observable. Processing failure rolls back the processing transaction; `fail_import_job` then records `failed` and a safe error in a separate transaction. The API maps persistence failures to 503 without exposing SQLite details.

The schema uses relational constraints and indexes, including unique source identity and fingerprint, plus targeted identity lookup indexes. PostgreSQL itself is not executed by this repository; portability is limited to conventional relational design choices rather than a tested backend claim.

## Failure behavior

- Malformed JSON, unsupported providers, and invalid envelopes: 422.
- Oversized batches: 413 before import/canonical writes.
- Missing resources: 404.
- Idempotency mismatch: 409.
- Record-level hard invalidity: persisted as a rejected import item without a canonical record.
- Persistence failure: processing rollback, observable failed job, safe 503 response.
- Unexpected processing exceptions are logged server-side, rolled back, and exposed as a generic persistence failure boundary.

## Test strategy

Tests use temporary SQLite databases and in-process `httpx.ASGITransport`; no server, credentials, network, or external account is needed. They cover each adapter and outcome, normalization, source replay, cross-provider deduplication, conflicting/ambiguous identity, request hashing/replay/conflict, batch boundaries, resource errors, and rollback with a preserved failed job. The one-process-per-request harness was removed because it provided no required isolation; per-test temporary databases provide isolation directly.

## Known limitations

Provider schemas are synthetic and fixed. Matching is conservative and deterministic, not fuzzy. There is no update/reconciliation workflow for changed source data, authentication, authorization, rate limiting, async queue, migration framework, production observability, or PostgreSQL runtime. The default local SQLite database is for demonstration use.
