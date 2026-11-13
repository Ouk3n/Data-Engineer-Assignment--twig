from datetime import datetime, timezone

from pipeline.models import JobRecord
from pipeline.storage import Store


def make_record(salary=None):
    now = datetime.now(timezone.utc)
    return JobRecord(
        posting_id="job-1", company="Acme", title="Data Engineer", city="Austin", country="US",
        salary_min=salary, source_urls=["https://example.test/1"], first_seen=now, last_seen=now,
    )


def test_idempotent_upsert_and_change_history(tmp_path):
    with Store(tmp_path / "jobs.db") as store:
        assert store.upsert(make_record(100000)) is True
        assert store.upsert(make_record(100000)) is False
        changed = make_record(120000)
        changed.posting_id = "new-title-derived-id"
        changed.title = "Senior Data Engineer"
        assert store.upsert(changed) is True
        assert len(store.all_records()) == 1
        assert store.change_count() == 1
        assert store.all_records()[0].posting_id == "job-1"
