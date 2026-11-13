from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from .storage import Store


@dataclass
class ResponseData:
    url: str
    status_code: int
    content_type: str
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)


class PoliteClient:
    def __init__(self, store: Store, refresh: bool = False, timeout: int = 30):
        self.store = store
        self.refresh = refresh
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "job-market-pipeline/0.1 (+polite research client)"})
        self.last_request: dict[str, float] = {}
        self.robots: dict[str, RobotFileParser] = {}

    def _allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self.robots:
            robots_url = f"{base}/robots.txt"
            parser = RobotFileParser(robots_url)
            try:
                response = self.session.get(robots_url, timeout=self.timeout)
                if response.status_code == 404:
                    parser.parse([])
                elif response.ok:
                    parser.parse(response.text.splitlines())
                else:
                    parser.parse([])
            except requests.RequestException:
                parser.parse([])
            self.robots[base] = parser
        return self.robots[base].can_fetch(self.session.headers["User-Agent"], url)

    def get(self, url: str, source: str, retries: int = 3) -> ResponseData:
        key = self.store.cache_key(url)
        cached = None if self.refresh else self.store.get_cached(key)
        if cached is not None:
            return ResponseData(url, cached["status_code"], cached["content_type"], bytes(cached["body"]))
        if not self._allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        host = urlparse(url).netloc
        for attempt in range(retries):
            delay = 1.0 - (time.monotonic() - self.last_request.get(host, 0.0))
            if delay > 0:
                time.sleep(delay)
            try:
                response = self.session.get(url, timeout=self.timeout)
                self.last_request[host] = time.monotonic()
                if (response.status_code == 429 or response.status_code >= 500) and attempt < retries - 1:
                    retry_after = response.headers.get("retry-after")
                    try:
                        wait_for = float(retry_after) if retry_after else 2**attempt
                    except ValueError:
                        wait_for = 2**attempt
                    time.sleep(wait_for)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
                self.store.put_cached(key, response.status_code, content_type, response.content)
                return ResponseData(url, response.status_code, content_type, response.content)
            except requests.RequestException:
                if attempt == retries - 1:
                    raise
                time.sleep(2**attempt)
        raise RuntimeError(f"unreachable fetch failure for {url}")
