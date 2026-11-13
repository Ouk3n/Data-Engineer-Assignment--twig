from __future__ import annotations

import math
import os
import json
from typing import Any


# USD per 1M tokens. Override with environment variables when using another model/rate.
DEFAULT_RATES = {
    "gpt-4o-mini": (0.15, 0.60),
}


def rates_for(model: str) -> tuple[float, float]:
    default_input, default_output = DEFAULT_RATES.get(model, (0.15, 0.60))
    input_rate = float(os.getenv("OPENAI_INPUT_USD_PER_1M", default_input))
    output_rate = float(os.getenv("OPENAI_OUTPUT_USD_PER_1M", default_output))
    return input_rate, output_rate


def estimate_record_cost(raw: Any, model: str, output_tokens: int = 400) -> dict[str, Any]:
    prompt_chars = len(
        "Extract exactly one job posting as JSON. Use null when a field is not explicitly stated. "
        + (raw.title or "")
        + (raw.company or "")
        + (raw.location_text or "")
        + (raw.description_text or "")[:18_000]
    )
    return estimate_from_prompt_chars(prompt_chars, model, output_tokens)


def estimate_canonical_cost(record: Any, model: str, output_tokens: int = 400) -> dict[str, Any]:
    prompt_chars = len(
        "Extract exactly one job posting as JSON. Use null when a field is not explicitly stated. "
        + (record.company or "")
        + (record.title or "")
        + json.dumps(record.evidence, ensure_ascii=False)
    )
    return estimate_from_prompt_chars(prompt_chars, model, output_tokens)


def estimate_from_prompt_chars(prompt_chars: int, model: str, output_tokens: int = 400) -> dict[str, Any]:
    input_tokens = max(1, math.ceil(prompt_chars / 4))
    input_rate, output_rate = rates_for(model)
    estimated = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    return {
        "model": model,
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_cost_usd": round(estimated, 8),
        "estimate_basis": "Approximate 4 characters/token and 400 output tokens; not actual spend",
    }
