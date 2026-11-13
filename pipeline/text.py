from __future__ import annotations

import html
import re
import unicodedata
from difflib import SequenceMatcher

from bs4 import BeautifulSoup


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    # Greenhouse often returns HTML escaped once inside JSON. Decode before
    # parsing so tags such as &lt;div&gt; are removed instead of becoming text.
    decoded = html.unescape(value)
    soup = BeautifulSoup(decoded, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    return " ".join(html.unescape(soup.get_text(" ")).split())


def normalize(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = text.encode("ascii", "ignore").decode().casefold()
    text = re.sub(r"\b(sr|jr|ii|iii|iv)\b", "", text)
    text = re.sub(r"\b(senior|staff|principal|lead|manager)\b", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize(left), normalize(right)).ratio()


def first_sentence(text: str, limit: int = 280) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"
