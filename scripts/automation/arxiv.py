"""Sprint 6 — resolve claimed arXiv identifiers against arXiv itself.

**The gap this closes.** An observation earns the `published` evidence tier — the
strongest we award — because its text contained a string matching
`\\d{4}\\.\\d{4,5}`. Nobody checked that the paper exists, or what it is about.
So "arXiv:2607.16401" typed in a tweet, a mis-transcribed id, a paper about
something else entirely, and a genuine preprint of the claimed result were all
indistinguishable, and all counted as our best class of evidence.

That is the same failure as the old boolean `has_corroboration`, one level down:
treating the *presence of a reference* as the *substance of one*.

**What this does not do.** Confirming a paper exists is not confirming it proves
the claim. A resolved id upgrades "somebody typed a number" to "there is a real
preprint, here is its title and date" — no further. Judging whether the paper
supports the claim is a curator's job, and the metadata is fetched precisely so
they have something to judge with.

No API key: arXiv's export API is public. It asks for one request every three
seconds and a descriptive User-Agent, both of which this honours.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterable, Protocol

import httpx

API = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"

# arXiv's stated courtesy limit. Slower than we need; the whole point of the
# Gemini incident was that a rate limit is cheaper to respect than to discover.
MIN_INTERVAL_SECONDS = 3.0

# The API takes at most this many ids per request in practice.
BATCH = 50

_VERSION = re.compile(r"v\d+$")


class ArxivError(RuntimeError):
    pass


@dataclass
class Paper:
    arxiv_id: str
    title: str
    published: str | None = None
    updated: str | None = None
    authors: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    doi: str | None = None
    abstract_url: str | None = None

    def to_dict(self) -> dict:
        return {
            "arxivId": self.arxiv_id, "title": self.title,
            "published": self.published, "updated": self.updated,
            "authors": self.authors[:8], "categories": self.categories,
            "doi": self.doi, "url": self.abstract_url,
        }


class ArxivSource(Protocol):
    def fetch(self, ids: Iterable[str]) -> dict[str, Paper | None]: ...


def normalise(arxiv_id: str) -> str:
    """`2607.16401v2` and `arXiv:2607.16401` are the same paper."""
    cleaned = str(arxiv_id).strip().lower()
    cleaned = cleaned.removeprefix("arxiv:").strip()
    return _VERSION.sub("", cleaned)


def _text(node, tag: str) -> str | None:
    found = node.find(f"{ATOM}{tag}")
    if found is None or found.text is None:
        return None
    return " ".join(found.text.split()) or None


def parse_feed(xml: str) -> dict[str, Paper]:
    """Parse an Atom feed into papers, keyed by normalised id.

    arXiv answers a query for a nonexistent id with an entry whose title is
    "Error" rather than with an HTTP error, so an unresolvable id has to be
    recognised from the payload — silently treating it as a hit would defeat the
    whole point of asking.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ArxivError(f"malformed response: {exc}") from None

    papers: dict[str, Paper] = {}
    for entry in root.findall(f"{ATOM}entry"):
        raw_id = _text(entry, "id") or ""
        title = _text(entry, "title") or ""
        if title.lower() == "error" or not raw_id:
            continue
        match = re.search(r"abs/([^v\s]+)", raw_id)
        if not match:
            continue
        paper = Paper(
            arxiv_id=normalise(match.group(1)),
            title=title,
            published=_text(entry, "published"),
            updated=_text(entry, "updated"),
            authors=[
                " ".join((a.findtext(f"{ATOM}name") or "").split())
                for a in entry.findall(f"{ATOM}author")
            ],
            categories=[
                c.attrib["term"]
                for c in entry.findall("{http://arxiv.org/schemas/atom}primary_category")
                + entry.findall(f"{ATOM}category")
                if "term" in c.attrib
            ],
            doi=entry.findtext("{http://arxiv.org/schemas/atom}doi"),
            abstract_url=raw_id,
        )
        papers[paper.arxiv_id] = paper
    return papers


class ArxivClient:
    """Live client. Paced, retried, and never told to trust an empty answer."""

    def __init__(self, *, timeout: float = 30.0, max_retries: int = 3,
                 min_interval: float = MIN_INTERVAL_SECONDS, base_url: str = API) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._min_interval = min_interval
        self._base_url = base_url
        self._last_call_at = 0.0
        self.call_count = 0

    def _pace(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_call_at
        if self._last_call_at and elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_at = time.monotonic()

    def _get(self, ids: list[str]) -> str:
        params = {"id_list": ",".join(ids), "max_results": str(len(ids))}
        headers = {"User-Agent": "ai-math-tracker/1.0 (+https://github.com/bogdan-ionut/ai-math-tracker)"}
        last: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                self._pace()
                self.call_count += 1
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.get(self._base_url, params=params, headers=headers)
                if resp.status_code == 200:
                    return resp.text
                if resp.status_code in (429, 500, 502, 503, 504):
                    last = ArxivError(f"HTTP {resp.status_code} from arXiv")
                    if attempt < self._max_retries:
                        time.sleep(self._min_interval * attempt)
                        continue
                raise ArxivError(f"HTTP {resp.status_code} from arXiv")
            except httpx.HTTPError as exc:
                last = ArxivError(f"transport error: {type(exc).__name__}")
                if attempt < self._max_retries:
                    time.sleep(self._min_interval * attempt)
                    continue
                raise last from None
        raise last or ArxivError("unknown failure")

    def fetch(self, ids: Iterable[str]) -> dict[str, Paper | None]:
        """Resolve ids to papers. An id we asked about but did not get back maps
        to `None` — an explicit "this does not resolve", never a silent absence."""
        wanted = [normalise(i) for i in ids if str(i).strip()]
        wanted = list(dict.fromkeys(wanted))
        out: dict[str, Paper | None] = {i: None for i in wanted}
        for start in range(0, len(wanted), BATCH):
            chunk = wanted[start:start + BATCH]
            for arxiv_id, paper in parse_feed(self._get(chunk)).items():
                if arxiv_id in out:
                    out[arxiv_id] = paper
        return out


class FixtureArxivClient:
    """Offline client for tests and dry runs. Never touches the network."""

    def __init__(self, papers: dict[str, Paper] | None = None) -> None:
        self._papers = papers or {}
        self.call_count = 0

    def fetch(self, ids: Iterable[str]) -> dict[str, Paper | None]:
        self.call_count += 1
        return {normalise(i): self._papers.get(normalise(i)) for i in ids}
