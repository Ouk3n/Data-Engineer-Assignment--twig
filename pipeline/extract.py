from __future__ import annotations

import json
import os
import re
import getpass
import sys
from datetime import datetime, timezone
from typing import Any

from .models import JobRecord, RawPosting
from .costs import rates_for
from .text import first_sentence, html_to_text


SKILL_PATTERNS = [
    "Python", "SQL", "Spark", "PySpark", "Kafka", "Airflow", "dbt", "Snowflake", "BigQuery",
    "Databricks", "AWS", "GCP", "Azure", "Kubernetes", "Terraform", "Flink", "Scala", "Java",
    "Go", "Docker", "PostgreSQL", "Redshift", "MLflow", "Pandas", "TensorFlow", "PyTorch",
    "TypeScript", "JavaScript", "React", "GraphQL", "Node.js", "Yarn", "HTML", "CSS",
]


def _evidence(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.I)
    if not match:
        return None
    start = max(0, match.start() - 100)
    end = min(len(text), match.end() + 180)
    return first_sentence(text[start:end], 280)


def _location(raw: RawPosting, text: str) -> tuple[str | None, str | None, str | None, dict[str, str]]:
    location = raw.location_text or ""
    evidence: dict[str, str] = {}
    remote: str | None = None
    location_and_text = location + " " + text
    if re.search(r"fully remote|remote[- ]first|remote eligible|us[- ]remote|remote in the us|work from anywhere in the us|work remotely", location_and_text, re.I):
        remote = "remote"
        evidence["remote_policy"] = _evidence(location_and_text, r"fully remote|remote[- ]first|remote eligible|us[- ]remote|remote in the us|work from anywhere|work remotely") or location
    elif re.search(r"hybrid", location_and_text, re.I):
        remote = "hybrid"
        evidence["remote_policy"] = _evidence(location_and_text, r"hybrid") or location
    elif re.search(r"on[- ]site|in office", location_and_text, re.I):
        remote = "onsite"
        evidence["remote_policy"] = _evidence(location_and_text, r"on[- ]site|in office") or location

    country = "US" if re.search(r"\b(?:US|USA|U\.S\.?|United States|NYC|New York|San Francisco|Seattle|Austin|Boston|Chicago|Denver|Los Angeles|Washington,? DC)\b|\b(?:CA|NY|WA|TX|MA|IL|CO|GA|VA|MD|OR|FL|NC|NJ|PA)\b", location, re.I) else None
    city = None
    if location and not remote and not re.fullmatch(r"(?:US|USA|U\.S\.?|United States)", location.strip(), re.I):
        city = re.split(r"[,|]", location)[0].strip() or None
    return city, country, remote, evidence


def _salary(text: str) -> tuple[float | None, float | None, str | None, dict[str, str]]:
    amount = r"(?:[$€£]\s*)?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,6})(?:\.[0-9]+)?\s*[kK]?"
    range_pattern = re.compile(rf"(?P<left>{amount})\s*(?:-|to|–|—)\s*(?P<right>{amount})\s*(?P<currency>USD|CAD|EUR|GBP|dollars?)?", re.I)
    matches = list(range_pattern.finditer(text))
    match = next((item for item in matches if "$" in item.group(0) or item.group("currency")), None)
    if match is None:
        context_pattern = re.compile(rf"(?:salary|compensation|base pay|pay range)[^$€£\d]{{0,80}}(?P<amount>{amount})\s*(?P<currency>USD|CAD|EUR|GBP|dollars?)?", re.I)
        match = context_pattern.search(text)
        if match is None:
            return None, None, None, {}
        low = _parse_amount(match.group("amount"))
        high = None
        currency = match.group("currency")
    else:
        low = _parse_amount(match.group("left"))
        high = _parse_amount(match.group("right"))
        currency = match.group("currency")
    snippet = first_sentence(text[max(0, match.start() - 100):match.end() + 100])
    currency = currency.upper() if currency else ("USD" if "$" in snippet else None)
    return low, high, currency, {"salary_min": snippet, "salary_max": snippet, "currency": snippet}


def _parse_amount(value: str) -> float:
    clean = value.replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
    multiplier = 1000 if clean.casefold().endswith("k") else 1
    return float(clean.rstrip("kK")) * multiplier


def _parse_amount_fixed(value: str) -> float:
    clean = value.replace(",", "").replace("$", "").replace("\u20ac", "").replace("\u00a3", "").strip()
    multiplier = 1000 if clean.casefold().endswith("k") else 1
    return float(clean.rstrip("kK")) * multiplier


