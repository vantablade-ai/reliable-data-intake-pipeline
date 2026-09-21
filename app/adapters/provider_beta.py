from __future__ import annotations

from typing import Any

from .base import ProviderAdapter, ProviderCandidate


def split_name(value: Any, errors: list[str]) -> tuple[Any, Any]:
    if value is None:
        return None, None
    if not isinstance(value, str):
        errors.append("invalid_field_type:fullName")
        return None, None
    parts = value.strip().split()
    if not parts:
        return None, None
    return parts[0], " ".join(parts[1:]) or None


class ProviderBetaAdapter(ProviderAdapter):
    name = "provider_beta"

    def parse(self, payload: Any) -> list[ProviderCandidate]:
        candidates: list[ProviderCandidate] = []
        for raw in self.records_from_payload(payload):
            if not isinstance(raw, dict):
                candidates.append(self.invalid_candidate(raw))
                continue
            errors: list[str] = []
            organization = raw.get("organization")
            company = organization.get("name") if isinstance(organization, dict) else organization
            if organization is not None and not isinstance(organization, (dict, str)):
                errors.append("invalid_field_type:organization")
                company = None
            first_name, last_name = split_name(raw.get("fullName"), errors)
            candidates.append(
                ProviderCandidate(
                    source_record_id=self.text(raw.get("contactId"), "contactId", errors),
                    email=self.text(raw.get("contactEmail"), "contactEmail", errors),
                    first_name=first_name,
                    last_name=last_name,
                    company_name=self.text(company, "organization.name", errors),
                    parse_errors=errors,
                )
            )
        return candidates
