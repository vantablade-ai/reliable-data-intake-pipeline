from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderCandidate:
    source_record_id: Any = None
    email: Any = None
    first_name: Any = None
    last_name: Any = None
    company_name: Any = None
    parse_errors: list[str] = field(default_factory=list)


class ProviderAdapter:
    name: str

    def parse(self, payload: Any) -> list[ProviderCandidate]:
        raise NotImplementedError

    @staticmethod
    def records_from_payload(payload: Any) -> list[Any]:
        if isinstance(payload, dict) and "records" in payload:
            records = payload["records"]
            return records if isinstance(records, list) else [records]
        if isinstance(payload, list):
            return payload
        return [payload]

    @staticmethod
    def text(value: Any, field_name: str, errors: list[str]) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            errors.append(f"invalid_field_type:{field_name}")
            return None
        return value

    @staticmethod
    def invalid_candidate(value: Any) -> ProviderCandidate:
        reason = "record_shape_invalid" if isinstance(value, dict) else "record_must_be_json_object"
        return ProviderCandidate(parse_errors=[reason])
