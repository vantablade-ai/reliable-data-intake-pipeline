from __future__ import annotations

from typing import Any

from .base import ProviderAdapter, ProviderCandidate


class ProviderAlphaAdapter(ProviderAdapter):
    name = "provider_alpha"

    def parse(self, payload: Any) -> list[ProviderCandidate]:
        candidates: list[ProviderCandidate] = []
        for raw in self.records_from_payload(payload):
            if not isinstance(raw, dict):
                candidates.append(self.invalid_candidate(raw))
                continue
            errors: list[str] = []
            candidates.append(
                ProviderCandidate(
                    source_record_id=self.text(raw.get("record_id"), "record_id", errors),
                    email=self.text(raw.get("email"), "email", errors),
                    first_name=self.text(raw.get("first_name"), "first_name", errors),
                    last_name=self.text(raw.get("last_name"), "last_name", errors),
                    company_name=self.text(raw.get("company"), "company", errors),
                    parse_errors=errors,
                )
            )
        return candidates
