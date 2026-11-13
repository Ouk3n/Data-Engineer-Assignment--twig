from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from .models import JobRecord
from .text import normalize, title_similarity


def _id(company: str, title: str, city: str | None, ordinal: int = 0) -> str:
    base = f"{normalize(company)}|{normalize(title)}|{normalize(city)}|{ordinal}"
    return "job-" + hashlib.sha1(base.encode()).hexdigest()[:16]


def _merge(left: JobRecord, right: JobRecord) -> JobRecord:
    data = left.model_dump()
    for field in ("company", "title", "seniority", "city", "country", "remote_policy", "salary_min", "salary_max", "currency", "employment_type", "visa_sponsorship", "posted_date"):
        if getattr(right, field) is not None and (getattr(left, field) is None or field in {"title", "company"} and len(getattr(right, field)) > len(getattr(left, field))):
            data[field] = getattr(right, field)
    data["skills"] = list(dict.fromkeys([*left.skills, *right.skills]))
    data["source_urls"] = list(dict.fromkeys([*left.source_urls, *right.source_urls]))
    data["evidence"] = {**left.evidence, **right.evidence}
    data["first_seen"] = min(left.first_seen, right.first_seen)
    data["last_seen"] = max(left.last_seen, right.last_seen)
    return JobRecord.model_validate(data)


class Deduplicator:
    def __init__(self):
        self.records: list[JobRecord] = []

    def add(self, candidate: JobRecord) -> JobRecord:
        for index, existing in enumerate(self.records):
            same_company = normalize(existing.company) == normalize(candidate.company)
            same_city = not existing.city or not candidate.city or normalize(existing.city) == normalize(candidate.city)
            same_title = title_similarity(existing.title, candidate.title)
            url_match = bool(set(existing.source_urls) & set(candidate.source_urls))
            if url_match or (same_company and same_city and same_title >= 0.72):
                merged = _merge(existing, candidate)
                self.records[index] = merged
                return merged
        if not candidate.posting_id or candidate.posting_id.startswith("data-"):
            candidate.posting_id = _id(candidate.company, candidate.title, candidate.city)
        self.records.append(candidate)
        return candidate

    def add_all(self, candidates: list[JobRecord]) -> list[JobRecord]:
        return [self.add(candidate) for candidate in candidates]
