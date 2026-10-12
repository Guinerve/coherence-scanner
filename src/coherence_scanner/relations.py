"""Versioned relations file. A relation is only used once a human has set `status: approved`.

relations:
  - id: r1
    type: equivalent | implies          # implies: a => b
    a: polymarket:12345
    b: kalshi:KXTICKER-26
    status: proposed | approved | rejected
    note: free text (why, or the resolution-rule difference that matters)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from .models import Event, Market

VERSION = 1


@dataclass
class Relation:
    id: str
    type: str
    a: str
    b: str
    status: str = "proposed"
    note: str = ""


def load(path: Path) -> list[Relation]:
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text()) or {}
    if doc.get("version", VERSION) != VERSION:
        raise ValueError(f"{path}: unsupported relations version {doc.get('version')}")
    return [Relation(**r) for r in doc.get("relations", [])]


def save(path: Path, relations: list[Relation]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"version": VERSION, "relations": [r.__dict__ for r in relations]}
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))


def propose_matches(poly: list[Event], kalshi: list[Event], threshold: int = 82) -> list[tuple[Market, Market, float]]:
    """Candidate cross-venue pairs by title similarity. A cheap first pass for a human or an LLM to review."""
    out = []
    pm = [m for e in poly for m in e.markets]
    km = [m for e in kalshi for m in e.markets]
    for a in pm:
        best, best_s = None, 0.0
        for b in km:
            s = fuzz.token_set_ratio(a.question, b.question)
            if s > best_s:
                best, best_s = b, s
        if best and best_s >= threshold:
            out.append((a, best, best_s))
    return sorted(out, key=lambda t: -t[2])
