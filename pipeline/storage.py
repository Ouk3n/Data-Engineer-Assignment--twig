from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import JobRecord, jsonable


SCHEMA = """
CREATE TABLE IF NOT EXISTS postings (
  posting_id TEXT PRIMARY KEY,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  data_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS change_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  posting_id TEXT NOT NULL,
  changed_at TEXT NOT NULL,
  change_type TEXT NOT NULL,
  before_json TEXT NOT NULL,
  after_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw_cache (
  cache_key TEXT PRIMARY KEY,
  fetched_at TEXT NOT NULL,
  status_code INTEGER NOT NULL,
  content_type TEXT NOT NULL,
  body BLOB NOT NULL,
  sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_failures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TEXT NOT NULL,
  source TEXT NOT NULL,
  url TEXT NOT NULL,
  error TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @staticmethod
    def cache_key(url: str, method: str = "GET", body: str = "") -> str:
        return hashlib.sha256(f"{method}\n{url}\n{body}".encode()).hexdigest()

    def get_cached(self, key: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM raw_cache WHERE cache_key = ?", (key,)).fetchone()

    def put_cached(self, key: str, status: int, content_type: str, body: bytes) -> None:
        now = datetime.now(timezone.utc).isoformat()
        digest = hashlib.sha256(body).hexdigest()
        self.conn.execute(
            "INSERT OR REPLACE INTO raw_cache VALUES (?, ?, ?, ?, ?, ?)",
            (key, now, status, content_type, body, digest),
        )
        self.conn.commit()

    def record_failure(self, source: str, url: str, error: str) -> None:
        self.conn.execute(
            "INSERT INTO run_failures(run_at, source, url, error) VALUES (?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), source, url, error),
        )
        self.conn.commit()

    def _existing_by_source_url(self, urls: list[str]) -> sqlite3.Row | None:
        if not urls:
            return None
        rows = self.conn.execute("SELECT * FROM postings").fetchall()
        wanted = set(urls)
        for row in rows:
            try:
                current = set(json.loads(row["data_json"]).get("source_urls", []))
            except (TypeError, json.JSONDecodeError):
                continue
            if current & wanted:
                return row
        return None

    def upsert(self, record: JobRecord) -> bool:
        data = jsonable(record)
        posting_id = record.posting_id
        old = self.conn.execute("SELECT * FROM postings WHERE posting_id = ?", (posting_id,)).fetchone()
        if old is None:
            old = self._existing_by_source_url(record.source_urls)
            if old is not None:
                posting_id = old["posting_id"]
                data["posting_id"] = posting_id
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
        stable = dict(data)
        stable.pop("first_seen", None)
        stable.pop("last_seen", None)
        digest = hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if old is None:
            self.conn.execute(
                "INSERT INTO postings VALUES (?, ?, ?, ?, ?, ?, ?)",
                (posting_id, record.company, record.title, payload, digest, record.first_seen.isoformat(), record.last_seen.isoformat()),
            )
            self.conn.commit()
            return True

        if old["content_hash"] == digest:
            self.conn.execute("UPDATE postings SET last_seen = ? WHERE posting_id = ?", (record.last_seen.isoformat(), posting_id))
            self.conn.commit()
            return False

        before = json.loads(old["data_json"])
        data["first_seen"] = before["first_seen"]
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
        self.conn.execute(
            "UPDATE postings SET company=?, title=?, data_json=?, content_hash=?, last_seen=? WHERE posting_id=?",
            (record.company, record.title, payload, digest, record.last_seen.isoformat(), posting_id),
        )
        self.conn.execute(
            "INSERT INTO change_history(posting_id, changed_at, change_type, before_json, after_json) VALUES (?, ?, ?, ?, ?)",
            (posting_id, record.last_seen.isoformat(), "record_updated", json.dumps(before, sort_keys=True), payload),
        )
        self.conn.commit()
        return True

    def all_records(self) -> list[JobRecord]:
        rows = self.conn.execute("SELECT data_json FROM postings ORDER BY company, title").fetchall()
        return [JobRecord.model_validate(json.loads(row[0])) for row in rows]

    def export(self, output_dir: str | Path) -> tuple[Path, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        records = [jsonable(item) for item in self.all_records()]
        json_path = output / "job_postings.json"
        csv_path = output / "job_postings.csv"
        json_path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        columns = list(JobRecord.model_fields)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for item in records:
                writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in item.items()})
        return json_path, csv_path

    def change_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM change_history").fetchone()[0])

    def failure_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM run_failures").fetchone()[0])

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
