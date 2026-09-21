from __future__ import annotations

from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class RecordStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ImportStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class Decision(StrEnum):
    ACCEPTED = "ACCEPTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REJECTED = "REJECTED"
    DUPLICATE = "DUPLICATE"


class CanonicalRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    source_record_id: str
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    fingerprint: Optional[str] = None
    status: RecordStatus
    review_required: bool
    review_reasons: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ImportItemResponse(BaseModel):
    source_record_id: Optional[str] = None
    decision: Decision
    record_id: Optional[str] = None
    reasons: list[str] = Field(default_factory=list)


class ImportResponse(BaseModel):
    import_id: str
    provider: str
    status: ImportStatus
    records_processed: int
    accepted_count: int
    review_count: int
    rejected_count: int
    duplicate_count: int
    idempotent_replay: bool = False
    items: list[ImportItemResponse] = Field(default_factory=list)
    error: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    detail: str
