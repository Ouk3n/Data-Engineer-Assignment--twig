from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Iterable
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from .http import PoliteClient
from .models import RawPosting
from .text import html_to_text


GREENHOUSE_TOKENS = ("stripe", "airbnb", "databricks", "figma")
# Plaid currently returns 404 from the public board API; Zoox is the documented
# same-ATS fallback used for this run and is called out in the README.
LEVER_SITES = ("palantir", "plaid", "zoox")
HN_SUBMITTED = "https://news.ycombinator.com/submitted?id=whoishiring"


def _date_from_value(value: Any) -> date | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, tz=timezone.utc).date()
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _first(value: Any, default: str = "") -> str:
    if isinstance(value, list):
        return str(value[0]) if value else default
    return str(value) if value is not None else default


class GreenhouseSource:
    def __init__(self, client: PoliteClient, tokens: Iterable[str] = GREENHOUSE_TOKENS):
        self.client = client
        self.tokens = tuple(tokens)

    def fetch(self) -> list[RawPosting]:
        result: list[RawPosting] = []
        for token in self.tokens:
            url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
            try:
                response = self.client.get(url, "greenhouse")
                if "json" not in response.content_type and not response.text.lstrip().startswith("{"):
                    raise ValueError(f"Greenhouse returned {response.content_type} for {url}")
                payload = response.json()
                for job in payload.get("jobs", []):
                    html = job.get("content") or ""
                    location = job.get("location") or {}
                    result.append(
                        RawPosting(
                            source="greenhouse",
                            source_id=f"{token}:{job.get('id')}",
                            source_url=job.get("absolute_url") or url,
                            company=token.title(),
                            title=job.get("title"),
                            location_text=location.get("name") if isinstance(location, dict) else str(location),
                            description_html=html,
                            description_text=html_to_text(html),
                            # Greenhouse exposes updated_at, not a reliable posted date.
                            posted_date=_date_from_value(job.get("first_published")),
                            raw=job,
                        )
                    )
            except Exception as exc:
                self.client.store.record_failure("greenhouse", url, str(exc))
        return result


class LeverSource:
    def __init__(self, client: PoliteClient, sites: Iterable[str] = LEVER_SITES):
        self.client = client
        self.sites = tuple(sites)

    def fetch(self) -> list[RawPosting]:
        result: list[RawPosting] = []
        for site in self.sites:
            url = f"https://api.lever.co/v0/postings/{site}?mode=json"
            try:
                response = self.client.get(url, "lever")
                if "json" not in response.content_type and not response.text.lstrip().startswith("["):
                    raise ValueError(f"Lever returned non-JSON content type {response.content_type} for {url}")
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError(f"Lever payload was not a list for {url}")
                for job in payload:
                    categories = job.get("categories") or {}
                    html = job.get("description") or ""
                    plain = job.get("descriptionPlain") or html_to_text(html)
                    location = categories.get("location") or _first(categories.get("allLocations"))
                    result.append(
                        RawPosting(
                            source="lever",
                            source_id=f"{site}:{job.get('id') or job.get('hostedUrl')}",
                            source_url=job.get("hostedUrl") or job.get("applyUrl") or url,
                            company=site.title(),
                            title=job.get("text"),
                            location_text=location,
                            description_html=html,
                            description_text=plain,
                            posted_date=_date_from_value(job.get("createdAt")),
                            raw=job,
                        )
                    )
            except Exception as exc:
                self.client.store.record_failure("lever", url, str(exc))
        return result


class HackerNewsSource:
    """Scrape the current whoishiring thread and its static More pagination."""

    def __init__(self, client: PoliteClient, max_pages: int = 40):
        self.client = client
        self.max_pages = max_pages

    def _current_thread_url(self) -> str:
        page = self.client.get(HN_SUBMITTED, "hacker_news")
        soup = BeautifulSoup(page.text, "html.parser")
        for link in soup.select("a.storylink, a.titleline, span.titleline > a"):
            title = link.get_text(" ", strip=True).casefold()
            if "who is hiring" in title:
                return urljoin("https://news.ycombinator.com/", link.get("href", ""))
        raise LookupError("Could not find a Who is hiring? thread on HN submitted page")

    @staticmethod
    def _comment_header(text: str) -> tuple[str | None, str | None, str | None]:
        lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
        if not lines:
            return None, None, None
        header = lines[0]
        parts = [part.strip() for part in re.split(r"\s*\|\s*", header)]
        company = parts[0] if parts else None
        title = parts[1] if len(parts) > 1 else None
        location = parts[2] if len(parts) > 2 else None
        if company and len(company) > 120:
            company = company[:120]
        return company, title, location

    def fetch(self) -> list[RawPosting]:
        thread_url = self._current_thread_url()
        page_url = thread_url
        result: list[RawPosting] = []
        seen: set[str] = set()
        for _ in range(self.max_pages):
            response = self.client.get(page_url, "hacker_news")
            soup = BeautifulSoup(response.text, "html.parser")
            for row in soup.select("tr.comtr[id]"):
                comment_id = row.get("id")
                if not comment_id or comment_id in seen:
                    continue
                seen.add(comment_id)
                content = row.select_one(".commtext")
                if content is None:
                    continue
                text = content.get_text("\n", strip=True)
                company, title, location = self._comment_header(text)
                result.append(
                    RawPosting(
                        source="hacker_news",
                        source_id=comment_id,
                        source_url=f"https://news.ycombinator.com/item?id={comment_id}",
                        company=company,
                        title=title,
                        location_text=location,
                        description_html=str(content),
                        description_text=text,
                        raw={"thread_url": thread_url, "comment_id": comment_id},
                    )
                )
            more = soup.select_one("a.morelink")
            if not more or not more.get("href"):
                break
            page_url = urljoin("https://news.ycombinator.com/", more["href"])
        return result
