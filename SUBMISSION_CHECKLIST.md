# Submission checklist

This folder is organized for a private GitHub repository.

## Included

- `pipeline/`: Greenhouse JSON, Lever JSON, Hacker News HTML, extraction, deduplication, SQLite, exports, DOM, and GraphQL helpers
- `tests/`: automated tests
- `README.md`: architecture, setup, trade-offs, failure modes, scaling, validation status
- `data/labels.csv`: human-labeling file to complete
- `data/validation/field_accuracy.csv`: 47-record source audit summary
- `data/validation/incorrect_fields.csv`: source-backed field corrections
- `data/validation/review_method.md`: honest review scope and HN coverage note
- `data/jobs.db`: SQLite storage from the final clean run
- `data/exports/`: JSON, CSV, run metrics, quality report, and per-record cost estimates

## Final commands

```powershell
python -m pip install -e ".[dev,llm]"
$env:OPENAI_API_KEY="your-api-key"
python -m pipeline run --refresh
python -m pipeline quality
python -m pytest -q
```

Never commit `.env` files or API keys. Create the GitHub repository as private and invite the evaluator. Describe the Claude review as human-directed, LLM-assisted source validation; do not call it independent manual labeling.
