from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.adapters import adapter_for
from app.models import Decision, ImportResponse, ImportStatus, RecordStatus
from app.repositories.records import IntakeRepository, PersistenceError
from app.services.normalization import NormalizedCandidate, identity_text, normalize_candidate

logger = logging.getLogger(__name__)
HARD_FAILURES = {"missing_source_record_id", "invalid_email", "insufficient_identity_fields", "record_shape_invalid", "record_must_be_json_object"}


class UnsupportedProviderError(ValueError):
    pass


class InvalidEnvelopeError(ValueError):
    pass


class IdempotencyConflictError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_fingerprint(provider: str, payload: Any) -> str:
    canonical = json.dumps({"provider": provider, "payload": payload}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_envelope(payload: Any) -> None:
    if isinstance(payload, dict) and "records" in payload:
        if not isinstance(payload["records"], list):
            raise InvalidEnvelopeError("records must be a list")
    elif not isinstance(payload, (dict, list)):
        raise InvalidEnvelopeError("payload must be a JSON object or list")


def row_to_record(row: Any) -> dict[str, Any]:
    return {"id": row["id"], "source": row["source"], "source_record_id": row["source_record_id"], "email": row["email"], "first_name": row["first_name"], "last_name": row["last_name"], "company_name": row["company_name"], "fingerprint": row["fingerprint"], "status": row["status"], "review_required": bool(row["review_required"]), "review_reasons": _json_list(row["review_reasons"]), "created_at": row["created_at"], "updated_at": row["updated_at"]}


def _json_list(value: Optional[str]) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


class IntakeService:
    def __init__(self, repository: IntakeRepository, max_batch_size: int = 100):
        self.repository = repository
        self.max_batch_size = max_batch_size

    def ingest(self, provider: str, payload: Any, idempotency_key: Optional[str] = None) -> ImportResponse:
        provider = provider.strip().lower()
        try:
            adapter = adapter_for(provider)
        except ValueError as exc:
            raise UnsupportedProviderError("unsupported provider") from exc
        validate_envelope(payload)
        candidates = adapter.parse(payload)
        if len(candidates) > self.max_batch_size:
            raise BatchTooLargeError(f"batch exceeds maximum of {self.max_batch_size} records")
        try:
            fingerprint = request_fingerprint(provider, payload)
        except (TypeError, ValueError) as exc:
            raise InvalidEnvelopeError("payload must contain valid JSON values") from exc
        if idempotency_key:
            prior = self.repository.find_idempotent_job(idempotency_key)
            if prior:
                if prior["provider"] != provider or prior["request_fingerprint"] != fingerprint:
                    raise IdempotencyConflictError("Idempotency-Key was already used for a different request")
                return self._response_for_job(prior["id"], idempotent_replay=True)
        job_id, replay = self.repository.create_import_job(provider, idempotency_key, fingerprint, now_iso())
        if replay:
            prior = self.repository.get_import_job(job_id)
            if not prior or prior["provider"] != provider or prior["request_fingerprint"] != fingerprint:
                raise IdempotencyConflictError("Idempotency-Key was already used for a different request")
            return self._response_for_job(job_id, idempotent_replay=True)

        try:
            with self.repository.transaction():
                counts = {"accepted": 0, "review": 0, "rejected": 0, "duplicates": 0}
                items: list[dict[str, Any]] = []
                for candidate in candidates:
                    normalized = normalize_candidate(candidate)
                    decision, record_id, reasons = self._process_candidate(provider, normalized)
                    counts[_count_key(decision)] += 1
                    self.repository.insert_item(job_id, normalized.source_record_id, decision.value, record_id, reasons, now_iso())
                    items.append({"source_record_id": normalized.source_record_id, "decision": decision, "record_id": record_id, "reasons": reasons})
                import_status = ImportStatus.PARTIAL if counts["review"] or counts["rejected"] else ImportStatus.SUCCEEDED
                self.repository.update_import_job(job_id, {"status": import_status.value, "records_processed": len(candidates), "accepted_count": counts["accepted"], "review_count": counts["review"], "rejected_count": counts["rejected"], "duplicate_count": counts["duplicates"], "completed_at": now_iso()})
            return ImportResponse(import_id=job_id, provider=provider, status=import_status, records_processed=len(candidates), accepted_count=counts["accepted"], review_count=counts["review"], rejected_count=counts["rejected"], duplicate_count=counts["duplicates"], items=items)
        except Exception as exc:
            logger.exception("intake processing failed provider=%s job=%s", provider, job_id)
            self.repository.fail_import_job(job_id, "persistence failure" if isinstance(exc, PersistenceError) else "intake processing failure", now_iso())
            if isinstance(exc, PersistenceError):
                raise
            raise PersistenceError("intake processing failed") from exc

    def _process_candidate(self, provider: str, candidate: NormalizedCandidate) -> tuple[Decision, Optional[str], list[str]]:
        if HARD_FAILURES.intersection(candidate.validation_reasons):
            return Decision.REJECTED, None, candidate.validation_reasons
        if not candidate.source_record_id:
            return Decision.REJECTED, None, ["missing_source_record_id"]
        existing = self.repository.find_by_source_key(provider, candidate.source_record_id)
        if existing:
            return Decision.DUPLICATE, existing["id"], ["same_source_record"]
        matching = self._find_identity_match(candidate)
        if matching[0] == "duplicate":
            return Decision.DUPLICATE, matching[1], [matching[2]]
        if matching[0] == "review":
            reasons = [matching[2]]
            return Decision.REVIEW_REQUIRED, self._persist_review(provider, candidate, reasons), reasons
        if candidate.validation_reasons:
            return Decision.REVIEW_REQUIRED, self._persist_review(provider, candidate, candidate.validation_reasons), candidate.validation_reasons
        if not candidate.email:
            reasons = ["missing_email"]
            return Decision.REVIEW_REQUIRED, self._persist_review(provider, candidate, reasons), reasons
        return Decision.ACCEPTED, self._persist_record(provider, candidate, RecordStatus.ACCEPTED, [], candidate.identity_fingerprint), []

    def _find_identity_match(self, candidate: NormalizedCandidate) -> tuple[str, Optional[str], str]:
        if candidate.email:
            for row in self.repository.find_by_email(candidate.email):
                return "duplicate", row["id"], "normalized_email"
        complete = bool(candidate.first_name and candidate.last_name and candidate.company_name)
        if complete:
            matches = self.repository.find_by_identity(identity_text(candidate.first_name), identity_text(candidate.last_name), identity_text(candidate.company_name))
            for row in matches:
                if not candidate.email and not row["email"]:
                    return "duplicate", row["id"], "exact_name_company_identity"
                if candidate.email and row["email"] and identity_text(row["email"]) != identity_text(candidate.email):
                    return "review", row["id"], "identity_conflict_different_email"
        rows = self.repository.find_partial_identity(identity_text(candidate.first_name), identity_text(candidate.last_name), identity_text(candidate.company_name))
        for row in rows:
            same = sum(bool(identity_text(row[key]) and identity_text(value) and identity_text(row[key]) == identity_text(value)) for key, value in (("first_name", candidate.first_name), ("last_name", candidate.last_name), ("company_name", candidate.company_name)))
            if same >= 2:
                return "review", row["id"], "ambiguous_identity_match"
        return "new", None, ""

    def _persist_review(self, provider: str, candidate: NormalizedCandidate, reasons: list[str]) -> str:
        fingerprint = None if {"ambiguous_identity_match", "identity_conflict_different_email"}.intersection(reasons) else candidate.identity_fingerprint
        return self._persist_record(provider, candidate, RecordStatus.REVIEW_REQUIRED, reasons, fingerprint)

    def _persist_record(self, provider: str, candidate: NormalizedCandidate, status: RecordStatus, reasons: list[str], fingerprint: Optional[str]) -> str:
        timestamp = now_iso()
        return self.repository.insert_record({"source": provider, "source_record_id": candidate.source_record_id, "email": candidate.email, "first_name": candidate.first_name, "last_name": candidate.last_name, "company_name": candidate.company_name, "fingerprint": fingerprint, "status": status.value, "review_required": status == RecordStatus.REVIEW_REQUIRED, "review_reasons": reasons, "created_at": timestamp, "updated_at": timestamp})

    def get_import(self, import_id: str) -> Optional[ImportResponse]:
        return self._response_for_job(import_id, idempotent_replay=False, missing_ok=True)

    def _response_for_job(self, job_id: str, idempotent_replay: bool, missing_ok: bool = False) -> Optional[ImportResponse]:
        job = self.repository.get_import_job(job_id)
        if not job:
            if missing_ok:
                return None
            raise KeyError(job_id)
        items = [{"source_record_id": row["source_record_id"], "decision": row["decision"], "record_id": row["record_id"], "reasons": _json_list(row["reasons"])} for row in self.repository.list_items(job_id)]
        return ImportResponse(import_id=job["id"], provider=job["provider"], status=job["status"], records_processed=job["records_processed"], accepted_count=job["accepted_count"], review_count=job["review_count"], rejected_count=job["rejected_count"], duplicate_count=job["duplicate_count"], idempotent_replay=idempotent_replay, items=items, error=job["error"])


class BatchTooLargeError(ValueError):
    pass


def _count_key(decision: Decision) -> str:
    return {Decision.ACCEPTED: "accepted", Decision.REVIEW_REQUIRED: "review", Decision.REJECTED: "rejected", Decision.DUPLICATE: "duplicates"}[decision]