def _salary_fixed(text: str) -> tuple[float | None, float | None, str | None, dict[str, str]]:
    amount = r"(?:[$\u20ac\u00a3]\s*)?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,6}|[0-9]{1,3}(?=\s*[kK]))(?:\.[0-9]+)?\s*[kK]?"
    range_pattern = re.compile(rf"(?P<left>{amount})\s*(?:-|to|\u2013|\u2014)\s*(?P<right>{amount})\s*(?P<currency>USD|CAD|EUR|GBP|dollars?)?", re.I)
    match = next((item for item in range_pattern.finditer(text) if "$" in item.group(0) or item.group("currency")), None)
    if match is not None:
        low = _parse_amount_fixed(match.group("left"))
        high = _parse_amount_fixed(match.group("right"))
        currency = match.group("currency")
    else:
        context_pattern = re.compile(rf"(?:salary|compensation|base pay|pay range)[^$\u20ac\u00a3\d]{{0,80}}(?P<amount>{amount})\s*(?P<currency>USD|CAD|EUR|GBP|dollars?)?", re.I)
        match = context_pattern.search(text)
        if match is None:
            return None, None, None, {}
        low = _parse_amount_fixed(match.group("amount"))
        high = None
        currency = match.group("currency")
    snippet = first_sentence(text[max(0, match.start() - 100):match.end() + 100])
    currency = currency.upper() if currency else ("USD" if "$" in snippet else None)
    return low, high, currency, {"salary_min": snippet, "salary_max": snippet, "currency": snippet}


def _heuristic(raw: RawPosting) -> JobRecord:
    text = " ".join(part for part in [raw.title or "", raw.location_text or "", raw.description_text or html_to_text(raw.description_html)] if part)
    title = raw.title or "Data/ML Engineer"
    company = raw.company or "Unknown"
    seniority = None
    if re.search(r"\b(staff|principal|lead|architect|distinguished)\b", title, re.I):
        seniority = "staff_plus"
    elif re.search(r"\b(senior|sr\.?|iii|iv)\b", title, re.I):
        seniority = "senior"
    elif re.search(r"\b(junior|jr\.?|entry|associate)\b", title, re.I):
        seniority = "junior"
    else:
        seniority = None
    evidence: dict[str, str] = {}
    for field, pattern in [("title", re.escape(title)), ("company", re.escape(company)), ("seniority", r"staff|principal|lead|senior|sr\.?|junior|jr\.?")]:
        snippet = _evidence(text, pattern)
        if snippet:
            evidence[field] = snippet
    if company and "company" not in evidence:
        evidence["company"] = f"Source board company: {company}"
    city, country, remote, location_evidence = _location(raw, text)
    evidence.update(location_evidence)
    if city:
        evidence["city"] = raw.location_text or city
    if country:
        evidence["country"] = raw.location_text or country
    salary_min, salary_max, currency, salary_evidence = _salary_fixed(text)
    evidence.update(salary_evidence)
    employment = None
    if re.search(r"\bintern(ship)?\b", text, re.I):
        employment = "intern"
        evidence["employment_type"] = _evidence(text, r"\bintern(ship)?\b") or "intern"
    elif re.search(r"\bcontract(or)?\b", text, re.I):
        employment = "contract"
        evidence["employment_type"] = _evidence(text, r"\bcontract(or)?\b") or "contract"
    elif re.search(r"\bfull[- ]time\b", text, re.I):
        employment = "full_time"
        evidence["employment_type"] = _evidence(text, r"\bfull[- ]time\b") or "full-time"
    def skill_is_stated(skill: str) -> bool:
        if skill == "Databricks":
            return bool(re.search(r"(?:experience|proficien(?:cy|t)|knowledge|working|using|familiarity|expertise)[^.!?]{0,35}\bDatabricks\b|\bDatabricks\s+(?:SQL|platform|workspace|runtime)\b", text, re.I))
        return bool(re.search(rf"\b{re.escape(skill)}\b", text, re.I))

    skills = [skill for skill in SKILL_PATTERNS if skill_is_stated(skill)]
    if skills:
        evidence["skills"] = _evidence(text, "|".join(re.escape(skill) for skill in skills)) or ", ".join(skills)
    visa = None
    visa_match = re.search(r"(visa sponsorship|sponsor(?:ship)?|H-?1B|will sponsor)[^.!?]{0,100}", text, re.I)
    if visa_match:
        visa = not bool(re.search(r"not|no|unable|cannot", visa_match.group(0), re.I))
        evidence["visa_sponsorship"] = visa_match.group(0).strip()
    if raw.posted_date:
        evidence["posted_date"] = str(raw.posted_date)
    if raw.status:
        evidence["status"] = raw.status
    fingerprint = re.sub(r"[^a-z0-9]+", "-", f"{company}-{title}-{city or country or 'unknown'}".casefold()).strip("-")
    return JobRecord(
        posting_id=fingerprint[:180], company=company.strip(), title=title.strip(), seniority=seniority,
        city=city, country=country, remote_policy=remote, salary_min=salary_min, salary_max=salary_max,
        currency=currency, employment_type=employment, skills=skills, visa_sponsorship=visa,
        posted_date=raw.posted_date, status=raw.status, source_urls=[raw.source_url], evidence=evidence,
    )


