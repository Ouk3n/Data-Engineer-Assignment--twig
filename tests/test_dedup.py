from datetime import datetime, timezone

from pipeline.dedup import Deduplicator
from pipeline.models import JobRecord


def record(title: str, url: str, salary: float | None = None) -> JobRecord:
    now = datetime.now(timezone.utc)
    return JobRecord(
        posting_id="stripe-data-engineer-san-francisco",
        company="Stripe",
        title=title,
        city="San Francisco",
        country="US",
        remote_policy="hybrid",
        salary_min=salary,
        source_urls=[url],
        first_seen=now,
        last_seen=now,
    )


def test_dedup_merges_title_variants_and_urls():
    dedup = Deduplicator()
    one = dedup.add(record("Sr. Data Engineer", "https://greenhouse/job/1", 150000))
    merged = dedup.add(record("Senior Data Engineer, Platform", "https://hn/item?id=2", 160000))
    assert len(dedup.records) == 1
    assert set(merged.source_urls) == {"https://greenhouse/job/1", "https://hn/item?id=2"}
    assert merged.salary_min == 150000


def test_dedup_keeps_different_companies_separate():
    dedup = Deduplicator()
    dedup.add(record("Data Engineer", "https://a/job/1"))
    other = record("Data Engineer", "https://b/job/2")
    other.company = "Plaid"
    dedup.add(other)
    assert len(dedup.records) == 2
