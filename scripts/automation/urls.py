"""URL canonicalisation.

Two URLs that point at the same thing must produce the same string, so that
deterministic deduplication catches them before any model is called.

Deliberately conservative: we only strip parameters that are known-safe to drop
(tracking junk). Anything we do not recognise is preserved, because dropping a
meaningful query parameter would silently merge two different resources.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Tracking parameters that never identify a resource.
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_EXACT = {
    "ref", "ref_src", "ref_url", "s", "t", "cxt", "twclid", "src",
    "fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "si", "feature",
}

# Hosts whose "www." prefix is noise.
_STRIP_WWW = True

# Known host aliases → canonical host.
_HOST_ALIASES = {
    "twitter.com": "x.com",
    "mobile.twitter.com": "x.com",
    "www.twitter.com": "x.com",
    "mobile.x.com": "x.com",
    "arxiv.org": "arxiv.org",
    "www.arxiv.org": "arxiv.org",
    "doi.org": "doi.org",
    "dx.doi.org": "doi.org",
}


def canonicalize_url(raw: str | None) -> str | None:
    """Return a canonical form of ``raw``, or ``None`` if it is not usable.

    - lowercases scheme and host
    - upgrades http → https
    - applies host aliases (twitter.com → x.com, dx.doi.org → doi.org)
    - drops tracking parameters, keeps everything else (sorted, for stability)
    - drops fragments
    - strips a trailing slash from the path
    """
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw

    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if not parts.netloc:
        return None

    host = parts.netloc.lower()
    # drop credentials and default ports
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    if host.endswith(":443") or host.endswith(":80"):
        host = host.rsplit(":", 1)[0]
    host = _HOST_ALIASES.get(host, host)
    if _STRIP_WWW and host.startswith("www.") and host not in _HOST_ALIASES:
        host = host[4:]

    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if k.lower() not in _TRACKING_EXACT
        and not any(k.lower().startswith(p) for p in _TRACKING_PREFIXES)
    ]
    query = urlencode(sorted(query_pairs))

    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return urlunsplit(("https", host, path, query, ""))


def tweet_url(author_handle: str | None, tweet_id: str) -> str:
    """Canonical permalink for a tweet."""
    handle = (author_handle or "i").lstrip("@")
    return f"https://x.com/{handle}/status/{tweet_id}"


def expand_links(entities: dict | None) -> list[str]:
    """Pull expanded (non-t.co) links out of a TwitterAPI.io entities blob.

    t.co shorteners are opaque without a network round-trip, so we take the
    ``expanded_url`` the API already provides and ignore the shortened form.
    """
    if not entities:
        return []
    out: list[str] = []
    for item in entities.get("urls") or []:
        if not isinstance(item, dict):
            continue
        url = item.get("expanded_url") or item.get("url")
        canon = canonicalize_url(url)
        if canon and "//t.co" not in canon:
            out.append(canon)
    # stable order, no duplicates
    return sorted(set(out))
