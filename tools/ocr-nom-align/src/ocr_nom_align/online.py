"""Online lookup of the characters the reading table does not list.

A Han or Nom character that no table source knows is looked up once on the web (the `/whv/<character>` page of
hvdic.thivien.net, Hán Việt and Nôm readings) and added to the table; the answer is kept in a JSON cache, so a character is
asked for once, ever. Nothing is asked when `offline` is set. A failed request never stops a run: the character stays
unknown (red). Requests are spaced out and stop for the rest of the run when the site refuses (block page) or when several
requests in a row fail.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path

from . import __version__
from .readings import ReadingTable
from .tokens import PLACEHOLDER, is_han, nfc

BASE = "https://hvdic.thivien.net"
PAGES = ("whv", "wnom")  # one-character pages: Han characters, then Nom characters
DENIED = "truy cập của bạn đã bị từ chối"  # the site's block page: HTTP 200, a few hundred bytes
MAX_FAILURES = 3  # consecutive failed requests that end the lookups of a run

_WORD = re.compile(
    r'<div class="hvres-word ([\w -]*)"[^>]*>\s*<a href="/(?:whv|wnom)/[^"]*">(.*?)</a>', re.S
)
_BLOCK = re.compile(r'<div class="hvres (?:han|nom)-word">')
_LABEL = re.compile(r"(Âm Hán Việt|Âm Nôm):\s*(.*?)(?:<br>|$)", re.S)
_LINK = re.compile(r'href="/(?:hv|nom)/[^"]*">([^<]+)</a>')
_TAG = re.compile(r"<[^>]+>")


class OnlineError(Exception):
    """The site could not be asked (network down, HTTP error, refused)."""


class RefusedError(OnlineError):
    """The site sent its block page: ask no more in this run."""


def parse_char_page(page: str, ch: str) -> list[str]:
    """The Hán Việt and Nôm readings that `page` lists for the character `ch` (empty when it is not on the page)."""
    found: list[str] = []
    for chunk in _BLOCK.split(page)[1:]:
        m = _WORD.search(chunk)
        if not m:
            continue
        head = nfc(html.unescape(_TAG.sub("", m.group(2))).strip())
        if "<img" in m.group(2) or head.replace("\ufe0f", "").replace("\ufe00", "") != ch:
            continue
        for _, val in _LABEL.findall(chunk):
            for r in _LINK.findall(val):
                r = html.unescape(r).strip()
                if r and r.lower() not in (x.lower() for x in found):
                    found.append(r)
    return found


def http_get(url: str, *, contact: str = "", timeout: float = 10.0) -> str:
    ua = f"ocr-nom-align/{__version__}" + (f" ({contact})" if contact else "")
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            page = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return ""  # the site has no page for it: a real answer, not a failure
        if exc.code in (403, 429):
            raise RefusedError(f"HTTP {exc.code} from {BASE}") from None
        raise OnlineError(f"HTTP {exc.code} from {url}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OnlineError(f"{url}: {exc}") from None
    if DENIED in page or len(page) < 1000:
        raise RefusedError(f"block page from {BASE}")
    return page


class OnlineLookup:
    """Asks the web for characters and remembers the answers in `cache` (a JSON file; `None`: memory only)."""

    def __init__(
        self,
        cache: str | Path | None = None,
        *,
        contact: str = "",
        timeout: float = 10.0,
        pause: float = 1.0,
        max_lookups: int = 300,
        get: Callable[[str], str] | None = None,
    ) -> None:
        self.cache_path = Path(cache) if cache else None
        self.pause, self.max_lookups = pause, max_lookups
        self._get = get or (lambda url: http_get(url, contact=contact, timeout=timeout))
        self._cache: dict[str, list[str]] = {}
        if self.cache_path and self.cache_path.is_file():
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                self._cache = {k: list(v) for k, v in data.items() if isinstance(v, list)}
            except (OSError, ValueError, AttributeError):
                self._cache = {}  # a damaged cache is rebuilt, never fatal
        self.stopped = ""

    def _save(self) -> None:
        if not self.cache_path:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=0, sort_keys=True),
                encoding="utf-8",
            )
        except OSError:
            pass  # a cache that cannot be written only costs a second request next time

    def resolve(self, table: ReadingTable, chars: Iterable[str]) -> dict:
        """Add to `table` the readings of the characters in `chars` that it does not know. Returns the report."""
        todo = sorted({c for c in map(nfc, chars) if len(c) == 1 and c != PLACEHOLDER and is_han(c)
                       and not table.known(c)})  # fmt: skip
        rep = {
            "source": BASE,
            "asked": 0,
            "cached": 0,
            "found": 0,
            "not_found": [],
            "failed": [],
            "skipped": 0,
        }
        failures, asked, learned = 0, 0, False
        for c in todo:
            if c in self._cache:
                rep["cached"] += 1
                readings = self._cache[c]
            elif self.stopped or asked >= self.max_lookups:
                rep["skipped"] += 1
                continue
            else:
                readings = None
                for page in PAGES:
                    if asked:
                        time.sleep(self.pause)
                    asked += 1
                    try:
                        found = parse_char_page(
                            self._get(f"{BASE}/{page}/{urllib.parse.quote(c)}"), c
                        )
                    except RefusedError as exc:
                        self.stopped = str(exc)
                        break
                    except OnlineError:
                        failures += 1
                        if failures >= MAX_FAILURES:
                            self.stopped = f"{MAX_FAILURES} requests failed in a row"
                        break
                    failures = 0
                    readings = found
                    if found:
                        break
                if readings is None:
                    rep["failed"].append(c)
                    continue
                self._cache[c] = readings
                learned = True
            if readings:
                for r in readings:
                    table.add(c, r)
                rep["found"] += 1
            else:
                rep["not_found"].append(c)
        rep["asked"] = asked
        if learned:
            self._save()
        if rep["found"]:
            table.sources.append(f"online:{BASE} ({rep['found']} characters)")
        if self.stopped:
            rep["stopped"] = self.stopped
        return rep


__all__ = ["BASE", "OnlineError", "OnlineLookup", "RefusedError", "parse_char_page"]
