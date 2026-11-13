# Job market pipeline

This is a small, production-minded Python pipeline for the Data Engineer take-home assignment. It ingests the three requested sources, keeps only US or US-remote data/ML/analytics/platform engineering roles, validates a canonical record, merges duplicates, stores raw responses, records changes, and exports valid JSON and CSV.

## Quick start

```powershell
cd C:\Users\amanb\data-engineer-take-home
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
# Add `,llm` when you want OpenAI extraction:
# pip install -e ".[dev,llm]"
python -m pipeline label-template
python -m pipeline run --refresh
python -m pytest -q
```

An interactive run asks for an OpenAI API key without echoing it. Press Enter to continue with the local deterministic extractor. You can also set `OPENAI_API_KEY` before running, or use `--no-llm-prompt` in automation. Missing, invalid, unavailable, or failed OpenAI calls automatically fall back to the local extractor and report the reason in `run_metrics.json`.

## Hand-labeling and scoring

Copy `posting_id` values from `data/exports/job_postings.json` into `data/labels.csv`. Fill the columns from `company` through `status` using the source text and evidence. Use `NULL` when the source does not state a value; leave a cell blank only when you are not labeling that field. For `skills`, use comma-separated values such as `Python, SQL, Spark`; for dates use `YYYY-MM-DD`; for booleans use `true` or `false`; for salary use the numeric value shown in the JSON. After filling 20 rows, run:

```powershell
python -m pipeline quality
```

This writes `data/exports/quality_report.json`. Because this is CSV, quote skills values containing commas, for example `"Python, SQL, Spark"`. LLM calls and actual cost are recorded in `data/exports/run_metrics.json`; hypothetical per-record estimates are written to `data/exports/llm_cost_estimates.csv`.

## External validation included

`data/validation/field_accuracy.csv` and `data/validation/incorrect_fields.csv` are the source-URL-based audit outputs supplied for this submission. The review was human-directed and LLM-assisted using Claude; it is not represented as independent manual labeling. The audit checked 47 records, including 8 Hacker News-linked records. Current checked accuracy is: company 100%, title 100%, country 97.9%, remote policy 85.1%, salary fields 93.6%, employment type 66.0%, skills 73.0%, and posted date 85.1%. `incorrect_fields.csv` contains the record, field, current value, corrected value, source URL, and supporting text for each flagged field.

## SQLite storage

The included `data/jobs.db` is the runnable SQLite store. It contains the canonical `postings` table, raw-response `raw_cache`, `change_history`, and `run_failures`. The clean packaged run contains 47 postings, 8 cached source responses, and one logged Lever fallback failure for the unavailable Plaid board. Re-running the command updates the same database idempotently and preserves history when a record changes.

## Submission status

The pipeline, SQLite storage, exports, cache, tests, validation reports, and cost estimates are included. `data/labels.csv` contains the first verified row; the full Claude audit is included separately under `data/validation/`. The current live target set has 8 Hacker News-linked canonical records, so the PDF's 10-HN labeling target is documented as a source-availability deviation. The supplied run used the local fallback (`llm_calls: 0`); run with `OPENAI_API_KEY` if the evaluator requires actual LLM calls and billed cost.

The final files are written to `data/exports/job_postings.json`, `data/exports/job_postings.csv`, and `data/exports/run_metrics.json`. The JSON is emitted with `json.dumps(..., indent=2, ensure_ascii=False)` and is validated by Pydantic before export. Rerunning without `--refresh` reads the raw-response cache. Use `--refresh` to detect closures, salary changes, location changes, and other updates; changes are appended to SQLite `change_history`.

## Architecture

`sources.py` has three independent collectors. Greenhouse calls the public `boards-api` endpoint with `content=true` and converts HTML-in-JSON descriptions to text. Lever calls `mode=json`, checks the response content type before decoding, and maps its different schema into the same `RawPosting` model. The assignment's Plaid board currently returns 404, so the configured same-ATS fallback is Zoox and this substitution is intentional. Hacker News finds the current `Who is hiring?` thread from the submitted page, parses comment HTML, and follows every static `More` link; it never uses the Firebase API.

`http.py` is shared by all collectors. It reads robots.txt, enforces a one-second-per-host minimum, retries 5xx/request failures with exponential backoff, caches raw bodies in SQLite, and raises source-level failures without stopping other sources. `extract.py` uses an optional OpenAI structured JSON extraction path when `OPENAI_API_KEY` is present. Without a key, its deterministic extractor is fully runnable locally and still enforces null-over-guessing and evidence snippets. `dedup.py` uses normalized company/title/city matching plus title similarity, and preserves all source URLs and evidence on merge.

For dynamic sites outside this assignment, `rendering.py` includes an optional Playwright DOM renderer and a GraphQL response validator. Install the extras with `pip install -e ".[browser]"` and `playwright install chromium`; the official Greenhouse and Lever endpoints stay on their simpler public JSON paths.

## Data quality and trade-offs

Run `python -m pipeline label-template` and fill 20 rows, including at least 10 Hacker News rows. A subsequent run produces `quality_report.json` with field-level accuracy. LLM cost is measured from provider token usage; heuristic-only runs have zero LLM cost. The extractor sends bounded posting text rather than whole HTML pages. A field absent from the source remains null.

The first things likely to break are upstream schema changes, HN markup changes, and ambiguous HN comments containing several roles. These are isolated to source adapters and logged in `run_failures`; one bad source does not discard successful sources. At 5,000 sources refreshed weekly, I would add a durable queue for fetch jobs, per-domain concurrency/rate-limit state, source-specific fixtures and contract tests, a cheaper pre-filter model, and a content-hash/embedding review queue only for uncertain dedup pairs. The SQLite design can move to Postgres without changing the source or extraction contracts.

## Tools

The implementation was built and reviewed with OpenAI Codex. The LLM path is optional and uses the OpenAI Python SDK only when `OPENAI_API_KEY` is supplied. No cloud deployment or orchestration framework is required.
