"""The rules automation may not break.

Everything here is deliberately boring, deterministic Python. No model output
reaches these functions as a decision — only as data to be checked.

Two guardrails carry most of the weight:

* **The field allowlist.** `scripts/schema.py` will happily validate a record
  where `impact` and `assessment` were both written together, so the schema
  alone cannot stop an automated editorial write. The prohibition has to live
  where mutations are decided (ARCHITECTURE_ASSESSMENT §2.6).

* **The corroboration gate.** A social post with no external identifier may not
  become a candidate on its own. Measured base rate: only 3 of 20 live tweets
  carried any identifier at all, so without this the candidate store would be
  ~85% unverifiable material within days (§2.1).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "automation.json"


class PolicyViolation(RuntimeError):
    """Raised when a proposed mutation would break an editorial guarantee.

    This is a bug-catcher, not a control-flow tool: reaching it means code tried
    to do something the project promises it never does.
    """


def load_policy(path: Path | None = None) -> dict:
    cfg = json.loads((path or CONFIG).read_text(encoding="utf-8"))
    return cfg.get("policy", {})


def never_auto_write(policy: dict | None = None) -> set[str]:
    policy = policy if policy is not None else load_policy()
    return set(policy.get("neverAutoWriteFields", []))


# --------------------------------------------------------------------------
# field allowlist
# --------------------------------------------------------------------------

def assert_no_editorial_write(
    before: dict[str, Any], after: dict[str, Any], policy: dict | None = None
) -> None:
    """Fail loudly if a protected field changed.

    Applied to every curated record the pipeline touches, before anything is
    written. `status` is protected in one direction only — automation may never
    promote *to* `audited`, because that is the claim the whole site rests on.
    """
    protected = never_auto_write(policy)
    for field in protected:
        old, new = before.get(field), after.get(field)
        if old == new:
            continue
        if field == "status":
            raise PolicyViolation(
                f"automation attempted to change status {old!r} → {new!r}; "
                "curated status is a human decision"
            )
        raise PolicyViolation(
            f"automation attempted to write protected field {field!r} ({old!r} → {new!r})"
        )


def assert_registry_untouched(before: list[dict], after: list[dict]) -> None:
    """The strongest guarantee this project makes: automation never edits the
    curated registry at all — not a field, not a record, not an ordering."""
    if before != after:
        b = {r["id"]: r for r in before}
        a = {r["id"]: r for r in after}
        added = set(a) - set(b)
        removed = set(b) - set(a)
        changed = {i for i in set(a) & set(b) if a[i] != b[i]}
        raise PolicyViolation(
            "automation modified data/results.json — "
            f"added={sorted(added)} removed={sorted(removed)} changed={sorted(changed)}"
        )


# --------------------------------------------------------------------------
# corroboration gate
# --------------------------------------------------------------------------

CORROBORATING_KINDS = ("arxiv", "doi", "oeis", "erdos", "github", "lean")


def has_corroboration(obs: dict) -> bool:
    """Is there anything outside the post itself that points at the claim?"""
    ids = obs.get("externalIds") or {}
    return any(ids.get(k) for k in CORROBORATING_KINDS)


def may_become_candidate(obs: dict, policy: dict | None = None) -> tuple[bool, str]:
    """Whether an observation may create a candidate, and why not if it may not."""
    policy = policy if policy is not None else load_policy()

    if not policy.get("requireCorroborationForCandidate", True):
        return True, "corroboration gate disabled in config"

    if has_corroboration(obs):
        kinds = [k for k in CORROBORATING_KINDS if (obs.get("externalIds") or {}).get(k)]
        return True, f"corroborated by {', '.join(kinds)}"

    return False, (
        "no external identifier — a social post alone is not evidence, so this "
        "goes to review rather than becoming a candidate"
    )


def meets_confidence(obs: dict, policy: dict | None = None) -> tuple[bool, str]:
    policy = policy if policy is not None else load_policy()
    floor = float(policy.get("minExtractionConfidence", 0.5))
    got = float(obs.get("extractionConfidence") or 0.0)
    if got >= floor:
        return True, f"confidence {got:.2f} ≥ {floor:.2f}"
    return False, f"extraction confidence {got:.2f} below floor {floor:.2f}"
