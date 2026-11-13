from __future__ import annotations

import argparse
import json
from pathlib import Path

from .quality import score_labels, write_label_template
from .runner import run
from .storage import Store


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape, normalize, deduplicate and export US data/ML engineering jobs")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--db", default="data/jobs.db")
    run_parser.add_argument("--out", default="data/exports")
    run_parser.add_argument("--refresh", action="store_true", help="bypass raw-response cache and fetch again")
    run_parser.add_argument("--no-hn", action="store_true")
    run_parser.add_argument("--no-llm-prompt", action="store_true", help="do not prompt for an OpenAI key; use the local fallback when OPENAI_API_KEY is absent")
    label_parser = sub.add_parser("label-template")
    label_parser.add_argument("--path", default="data/labels.csv")
    quality_parser = sub.add_parser("quality")
    quality_parser.add_argument("--db", default="data/jobs.db")
    quality_parser.add_argument("--labels", default="data/labels.csv")
    quality_parser.add_argument("--out", default="data/exports/quality_report.json")
    args = parser.parse_args()
    if args.command == "label-template":
        write_label_template(args.path)
        print(f"Wrote {args.path}")
        return
    if args.command == "quality":
        with Store(args.db) as store:
            report = score_labels(args.labels, [record.model_dump(mode="json") for record in store.all_records()])
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return
    metrics = run(args.db, args.out, refresh=args.refresh, include_hn=not args.no_hn, prompt_for_key=not args.no_llm_prompt)
    print(json.dumps(metrics.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
