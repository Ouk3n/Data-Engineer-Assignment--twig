from __future__ import annotations

from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import re

from .dedup import Deduplicator
from .costs import estimate_canonical_cost, estimate_record_cost
from .extract import ExtractionService
from .http import PoliteClient
from .models import RunMetrics
from .quality import score_labels
from .sources import GreenhouseSource, HackerNewsSource, LeverSource
from .storage import Store


def _is_target(raw) -> bool:
    title = raw.title or ""
    location = raw.location_text or ""
    text = " ".join([title, location, raw.description_text or ""])
    role_title = title.replace("/", " ")
    role = bool(re.search(r"\bengineer(?:ing|s)?\b", role_title, re.I)) and bool(re.search(r"\b(?:data|ml|machine learning|analytics|platform)\b", role_title, re.I))
    if re.search(r"\b(?:software|full[- ]stack) engineer\b", title, re.I) and not re.search(r"^\s*(?:senior\s+)?(?:data|ml|machine learning|analytics|platform)", title, re.I):
        role = False
    us_location = bool(re.search(r"\b(?:US|USA|U\.S\.?|United States|NYC|New York|San Francisco|Seattle|Austin|Boston|Chicago|Denver|Los Angeles|Washington,? DC)\b|\b(?:CA|NY|WA|TX|MA|IL|CO|GA|VA|MD|OR|FL|NC|NJ|PA)\b", location, re.I))
    explicit_us_remote = bool(re.search(r"remote(?:[- ]first)?[^.]{0,40}\b(?:US|USA|United States)\b|\b(?:US|USA|United States)[^.]{0,40}remote", text, re.I))
    us = us_location or (not location and explicit_us_remote)
    return role and us


def run(db_path: str | Path, output_dir: str | Path, refresh: bool = False, include_hn: bool = True, prompt_for_key: bool = True) -> RunMetrics:
    started = datetime.now(timezone.utc)
    metrics = RunMetrics(started_at=started)
    extractor = ExtractionService(prompt_for_key=prompt_for_key)
    with Store(db_path) as store:
        client = PoliteClient(store, refresh=refresh)
        sources = [GreenhouseSource(client), LeverSource(client)]
        if include_hn:
            sources.append(HackerNewsSource(client))
        dedup = Deduplicator()
        cost_estimates = {}
        for source in sources:
            source_name = source.__class__.__name__
            failures_before = store.failure_count()
            try:
                raw_records = source.fetch()
                metrics.fetched += len(raw_records)
                metrics.parsed += len(raw_records)
                metrics.source_counts[source_name] = len(raw_records)
                for raw in raw_records:
                    try:
                        if not _is_target(raw):
                            metrics.filtered += 1
                            continue
                        canonical = extractor.extract(raw)
                        merged = dedup.add(canonical)
                        estimate = estimate_record_cost(raw, extractor.model)
                        estimate["posting_id"] = merged.posting_id
                        previous = cost_estimates.get(merged.posting_id)
                        if previous is None or estimate["estimated_input_tokens"] > previous["estimated_input_tokens"]:
                            cost_estimates[merged.posting_id] = estimate
                        metrics.extracted += 1
                    except Exception as exc:
                        metrics.errors.append(f"{source_name}: {exc}")
                        store.record_failure(source_name, getattr(raw, "source_url", ""), str(exc))
            except Exception as exc:
                metrics.errors.append(f"{source_name}: {exc}")
                store.record_failure(source_name, "", str(exc))
            metrics.failures += store.failure_count() - failures_before
        for record in dedup.records:
            store.upsert(record)
            metrics.stored += 1
        for record in store.all_records():
            if record.posting_id not in cost_estimates:
                estimate = estimate_canonical_cost(record, extractor.model)
                estimate["posting_id"] = record.posting_id
                cost_estimates[record.posting_id] = estimate
        json_path, csv_path = store.export(output_dir)
        metrics.llm_calls = extractor.calls
        metrics.llm_cost_usd = round(extractor.cost_usd, 8)
        metrics.estimated_llm_cost_usd = round(sum(item["estimated_cost_usd"] for item in cost_estimates.values()), 8)
        metrics.llm_provider = extractor.provider
        metrics.llm_warning = extractor.warning
        metrics.finished_at = datetime.now(timezone.utc)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "run_metrics.json").write_text(metrics.model_dump_json(indent=2), encoding="utf-8")
        cost_path = Path(output_dir) / "llm_cost_estimates.csv"
        with cost_path.open("w", newline="", encoding="utf-8") as handle:
            columns = ["posting_id", "model", "estimated_input_tokens", "estimated_output_tokens", "estimated_cost_usd", "estimate_basis"]
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for posting_id in sorted(cost_estimates):
                writer.writerow(cost_estimates[posting_id])
        labels = Path("data/labels.csv")
        if labels.exists():
            report = score_labels(labels, [record.model_dump(mode="json") for record in store.all_records()])
            (Path(output_dir) / "quality_report.json").write_text(__import__("json").dumps(report, indent=2), encoding="utf-8")
    return metrics
