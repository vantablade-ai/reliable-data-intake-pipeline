from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.adapters import adapter_for
from app.models import Decision, ImportResponse, ImportStatus, RecordStatus
from app.repositories.records import IntakeRepository, PersistenceError
from app.services.normalization import NormalizedCandidate, identity_text, normalize_candidate


logger = logging.getLogger(__name__)


class UnsupportedProviderError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def row_to_record(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"], "source": row["source"], "source_record_id": row["source_record_id"],
        "email": row["email"], "first_name": row["first_name"], "last_name": row["last_name"],
        "company_name": row["company_name"], "fingerprint": row["fingerprint"],
        "status": row["status"], "review_required": bool(row["review_required"]),
        "review_reasons": _json_list(row["review_reasons"]),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _json_list(value: Optional[str]) -> list[str]:
    try:
        parsed = __import__("json").loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


class IntakeService:
    def __init__(self, repository: IntakeRepository):
        self.repository = repository

    def ingest(self, provider: str, payload: Any, idempotency_key: Optional[str] = None) -> ImportResponse:
        provider = provider.strip().lower()
        try:
            adapter = adapter_for(provider)
        except ValueError as exc:
            raise UnsupportedProviderError("unsupported provider") from exc

        job_id, replay = self.repository.create_import_job(provider, idempotency_key, now_iso())
        if replay:
            return self._response_for_job(job_id, idempotent_replay=True)

        try:
            candidates = adapter.parse(payload)
            counts = {"accepted": 0, "review": 0, "rejected": 0, "duplicates": 0}
            items: list[dict[str, Any]] = []
            for candidate in candidates:
                normalized = normalize_candidate(candidate)
                decision, record_id, reasons = self._process_candidate(provider, normalized)
                counts[_count_key(decision)] += 1
                self.repository.insert_item(job_id, normalized.source_record_id, decision.value, record_id, reasons, now_iso())
                items.append({
                    "source_record_id": normalized.source_record_id,
                    "decision": decision,
                    "record_id": record_id,
                    "reasons": reasons,
                })

            status = ImportStatus.PARTIAL if counts["review"] or counts["rejected"] else ImportStatus.SUCCEEDED
            self.repository.update_import_job(job_id, {
                "status": status.value,
                "records_processed": len(candidates),
                "accepted_count": counts["accepted"],
                "review_count": counts["review"],
                "rejected_count": counts["rejected"],
                "duplicate_count": counts["duplicates"],
                "completed_at": now_iso(),
            })
            return ImportResponse(
                import_id=job_id, provider=provider, status=status,
                records_processed=len(candidates), accepted_count=counts["accepted"],
                review_count=counts["review"], rejected_count=counts["rejected"],
                duplicate_count=counts["duplicates"], items=items,
            )
        except PersistenceError:
            self.repository.update_import_job(job_id, {
                "status": ImportStatus.FAILED.value,
                "error": "persistence failure",
                "completed_at": now_iso(),
            })
            raise
        except Exception:
            logger.exception("unexpected intake failure for provider=%s job=%s", provider, job_id)
            self.repository.update_import_job(job_id, {
                "status": ImportStatus.FAILED.value,
                "error": "intake processing failure",
                "completed_at": now_iso(),
            })
            raise

    def _process_candidate(self, provider: str, candidate: NormalizedCandidate) -> tuple[Decision, Optional[str], list[str]]:
        if candidate.validation_reasons:
            hard_failures = {"missing_source_record_id", "invalid_email", "insufficient_identity_fields", "record_shape_invalid", "record_must_be_json_object"}
            if hard_failures.intersection(candidate.validation_reasons):
                return Decision.REJECTED, None, candidate.validation_reasons
            return Decision.REVIEW_REQUIRED, self._persist_review(provider, candidate, candidate.validation_reasons), candidate.validation_reasons

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

        if not candidate.email:
            reasons = ["missing_email"]
            return Decision.REVIEW_REQUIRED, self._persist_review(provider, candidate, reasons), reasons

        record_id = self._persist_record(provider, candidate, RecordStatus.ACCEPTED, [], candidate.identity_fingerprint)
        return Decision.ACCEPTED, record_id, []

    def _find_identity_match(self, candidate: NormalizedCandidate) -> tuple[str, Optional[str], str]:
        for row in self.repository.list_records():
            row_email = identity_text(row["email"])
            candidate_email = identity_text(candidate.email)
            same_email = bool(candidate_email and row_email and candidate_email == row_email)
            same_full_identity = all(
                identity_text(row[key]) and identity_text(candidate_value) and identity_text(row[key]) == identity_text(candidate_value)
                for key, candidate_value in (
                    ("first_name", candidate.first_name),
                    ("last_name", candidate.last_name),
                    ("company_name", candidate.company_name),
                )
            )
            same_name_company = all(
                identity_text(row[key]) and identity_text(candidate_value) and identity_text(row[key]) == identity_text(candidate_value)
                for key, candidate_value in (("first_name", candidate.first_name), ("last_name", candidate.last_name), ("company_name", candidate.company_name))
            )
            matching_name_parts = sum(
                bool(identity_text(row[key]) and identity_text(candidate_value) and identity_text(row[key]) == identity_text(candidate_value))
                for key, candidate_value in (("first_name", candidate.first_name), ("last_name", candidate.last_name), ("company_name", candidate.company_name))
            )
            if same_email:
                return "duplicate", row["id"], "normalized_email"
            if same_full_identity and not candidate.email and not row_email:
                return "duplicate", row["id"], "exact_name_company_identity"
            if same_name_company and candidate.email and row_email and candidate_email != row_email:
                return "review", row["id"], "identity_conflict_different_email"
            if matching_name_parts >= 2:
                return "review", row["id"], "ambiguous_identity_match"
        return "new", None, ""

    def _persist_review(self, provider: str, candidate: NormalizedCandidate, reasons: list[str]) -> Optional[str]:
        fingerprint = None
        if not any(reason in {"ambiguous_identity_match", "identity_conflict_different_email"} for reason in reasons):
            fingerprint = candidate.identity_fingerprint
        return self._persist_record(provider, candidate, RecordStatus.REVIEW_REQUIRED, reasons, fingerprint)

    def _persist_record(self, provider: str, candidate: NormalizedCandidate, status: RecordStatus, reasons: list[str], fingerprint: Optional[str]) -> str:
        timestamp = now_iso()
        record_id, inserted = self.repository.insert_record({
            "source": provider,
            "source_record_id": candidate.source_record_id,
            "email": candidate.email,
            "first_name": candidate.first_name,
            "last_name": candidate.last_name,
            "company_name": candidate.company_name,
            "fingerprint": fingerprint,
            "status": status.value,
            "review_required": status == RecordStatus.REVIEW_REQUIRED,
            "review_reasons": reasons,
            "created_at": timestamp,
            "updated_at": timestamp,
        })
        if inserted and record_id:
            return record_id
        existing = self.repository.find_by_source_key(provider, candidate.source_record_id or "")
        return existing["id"] if existing else ""

    def get_import(self, import_id: str) -> Optional[ImportResponse]:
        return self._response_for_job(import_id, idempotent_replay=False, missing_ok=True)

    def _response_for_job(self, job_id: str, idempotent_replay: bool, missing_ok: bool = False) -> Optional[ImportResponse]:
        job = self.repository.get_import_job(job_id)
        if not job:
            if missing_ok:
                return None
            raise KeyError(job_id)
        items = []
        for row in self.repository.list_items(job_id):
            items.append({
                "source_record_id": row["source_record_id"],
                "decision": row["decision"],
                "record_id": row["record_id"],
                "reasons": _json_list(row["reasons"]),
            })
        return ImportResponse(
            import_id=job["id"], provider=job["provider"], status=job["status"],
            records_processed=job["records_processed"], accepted_count=job["accepted_count"],
            review_count=job["review_count"], rejected_count=job["rejected_count"],
            duplicate_count=job["duplicate_count"], idempotent_replay=idempotent_replay,
            items=items, error=job["error"],
        )


def _count_key(decision: Decision) -> str:
    return {Decision.ACCEPTED: "accepted", Decision.REVIEW_REQUIRED: "review", Decision.REJECTED: "rejected", Decision.DUPLICATE: "duplicates"}[decision]


def _json_list(value: Optional[str]) -> list[str]:
    import json
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []
