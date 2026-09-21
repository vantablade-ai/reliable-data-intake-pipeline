from __future__ import annotations

from typing import Any

from .base import ProviderAdapter, ProviderCandidate
from .provider_beta import split_name


class ProviderGammaAdapter(ProviderAdapter):
    name = "provider_gamma"

    def parse(self, payload: Any) -> list[ProviderCandidate]:
        candidates: list[ProviderCandidate] = []
        for raw in self.records_from_payload(payload):
            if not isinstance(raw, dict):
                candidates.append(self.invalid_candidate(raw))
                continue
            errors: list[str] = []
            person = raw.get("person")
            person = person if isinstance(person, dict) else raw
            name_value = person.get("name")
            first_name, last_name = split_name(name_value, errors)
            organization = raw.get("org")
            if isinstance(organization, dict):
                organization = organization.get("label") or organization.get("name")
            elif organization is not None and not isinstance(organization, str):
                errors.append("invalid_field_type:org")
                organization = None
            candidates.append(
                ProviderCandidate(
                    source_record_id=self.text(raw.get("ref"), "ref", errors),
                    email=self.text(raw.get("mail"), "mail", errors),
                    first_name=first_name,
                    last_name=last_name,
                    company_name=self.text(organization, "org", errors),
                    parse_errors=errors,
                )
            )
        return candidates
