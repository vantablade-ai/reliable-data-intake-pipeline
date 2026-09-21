from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional
from uuid import uuid4


class PersistenceError(RuntimeError):
    """A safe boundary for database errors exposed to the service layer."""


class IntakeRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create_import_job(self, provider: str, idempotency_key: Optional[str], created_at: str) -> tuple[str, bool]:
        if idempotency_key:
            existing = self.connection.execute(
                "SELECT id FROM import_jobs WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing:
                return str(existing["id"]), True
        job_id = str(uuid4())
        try:
            self.connection.execute(
                """INSERT INTO import_jobs
                   (id, provider, status, idempotency_key, created_at)
                   VALUES (?, ?, 'running', ?, ?)""",
                (job_id, provider, idempotency_key, created_at),
            )
            self.connection.commit()
            return job_id, False
        except sqlite3.IntegrityError:
            if idempotency_key:
                existing = self.connection.execute(
                    "SELECT id FROM import_jobs WHERE idempotency_key = ?", (idempotency_key,)
                ).fetchone()
                if existing:
                    return str(existing["id"]), True
            raise PersistenceError("could not create import job")

    def update_import_job(self, job_id: str, values: dict[str, Any]) -> None:
        allowed = {
            "status", "records_processed", "accepted_count", "review_count",
            "rejected_count", "duplicate_count", "error", "completed_at",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{key} = ?" for key in updates)
        try:
            self.connection.execute(
                f"UPDATE import_jobs SET {assignments} WHERE id = ?",
                (*updates.values(), job_id),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise PersistenceError("could not update import job") from exc

    def get_import_job(self, job_id: str) -> Optional[sqlite3.Row]:
        return self.connection.execute("SELECT * FROM import_jobs WHERE id = ?", (job_id,)).fetchone()

    def insert_record(self, values: dict[str, Any]) -> tuple[Optional[str], bool]:
        record_id = str(uuid4())
        try:
            cursor = self.connection.execute(
                """INSERT OR IGNORE INTO canonical_records
                   (id, source, source_record_id, email, first_name, last_name,
                    company_name, fingerprint, status, review_required,
                    review_reasons, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record_id, values["source"], values["source_record_id"], values.get("email"),
                    values.get("first_name"), values.get("last_name"), values.get("company_name"),
                    values.get("fingerprint"), values["status"], int(values["review_required"]),
                    json.dumps(values.get("review_reasons", [])), values["created_at"], values["updated_at"],
                ),
            )
            self.connection.commit()
            return (record_id, True) if cursor.rowcount == 1 else (None, False)
        except sqlite3.DatabaseError as exc:
            raise PersistenceError("could not persist canonical record") from exc

    def find_by_source_key(self, source: str, source_record_id: str) -> Optional[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM canonical_records WHERE source = ? AND source_record_id = ?",
            (source, source_record_id),
        ).fetchone()

    def find_by_fingerprint(self, fingerprint: str) -> Optional[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM canonical_records WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()

    def list_records(self, status: Optional[str] = None) -> list[sqlite3.Row]:
        if status:
            return list(self.connection.execute(
                "SELECT * FROM canonical_records WHERE status = ? ORDER BY created_at DESC", (status,)
            ))
        return list(self.connection.execute("SELECT * FROM canonical_records ORDER BY created_at DESC"))

    def get_record(self, record_id: str) -> Optional[sqlite3.Row]:
        return self.connection.execute("SELECT * FROM canonical_records WHERE id = ?", (record_id,)).fetchone()

    def insert_item(self, import_id: str, source_record_id: Optional[str], decision: str, record_id: Optional[str], reasons: list[str], created_at: str) -> None:
        try:
            self.connection.execute(
                """INSERT INTO import_items
                   (id, import_id, source_record_id, decision, record_id, reasons, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), import_id, source_record_id, decision, record_id, json.dumps(reasons), created_at),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise PersistenceError("could not persist import item") from exc

    def list_items(self, import_id: str) -> list[sqlite3.Row]:
        return list(self.connection.execute(
            "SELECT source_record_id, decision, record_id, reasons FROM import_items WHERE import_id = ? ORDER BY rowid",
            (import_id,),
        ))
