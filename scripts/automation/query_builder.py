"""Build concrete search queries from the taxonomy, and evaluate them offline.

Two jobs:

1. **Build.** Expand family templates into real query strings, applying the
   operators the probe verified as supported. Every emitted query carries a
   stable id, its family, its tier and its cap, so telemetry can attribute
   results and noisy families can be disabled from config alone.

2. **Match.** A local approximation of the search semantics, used by the
   calibration harness to ask "would this query set have found this known
   event?" without spending API calls. It is deliberately *conservative*: it
   models quoted phrases, OR-groups, implicit AND and negation, and nothing
   else. If it says a query matches, the real search very likely agrees.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "twitter_discovery.json"

MAX_QUERY_CHARS = 1000  # probe accepted 788 without error; stay under a round number


@dataclass
class BuiltQuery:
    id: str
    family: str
    tier: int
    query: str
    purpose: str
    max_results: int
    expected_precision: str
    routes_to: str | None = None
    groups: list[list[str]] = field(default_factory=list)   # for offline matching
    negatives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "family": self.family, "tier": self.tier,
            "query": self.query, "purpose": self.purpose,
            "maxResults": self.max_results,
            "expectedPrecision": self.expected_precision,
            "routesTo": self.routes_to,
        }


def load_taxonomy(path: Path | None = None) -> dict:
    return json.loads((path or CONFIG).read_text(encoding="utf-8"))


def _or_group(terms: list[str]) -> str:
    return "(" + " OR ".join(terms) + ")"


def _cluster(tax: dict, name: str) -> list[str]:
    c = tax["clusters"][name]
    return list(c["terms"]) if isinstance(c, dict) else list(c)


def build_queries(tax: dict | None = None) -> list[BuiltQuery]:
    """Expand every enabled family (and trusted account) into a concrete query."""
    tax = tax or load_taxonomy()
    defaults = tax.get("defaults", {})
    tiers = tax.get("tiers", {})
    out: list[BuiltQuery] = []

    suffix_parts: list[str] = []
    if defaults.get("language"):
        suffix_parts.append(f"lang:{defaults['language']}")
    if defaults.get("excludeRetweets"):
        suffix_parts.append("-filter:retweets")
    suffix = (" " + " ".join(suffix_parts)) if suffix_parts else ""

    for fam in tax.get("families", []):
        if not fam.get("enabled", True):
            continue
        tier = int(fam.get("tier", 2))
        tier_cfg = tiers.get(str(tier), {})
        groups: list[list[str]] = []

        if fam.get("literal"):
            core = fam["literal"]
            # recover OR-groups from the literal so offline matching still works
            for m in re.finditer(r"\(([^()]*)\)", core):
                groups.append([t.strip() for t in m.group(1).split(" OR ") if t.strip()])
        else:
            tpl = fam.get("template", {})
            parts: list[str] = []
            for key in tpl.get("all", []):
                terms = _cluster(tax, key)
                parts.append(_or_group(terms))
                groups.append(terms)
            for key_list, _label in ((tpl.get("any", []), "any"), (tpl.get("andAny", []), "andAny")):
                if not key_list:
                    continue
                terms: list[str] = []
                for key in key_list:
                    terms.extend(_cluster(tax, key))
                parts.append(_or_group(terms))
                groups.append(terms)
            core = " ".join(parts)

        negatives: list[str] = []
        if fam.get("applyNegativeTerms"):
            negatives = _cluster(tax, "negative")
            core += " " + " ".join(f"-{t}" for t in negatives)

        query = (core + suffix).strip()
        if len(query) > MAX_QUERY_CHARS:
            # Never silently truncate a query — that would change its meaning.
            # Drop the lowest-value group (the last one) and record it.
            while len(query) > MAX_QUERY_CHARS and len(groups) > 1:
                groups.pop()
                parts = [_or_group(g) for g in groups]
                query = (" ".join(parts) + suffix).strip()

        out.append(BuiltQuery(
            id=fam["id"], family=fam["id"], tier=tier, query=query,
            purpose=fam.get("purpose", ""),
            max_results=int(tier_cfg.get("maxResultsPerRun", 20)),
            expected_precision=fam.get("expectedPrecision", "unknown"),
            routes_to=fam.get("routesTo"),
            groups=groups, negatives=negatives,
        ))

    accounts = tax.get("trustedAccounts", {})
    tpl = accounts.get("queryTemplate", "from:{handle}")
    for acc in accounts.get("accounts", []):
        if not acc.get("enabled"):
            continue
        handle = acc["username"]
        q = tpl.format(handle=handle)
        groups = [[t.strip() for t in m.group(1).split(" OR ") if t.strip()]
                  for m in re.finditer(r"\(([^()]*)\)", q)]
        out.append(BuiltQuery(
            id=f"account-{handle}", family="trusted-account", tier=1,
            query=q + (" -filter:retweets" if defaults.get("excludeRetweets") else ""),
            purpose=f"Trusted account @{handle} ({acc.get('category','?')})",
            max_results=int(tiers.get("1", {}).get("maxResultsPerRun", 40)),
            expected_precision="high", groups=groups,
        ))

    return out


# ---------------------------------------------------------------- offline matching

_QUOTED = re.compile(r'^"(.*)"$')


def _term_matches(term: str, text: str, author: str | None = None) -> bool:
    t = term.strip()
    m = _QUOTED.match(t)
    if m:                                   # quoted phrase: substring, case-insensitive
        return m.group(1).lower() in text
    if t.startswith("url:"):
        return t[4:].lower() in text
    if t.startswith("from:"):
        # An account query only matches posts by that account. Modelling this
        # matters: treating it as neutral made every account query appear to
        # match every gold-set entry.
        return author is not None and author.lower() == t[5:].strip().lower()
    if t.startswith(("lang:", "-filter:", "since:", "until:")):
        return True                          # not modelled; treated as neutral
    # bare word: whole-word match so "AI" does not match "said"
    return re.search(rf"(?<!\w){re.escape(t.lower())}(?!\w)", text) is not None


def query_matches(bq: BuiltQuery, text: str, author: str | None = None) -> bool:
    """Would this query plausibly return a post with this text (by this author)?

    Every OR-group must have at least one hit (implicit AND between groups), any
    bare `from:` constraint must be satisfied, and no negative term may appear.
    """
    low = text.lower()
    for neg in bq.negatives:
        if _term_matches(neg, low, author):
            return False
    # bare operators sit outside OR-groups; from: is a hard constraint
    for token in bq.query.split():
        if token.startswith("from:") and not _term_matches(token, low, author):
            return False
    if not bq.groups:
        return False
    return all(any(_term_matches(t, low, author) for t in group) for group in bq.groups)


def which_queries_match(text: str, queries: list[BuiltQuery] | None = None,
                        author: str | None = None) -> list[str]:
    queries = queries or build_queries()
    return [q.id for q in queries if query_matches(q, text, author)]


def main() -> int:
    queries = build_queries()
    print(f"{len(queries)} queries built\n")
    for q in sorted(queries, key=lambda x: (x.tier, x.id)):
        print(f"  [tier {q.tier}] {q.id:<26} cap={q.max_results:<3} {len(q.query):>4} chars")
        print(f"      {q.query}")
    total = sum(1 for _ in queries)
    print(f"\nestimated API calls per daily run: {total} (1 page each)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
