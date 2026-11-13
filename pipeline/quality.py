from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


FIELDS = ["company", "title", "seniority", "city", "country", "remote_policy", "salary_min", "salary_max", "currency", "employment_type", "skills", "visa_sponsorship", "posted_date", "status"]


def write_label_template(path: str | Path, rows: int = 20) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["posting_id", "source", *FIELDS])
        writer.writeheader()
        for _ in range(rows):
            writer.writerow({key: "" for key in ["posting_id", "source", *FIELDS]})


def score_labels(labels_path: str | Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {record["posting_id"]: record for record in records}
    totals = defaultdict(int)
    correct = defaultdict(int)
    labeled_rows: set[str] = set()
    with Path(labels_path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            candidate = by_id.get(row.get("posting_id", ""))
            if not candidate:
                continue
            labeled_rows.add(row["posting_id"])
            for field in FIELDS:
                expected = row.get(field, "").strip()
                if expected == "":
                    continue
                actual = candidate.get(field)
                is_null = expected.casefold() in {"null", "none", "n/a"}
                totals[field] += 1
                if is_null:
                    matched = actual is None or actual == []
                elif field == "skills":
                    expected_skills = {item.strip().casefold() for item in expected.split(",") if item.strip()}
                    actual_skills = {str(item).strip().casefold() for item in (actual or []) if str(item).strip()}
                    matched = expected_skills == actual_skills
                elif field in {"salary_min", "salary_max"}:
                    try:
                        matched = float(actual) == float(expected)
                    except (TypeError, ValueError):
                        matched = False
                else:
                    matched = str(actual).casefold() == expected.casefold()
                if matched:
                    correct[field] += 1
    accuracy = {field: (correct[field] / totals[field] if totals[field] else None) for field in FIELDS}
    return {"labeled_rows": len(labeled_rows), "labeled_fields": sum(totals.values()), "field_accuracy": accuracy}
