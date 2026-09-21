from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional

from app.adapters.base import ProviderCandidate


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class NormalizedCandidate:
    source_record_id: Optional[str]
    email: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    company_name: Optional[str]
    identity_fingerprint: Optional[str]
    validation_reasons: list[str] = field(default_factory=list)


def clean_text(value: object) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().split())
    return normalized or None


def normalize_email(value: object) -> Optional[str]:
    normalized = clean_text(value)
    return normalized.casefold() if normalized else None


def identity_text(value: Optional[str]) -> Optional[str]:
    return value.casefold() if value else None


def valid_email(value: Optional[str]) -> bool:
    return bool(value and EMAIL_PATTERN.fullmatch(value))


def identity_fingerprint(email: Optional[str], first_name: Optional[str], last_name: Optional[str], company_name: Optional[str]) -> Optional[str]:
    if email:
        basis = f"email:{email}"
    elif first_name and last_name and company_name:
        basis = "identity:" + "|".join(
            identity_text(item) or "" for item in (first_name, last_name, company_name)
        )
    else:
        return None
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def normalize_candidate(candidate: ProviderCandidate) -> NormalizedCandidate:
    source_id = clean_text(candidate.source_record_id)
    email = normalize_email(candidate.email)
    first_name = clean_text(candidate.first_name)
    last_name = clean_text(candidate.last_name)
    company_name = clean_text(candidate.company_name)
    reasons = list(candidate.parse_errors)

    if not source_id:
        reasons.append("missing_source_record_id")
    if email and not valid_email(email):
        reasons.append("invalid_email")
    if not email and not (first_name and last_name):
        reasons.append("insufficient_identity_fields")

    return NormalizedCandidate(
        source_record_id=source_id,
        email=email,
        first_name=first_name,
        last_name=last_name,
        company_name=company_name,
        identity_fingerprint=identity_fingerprint(email, first_name, last_name, company_name),
        validation_reasons=list(dict.fromkeys(reasons)),
    )
