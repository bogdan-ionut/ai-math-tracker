"""External identifier extraction.

These identifiers are the backbone of deterministic matching: when two records
carry the same arXiv id or the same Erdős number, we know they are about the
same thing without asking a model. Extraction is therefore deliberately strict —
a false positive here would merge two unrelated problems.

Everything returned is normalised so that string equality is a valid comparison.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 2604.03789 / 2604.03789v2 — modern arXiv ids. Also the legacy math.AG/0601001 form.
_ARXIV_NEW = re.compile(r"\b(?:arxiv[:\s/]*)?(\d{4}\.\d{4,5})(v\d+)?\b", re.I)
_ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})(v\d+)?", re.I)
_ARXIV_OLD = re.compile(r"\b([a-z-]+(?:\.[A-Z]{2})?)/(\d{7})(v\d+)?\b")

# DOIs: 10.<registrant>/<suffix>
_DOI = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b", re.I)

# OEIS sequence ids
_OEIS = re.compile(r"\b(A\d{6})\b")

# Erdős problem numbers — require nearby context so a bare "#12" is not captured.
_ERDOS_CTX = re.compile(
    r"erd(?:os|ős|ös)[^.\n]{0,40}?#\s*(\d{1,4})|#\s*(\d{1,4})[^.\n]{0,30}?erd(?:os|ős|ös)",
    re.I,
)
_ERDOS_URL = re.compile(r"erdosproblems\.com/(?:forum/thread/)?(\d{1,4})", re.I)

# GitHub repositories (owner/repo) — used for Lean artifacts and code drops.
_GITHUB = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.I)

_LEAN_HINTS = ("lean", "mathlib", "formal")


@dataclass
class ExternalIds:
    """Normalised identifiers found in a piece of text or a set of links."""

    arxiv: list[str] = field(default_factory=list)
    doi: list[str] = field(default_factory=list)
    oeis: list[str] = field(default_factory=list)
    erdos: list[str] = field(default_factory=list)
    github: list[str] = field(default_factory=list)
    lean: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            (self.arxiv, self.doi, self.oeis, self.erdos, self.github, self.lean)
        )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "arxiv": self.arxiv,
            "doi": self.doi,
            "oeis": self.oeis,
            "erdos": self.erdos,
            "github": self.github,
            "lean": self.lean,
        }

    def overlaps(self, other: "ExternalIds") -> bool:
        """True if any identifier of the same kind is shared."""
        a, b = self.to_dict(), other.to_dict()
        return any(set(a[k]) & set(b[k]) for k in a)

    def conflicts_with(self, other: "ExternalIds") -> bool:
        """True if both carry the same *kind* of identifier but none match.

        Used as a hard stop: records with conflicting explicit identifiers must
        never be merged, regardless of what a model thinks.
        """
        a, b = self.to_dict(), other.to_dict()
        for k in a:
            if a[k] and b[k] and not (set(a[k]) & set(b[k])):
                return True
        return False


def _dedupe(seq: list[str]) -> list[str]:
    return sorted(set(seq))


def extract_identifiers(text: str | None, links: list[str] | None = None) -> ExternalIds:
    """Extract normalised external identifiers from text plus expanded links."""
    blob = " ".join(filter(None, [text or "", " ".join(links or [])]))
    if not blob.strip():
        return ExternalIds()

    arxiv = [m.group(1) for m in _ARXIV_URL.finditer(blob)]
    # Only accept bare numeric ids when "arxiv" is mentioned — otherwise a date
    # like 2604.03 or a version string would be captured.
    if "arxiv" in blob.lower():
        arxiv += [m.group(1) for m in _ARXIV_NEW.finditer(blob)]
    arxiv += [f"{m.group(1)}/{m.group(2)}" for m in _ARXIV_OLD.finditer(blob)]

    doi = [m.group(1).rstrip(".,);").lower() for m in _DOI.finditer(blob)]
    oeis = [m.group(1).upper() for m in _OEIS.finditer(blob)]

    erdos = [m.group(1) for m in _ERDOS_URL.finditer(blob)]
    for m in _ERDOS_CTX.finditer(blob):
        num = m.group(1) or m.group(2)
        if num:
            erdos.append(num)

    github: list[str] = []
    lean: list[str] = []
    for m in _GITHUB.finditer(blob):
        owner, repo = m.group(1), m.group(2)
        if repo.lower().endswith(".git"):
            repo = repo[:-4]
        slug = f"{owner.lower()}/{repo.lower()}"
        github.append(slug)
        if any(h in slug for h in _LEAN_HINTS) or any(
            h in blob.lower() for h in ("lean 4", "lean4", "mathlib")
        ):
            lean.append(slug)

    return ExternalIds(
        arxiv=_dedupe(arxiv),
        doi=_dedupe(doi),
        oeis=_dedupe(oeis),
        erdos=_dedupe(erdos),
        github=_dedupe(github),
        lean=_dedupe(lean),
    )


def normalize_title(title: str | None) -> str:
    """Fold a problem title to a comparable key.

    Lowercase, strip diacritics on the common Erdős spellings, collapse
    punctuation and whitespace, drop leading articles.
    """
    if not title:
        return ""
    t = title.lower()
    for a, b in (("ő", "o"), ("ö", "o"), ("ø", "o"), ("é", "e"), ("è", "e"), ("ü", "u")):
        t = t.replace(a, b)
    t = re.sub(r"[^a-z0-9#]+", " ", t)
    t = re.sub(r"\b(the|a|an|on|of)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()
