from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, Header, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import database_path, max_batch_size
from app.database import connect_database, initialize_database
from app.models import CanonicalRecordResponse, ImportResponse, RecordStatus
from app.repositories.records import IntakeRepository, PersistenceError
from app.services.ingestion import (BatchTooLargeError, IdempotencyConflictError, IntakeService, InvalidEnvelopeError, UnsupportedProviderError, row_to_record)


logging.basicConfig(level=logging.INFO)


def create_app(db_path: Optional[Path] = None) -> FastAPI:
    connection = connect_database(db_path or database_path())
    initialize_database(connection)
    service = IntakeService(IntakeRepository(connection), max_batch_size=max_batch_size())
    app = FastAPI(title="Reliable Data Intake Pipeline", version="1.0.0")
    app.state.connection = connection
    app.state.service = service

    @app.exception_handler(PersistenceError)
    async def persistence_error_handler(_, exc: PersistenceError):
        return JSONResponse(status_code=503, content={"error": "persistence_error", "detail": "intake could not be persisted"})

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict_handler(_, exc: IdempotencyConflictError):
        return JSONResponse(status_code=409, content={"error": "idempotency_conflict", "detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(_, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": "invalid_request", "detail": "request body must be valid JSON"})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/ingest/{provider}", response_model=ImportResponse)
    async def ingest(
        provider: str,
        payload: Any = Body(...),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> ImportResponse:
        if idempotency_key and len(idempotency_key) > 200:
            raise HTTPException(status_code=422, detail="Idempotency-Key must be 200 characters or fewer")
        try:
            result = service.ingest(provider, payload, idempotency_key)
        except UnsupportedProviderError as exc:
            return JSONResponse(status_code=422, content={"error": "unsupported_provider", "detail": str(exc)})
        except InvalidEnvelopeError as exc:
            return JSONResponse(status_code=422, content={"error": "invalid_envelope", "detail": str(exc)})
        except BatchTooLargeError as exc:
            return JSONResponse(status_code=413, content={"error": "batch_too_large", "detail": str(exc)})
        return JSONResponse(
            status_code=status.HTTP_200_OK if result.idempotent_replay else status.HTTP_201_CREATED,
            content=result.model_dump(mode="json"),
        )

    @app.get("/records", response_model=list[CanonicalRecordResponse])
    async def list_records(status_filter: Optional[RecordStatus] = Query(default=None, alias="status")) -> JSONResponse:
        status_value = status_filter.value if status_filter else None
        records = [CanonicalRecordResponse.model_validate(row_to_record(row)).model_dump(mode="json") for row in service.repository.list_records(status_value)]
        return JSONResponse(content=records)

    @app.get("/records/{record_id}", response_model=CanonicalRecordResponse)
    async def get_record(record_id: str) -> JSONResponse:
        row = service.repository.get_record(record_id)
        if not row:
            raise HTTPException(status_code=404, detail="record not found")
        return JSONResponse(content=CanonicalRecordResponse.model_validate(row_to_record(row)).model_dump(mode="json"))

    @app.get("/reviews", response_model=list[CanonicalRecordResponse])
    async def list_reviews() -> JSONResponse:
        records = [CanonicalRecordResponse.model_validate(row_to_record(row)).model_dump(mode="json") for row in service.repository.list_records(RecordStatus.REVIEW_REQUIRED.value)]
        return JSONResponse(content=records)

    @app.get("/imports/{import_id}", response_model=ImportResponse)
    async def get_import(import_id: str) -> JSONResponse:
        result = service.get_import(import_id)
        if not result:
            raise HTTPException(status_code=404, detail="import not found")
        return JSONResponse(content=result.model_dump(mode="json"))

    return app


app = create_app()