class ExtractionService:
    """LLM-first extractor with a deterministic no-key fallback for local runs."""

    def __init__(self, model: str | None = None, prompt_for_key: bool = True):
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.calls = 0
        self.cost_usd = 0.0
        self.provider = "heuristic"
        self.warning: str | None = None
        self._client: Any | None = None
        self._llm_disabled = False
        self._configure_client(prompt_for_key)

    @staticmethod
    def _interactive() -> bool:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())

    def _configure_client(self, prompt_for_key: bool) -> None:
        key = os.getenv("OPENAI_API_KEY", "").strip()
        prompted = False
        if not key and prompt_for_key and self._interactive():
            prompted = True
            try:
                key = getpass.getpass("OpenAI API key (press Enter to use the local fallback): ").strip()
            except (EOFError, KeyboardInterrupt):
                key = ""
        if not key:
            self.warning = "No OpenAI API key supplied; using the local deterministic extractor."
            return
        try:
            import openai
        except ImportError:
            self.warning = "OpenAI SDK is not installed; using the local deterministic extractor. Install with: pip install -e \".[llm]\""
            return

        try:
            candidate = openai.OpenAI(api_key=key)
            candidate.models.list()
            self._client = candidate
            self.provider = "openai"
            return
        except Exception:
            if not prompted and prompt_for_key and self._interactive():
                try:
                    replacement = getpass.getpass("The OpenAI key was rejected. Enter another key, or press Enter for local fallback: ").strip()
                except (EOFError, KeyboardInterrupt):
                    replacement = ""
                if replacement:
                    try:
                        candidate = openai.OpenAI(api_key=replacement)
                        candidate.models.list()
                        self._client = candidate
                        self.provider = "openai"
                        return
                    except Exception:
                        pass
            self.warning = "OpenAI key was missing or invalid; using the local deterministic extractor."

    def extract(self, raw: RawPosting) -> JobRecord:
        if self._client is None or self._llm_disabled:
            return _heuristic(raw)
        try:
            prompt = (
                "Extract exactly one job posting as JSON. Use null when a field is not explicitly stated; never guess. "
                "Include evidence snippets for every non-null field. Schema keys: company,title,seniority,city,country,"
                "remote_policy,salary_min,salary_max,currency,employment_type,skills,visa_sponsorship,posted_date,status,evidence.\n\n"
                f"SOURCE TITLE: {raw.title}\nSOURCE COMPANY: {raw.company}\nSOURCE LOCATION: {raw.location_text}\nTEXT:\n{raw.description_text[:18000]}"
            )
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": prompt}],
            )
            data: dict[str, Any] = json.loads(response.choices[0].message.content or "{}")
            base = _heuristic(raw)
            data["posting_id"] = base.posting_id
            data["source_urls"] = [raw.source_url]
            data["first_seen"] = base.first_seen.isoformat()
            data["last_seen"] = base.last_seen.isoformat()
            if data.get("posted_date"):
                data["posted_date"] = str(data["posted_date"])
            record = JobRecord.model_validate(data)
            self.calls += 1
            self.provider = "openai"
            usage = getattr(response, "usage", None)
            if usage:
                input_rate, output_rate = rates_for(self.model)
                self.cost_usd += ((getattr(usage, "prompt_tokens", 0) * input_rate) + (getattr(usage, "completion_tokens", 0) * output_rate)) / 1_000_000
            return record
        except Exception:
            self._llm_disabled = True
            self.warning = "OpenAI extraction failed during the run; remaining records use the local deterministic extractor."
            return _heuristic(raw)
