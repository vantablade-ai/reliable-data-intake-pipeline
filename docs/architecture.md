# Architecture

## Request lifecycle

1. `POST /ingest/{provider}` receives one JSON object, a list, or an object with a `records` list.
2. The provider registry selects one adapter. Unsupported providers fail before persistence.
3. The adapter maps provider-specific fields into `ProviderCandidate` values. It does not write to the database.
4. Normalization trims text, lowercases email addresses, validates deterministic formats, and records reasons for unsafe input.
5. The intake service checks the source record key, normalized email, and conservative name/company evidence.
6. The repository persists accepted or review-required canonical records and an import-item audit row.
7. The import job is finalized with counts and an explicit status.

## Adapter boundary

Adapters only understand their provider's JSON shape:

- Alpha uses `record_id`, `email`, separate name fields, and `company`.
- Beta uses `contactId`, `contactEmail`, `fullName`, and nested `organization`.
- Gamma uses `ref`, `mail`, `name`, and `org`.

The service never branches on those provider-specific field names. This keeps schema drift local to an adapter and makes another provider a contained addition.

## Canonical model

`canonical_records` stores the normalized application shape: source, source record ID, email, names, company, an identity fingerprint, lifecycle status, review reasons, and timestamps. Raw provider payloads are deliberately not persisted.

The canonical persistence states are:

- `ACCEPTED`: a valid email is sufficient stable identity for this demonstration.
- `REVIEW_REQUIRED`: the record is processable but has missing email, identity conflict, ambiguity, or a non-fatal mapping issue.
- `REJECTED`: the record is not persisted as a canonical record because its source ID, email, or minimum identity evidence is invalid.

Rejected decisions remain visible in the import summary and item audit table without storing the raw payload.

## Dedupe and identity strategy

There are two distinct guarantees:

1. Source replay: `UNIQUE(source, source_record_id)` prevents the same provider record from creating another canonical record.
2. Entity dedupe: normalized email is the strongest cross-provider identity signal. Exact name + company identity can deduplicate records that both lack email. A same-name/company conflict with different emails is review-only, and partial matches are never merged.

The identity fingerprint is SHA-256 over normalized identity values. It is a lookup/deduplication key, not a security credential. Fingerprints are only stored when the identity is sufficiently complete; uncertain review records do not receive a guessed identity key.

## Idempotency

An optional `Idempotency-Key` is unique on `import_jobs`. Replaying the same key returns the original import ID and summary with `idempotent_replay=true`. Without that header, a repeated request may create a new import job, but source and identity uniqueness still prevents duplicate canonical state.

This project treats source records as immutable intake events: a replay does not silently update the existing canonical record. A future system could add an explicit reconciliation/update workflow if source corrections need to be applied.

## Persistence

SQLite is used for zero-friction local execution. `schema.sql` keeps the model relational and includes checks, foreign keys, unique constraints, and indexes. The repository is the only layer that issues SQL, so a PostgreSQL implementation can replace it without changing adapters or normalization rules.

## Failure behavior

- Invalid JSON is rejected by FastAPI with a 422 response.
- Unsupported providers return a controlled 422 response.
- Invalid records become rejected item decisions with safe reasons.
- Database failures are translated into a 503 `persistence_error` response.
- Unexpected processing failures are logged server-side, mark the import failed, and do not expose a traceback to the caller.

## Testing strategy

Tests exercise both the service and HTTP boundary. They cover each adapter, normalization, exact replay, cross-provider duplicate handling, ambiguous identity routing, explicit outcome states, API validation, and repository-backed canonical persistence. All test data is synthetic.
