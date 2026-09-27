"""ESV API client (https://api.esv.org), used for the text the classifier reads.

Crossway's terms for personal, non-commercial use: at most 500 verses stored
locally, 60 requests/minute, 1,000/hour, 5,000/day. So chapters are fetched on
demand, requests are paced, and the disk cache keeps at most 500 verses.
Set ESV_API_KEY (environment or .env) to enable; otherwise callers fall back to
the local BSB text.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from pathlib import Path

from .refs import FULL_NAME

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "esv-cache.json"
MAX_CACHED_VERSES = 500
MIN_INTERVAL = 1.05  # seconds between requests (≤ 60/minute)
HOURLY_LIMIT = 1000


def api_key() -> str | None:
    if key := os.environ.get("ESV_API_KEY"):
        return key
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ESV_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return None


class ESV:
    def __init__(self, key: str):
        self.key = key
        self._last = 0.0
        self._recent: list[float] = []
        self._cache: OrderedDict[str, dict] = OrderedDict()  # chapter key -> {verses: {n: text}, footnotes: str}
        if CACHE_PATH.exists():
            self._cache.update(json.loads(CACHE_PATH.read_text(encoding="utf-8")))

    def _save(self) -> None:
        # Evict oldest chapters until the stored verse count is within the limit.
        while sum(len(c["verses"]) for c in self._cache.values()) > MAX_CACHED_VERSES and len(self._cache) > 1:
            self._cache.popitem(last=False)
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")

    def _pace(self) -> None:
        now = time.monotonic()
        self._recent = [t for t in self._recent if now - t < 3600]
        if len(self._recent) >= HOURLY_LIMIT:
            time.sleep(3600 - (now - self._recent[0]) + 1)
        wait = self._last + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self._recent.append(self._last)

    def chapter(self, book: str, chapter: int) -> dict:
        """{'verses': {verse_number: text}, 'footnotes': str} for one chapter."""
        key = f"{book} {chapter}"
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        params = {
            "q": f"{FULL_NAME[book]} {chapter}",
            "include-passage-references": "false",
            "include-headings": "false",
            "include-short-copyright": "false",
            "include-footnotes": "true",
            "include-footnote-body": "true",
            "include-first-verse-numbers": "true",
            "indent-poetry": "false",
            "indent-paragraphs": "0",
        }
        req = urllib.request.Request(
            "https://api.esv.org/v3/passage/text/?" + urllib.parse.urlencode(params),
            headers={"Authorization": f"Token {self.key}"},
        )
        self._pace()
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        text = "".join(data.get("passages") or [])
        body, _, notes = text.partition("Footnotes")
        verses: dict[str, str] = {}
        for m in re.finditer(r"\[(\d+)\]\s*(.*?)(?=\s*\[\d+\]|\Z)", body, re.S):
            verses[m[1]] = " ".join(m[2].split())
        result = {"verses": verses, "footnotes": " ".join(notes.split())}
        self._cache[key] = result
        self._save()
        return result
