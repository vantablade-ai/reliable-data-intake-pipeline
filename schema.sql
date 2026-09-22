CREATE TABLE IF NOT EXISTS import_jobs (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'partial', 'failed')),
    records_processed INTEGER NOT NULL DEFAULT 0 CHECK (records_processed >= 0),
    accepted_count INTEGER NOT NULL DEFAULT 0 CHECK (accepted_count >= 0),
    review_count INTEGER NOT NULL DEFAULT 0 CHECK (review_count >= 0),
    rejected_count INTEGER NOT NULL DEFAULT 0 CHECK (rejected_count >= 0),
    duplicate_count INTEGER NOT NULL DEFAULT 0 CHECK (duplicate_count >= 0),
    idempotency_key TEXT UNIQUE,
    request_fingerprint TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_import_jobs_provider ON import_jobs(provider);
CREATE INDEX IF NOT EXISTS idx_import_jobs_created_at ON import_jobs(created_at DESC);
CREATE TABLE IF NOT EXISTS canonical_records (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    email TEXT,
    first_name TEXT,
    last_name TEXT,
    company_name TEXT,
    fingerprint TEXT,
    status TEXT NOT NULL CHECK (status IN ('ACCEPTED', 'REVIEW_REQUIRED')),
    review_required INTEGER NOT NULL CHECK (review_required IN (0, 1)),
    review_reasons TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source, source_record_id),
    UNIQUE (fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_canonical_records_status ON canonical_records(status);
CREATE INDEX IF NOT EXISTS idx_canonical_records_email ON canonical_records(email COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_canonical_records_identity ON canonical_records(first_name COLLATE NOCASE, last_name COLLATE NOCASE, company_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_canonical_records_last_name ON canonical_records(last_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_canonical_records_company ON canonical_records(company_name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS import_items (
    id TEXT PRIMARY KEY,
    import_id TEXT NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
    source_record_id TEXT,
    decision TEXT NOT NULL CHECK (decision IN ('ACCEPTED', 'REVIEW_REQUIRED', 'REJECTED', 'DUPLICATE')),
    record_id TEXT REFERENCES canonical_records(id) ON DELETE SET NULL,
    reasons TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_import_items_import_id ON import_items(import_id);
CREATE INDEX IF NOT EXISTS idx_import_items_decision ON import_items(decision);
