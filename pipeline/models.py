from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Seniority = Literal["junior", "mid", "senior", "staff_plus"]
RemotePolicy = Literal["onsite", "hybrid", "remote"]
EmploymentType = Literal["full_time", "contract", "intern"]
Status = Literal["open", "closed"]


class JobRecord(BaseModel):
    """Canonical schema stored in SQLite and exported as JSON/CSV."""

    model_config = ConfigDict(extra="ignore")

    posting_id: str
    company: str
    title: str
    seniority: Seniority | None = None
    city: str | None = None
    country: str | None = None
    remote_policy: RemotePolicy | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    currency: str | None = None
    employment_type: EmploymentType | None = None
    skills: list[str] = Field(default_factory=list)
    visa_sponsorship: bool | None = None
    posted_date: date | None = None
    status: Status = "open"
    source_urls: list[str] = Field(default_factory=list)
    evidence: dict[str, str] = Field(default_factory=dict)
    first_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("skills")
    @classmethod
    def dedupe_skills(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for skill in value:
            clean = " ".join(str(skill).split()).strip()
            key = clean.casefold()
            if clean and key not in seen:
                seen.add(key)
                result.append(clean)
        return result


class RawPosting(BaseModel):
    """Source-specific record before extraction and canonicalization."""

    model_config = ConfigDict(extra="allow")

    source: Literal["greenhouse", "lever", "hacker_news"]
    source_id: str
    source_url: str
    company: str | None = None
    title: str | None = None
    location_text: str | None = None
    description_html: str | None = None
    description_text: str = ""
    posted_date: date | None = None
    status: Status = "open"
    raw: dict[str, Any] = Field(default_factory=dict)


class RunMetrics(BaseModel):
    started_at: datetime
    finished_at: datetime | None = None
    fetched: int = 0
    parsed: int = 0
    filtered: int = 0
    extracted: int = 0
    stored: int = 0
    failures: int = 0
    llm_calls: int = 0
    llm_cost_usd: float = 0.0
    estimated_llm_cost_usd: float = 0.0
    llm_provider: str = "heuristic"
    llm_warning: str | None = None
    source_counts: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


def jsonable(model: BaseModel) -> dict[str, Any]:
    """Serialize a Pydantic model using JSON-compatible primitives."""

    return model.model_dump(mode="json")
