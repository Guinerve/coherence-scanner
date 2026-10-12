from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import httpx

from . import checks, relations, venues
from .models import Event, Market
from .project import project


def snapshot(pages: int) -> tuple[list[Event], list[Event]]:
    with httpx.Client(timeout=30, headers={"User-Agent": "coherence-scanner/0.1 (read-only research)"}) as http:
        return venues.fetch_polymarket(http, pages), venues.fetch_kalshi(http, pages)


def index(events: list[Event]) -> dict[str, Market]:
    return {m.ref: m for e in events for m in e.markets}


TOLERANCE = 0.01  # sums within 1 cent of coherent are not reported
VALID_STATUS = {"proposed", "approved", "rejected"}
VALID_TYPE = {"equivalent", "implies"}


def scan(poly: list[Event], kal: list[Event], rels: list[relations.Relation],
         warn=lambda msg: print(msg, file=sys.stderr)) -> list[checks.Violation]:  # noqa: ANN001
    out: list[checks.Violation] = []
    for e in [*poly, *kal]:
        v = checks.check_exclusive(e)
        if v and (abs(v.deviation) > TOLERANCE or v.edge > 0):  # a coherent book is not a violation
            out.append(v)
    idx = index([*poly, *kal])
    for r in rels:
        if r.status not in VALID_STATUS or r.type not in VALID_TYPE:
            warn(f"relation {r.id}: unknown status {r.status!r} or type {r.type!r}; skipped")
            continue
        if r.status != "approved":
            continue
        if r.a not in idx or r.b not in idx:
            warn(f"relation {r.id}: {r.a if r.a not in idx else r.b} not in this snapshot (closed, renamed, or past the page limit); skipped")
            continue
        a, b = idx[r.a], idx[r.b]
        v = checks.check_cross_venue(a, b, r.note) if r.type == "equivalent" else checks.check_nesting(a, b, r.note)
        if v is None:
            warn(f"relation {r.id}: one side has no price; skipped")
        else:
            out.append(v)
    return out


def main(argv: list[str] | None = None) -> int:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="coherence-scanner", description="Read-only research on public prediction-market data. Do not trade.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="Snapshot both venues and report coherence violations")
    s.add_argument("--pages", type=int, default=3)
    s.add_argument("--relations", type=Path, default=Path("data/relations.yaml"))
    s.add_argument("--top", type=int, default=15)
    s.add_argument("--json", type=Path, help="Write all violations as JSON")
    pr = sub.add_parser("propose", help="Suggest cross-venue matches for human review")
    pr.add_argument("--pages", type=int, default=2)
    pr.add_argument("--relations", type=Path, default=Path("data/relations.yaml"))
    pr.add_argument("--threshold", type=int, default=85)
    args = p.parse_args(argv)

    poly, kal = snapshot(args.pages)
    priced = sum(1 for e in [*poly, *kal] for m in e.markets if m.mid is not None)
    total = sum(len(e.markets) for e in [*poly, *kal])
    print(f"snapshot: {len(poly)} Polymarket events, {len(kal)} Kalshi events, {priced}/{total} markets priced", file=sys.stderr)
    if not poly or not kal or priced == 0:
        print("ERROR: a venue returned no events or no usable prices (API change or outage?). Not reporting 'no violations'.", file=sys.stderr)
        return 2

    if args.cmd == "propose":
        existing = relations.load(args.relations)
        seen = {(r.a, r.b) for r in existing}
        new = []
        for a, b, score in relations.propose_matches(poly, kal, args.threshold):
            if (a.ref, b.ref) in seen:
                continue
            print(f"\n[{score:.0f}] {a.ref}\n     {a.question}\n   ~ {b.ref}\n     {b.question}")
            print(f"   Polymarket rules: {a.rules[:200].strip()!r}\n   Kalshi rules:     {b.rules[:200].strip()!r}")
            new.append(relations.Relation(f"r{len(existing) + len(new) + 1}", "equivalent", a.ref, b.ref, "proposed"))
        relations.save(args.relations, existing + new)
        print(f"\n{len(new)} proposals written to {args.relations}. Edit status to 'approved' for the ones you trust.", file=sys.stderr)
        return 0

    viol = scan(poly, kal, relations.load(args.relations))
    viol.sort(key=lambda v: (-v.edge, -abs(v.deviation)))
    print(f"{'kind':14s} {'dev':>7s} {'edge':>7s}  title")
    for v in viol[: args.top]:
        print(f"{v.kind:14s} {v.deviation:+7.3f} {v.edge:+7.3f}  {v.title[:80]}")
    n_edge = sum(1 for v in viol if v.edge > 0)
    print(f"\n{len(viol)} incoherent sets, {n_edge} with a positive edge at the touch after modelled fees (top-of-book only; not depth-aware).", file=sys.stderr)
    if args.json:
        args.json.write_text(json.dumps([v.__dict__ for v in viol], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
