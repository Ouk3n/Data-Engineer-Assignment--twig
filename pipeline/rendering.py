"""Optional dynamic-site helpers: DOM rendering and GraphQL JSON validation."""

from __future__ import annotations

from typing import Any

import requests


def graphql_json(url: str, query: str, variables: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """POST GraphQL and fail loudly on transport or GraphQL errors."""

    response = requests.post(url, json={"query": query, "variables": variables or {}}, headers=headers or {}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise ValueError(f"GraphQL errors: {payload['errors']}")
    if not isinstance(payload.get("data"), dict):
        raise ValueError("GraphQL response did not contain an object data field")
    return payload["data"]


def render_dom(url: str, wait_for: str | None = None, timeout_ms: int = 30_000) -> str:
    """Render a JS page with Playwright; optional dependency, never used for the official API sources."""

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install the browser extra and run `playwright install chromium` to use DOM rendering") from exc
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        if wait_for:
            page.wait_for_selector(wait_for, timeout=timeout_ms)
        html = page.content()
        browser.close()
        return html
