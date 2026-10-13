from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import httpx
import yaml

from . import checks, relations, venues
from .models import Event, Market


def snapshot(pages: int) -> tuple[list[Event], list[Event]]:
    with httpx.Client(timeout=30, headers={"User-Agent": "coherence-scanner/0.1 (read-only research)"}) as http:
        return venues.fetch_polymarket(http, pages), venues.fetch_kalshi(http, pages)


def index(events: list[Event]) -> dict[str, Market]:
    return {m.ref: m for e in events for m in e.markets}


TOLERANCE = 0.01  # sums within 1 cent of coherent are not reported
VALID_STATUS = {"proposed", "approved", "rejected"}
VALID_TYPE = {"equivalent", "implies"}


def scan(poly: list[Event], kal: list[Event], rels: list[relations.Relation],
         warn=lambda msg: print(msg, file=sys.stderr)) -> list[checks.Violation]:
    out: list[checks.Violation] = []
    for e in [*poly, *kal]:
        v = checks.check_exclusive(e)
        if v and _incoherent(v):
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
        elif _incoherent(v):
            out.append(v)
    return out


def _incoherent(v: checks.Violation) -> bool:
    """A book within the tolerance and with no edge is coherent, so it is not reported."""
    return abs(v.deviation) > TOLERANCE or v.edge > 0


def _positive_int(text: str) -> int:
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return n


def _err(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(
        prog="coherence-scanner",
        description="Find where linked prediction markets contradict each other. "
        "The tool reads public market data only. It never places trades.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="Take a snapshot of both venues and report incoherent prices")
    s.add_argument("--pages", type=_positive_int, default=3,
                   help="pages of 100 events to read from each venue (default: 3)")
    s.add_argument("--relations", type=Path, default=Path("data/relations.yaml"),
                   help="file of approved market pairs (default: data/relations.yaml)")
    s.add_argument("--top", type=int, default=15, help="rows to show in the table (default: 15)")
    s.add_argument("--json", type=Path, help="write all violations to this JSON file")
    pr = sub.add_parser("propose", help="Suggest pairs of matching markets for a person to review")
    pr.add_argument("--pages", type=_positive_int, default=2,
                    help="pages of 100 events to read from each venue (default: 2)")
    pr.add_argument("--relations", type=Path, default=Path("data/relations.yaml"),
                    help="file to add the proposals to (default: data/relations.yaml)")
    pr.add_argument("--threshold", type=int, default=85,
                    help="minimum title similarity, 0 to 100 (default: 85)")
    args = p.parse_args(argv)

    try:
        rels = relations.load(args.relations)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        _err(f"could not read the relations file: {exc}")
        return 2
    try:
        poly, kal = snapshot(args.pages)
    except httpx.HTTPError as exc:
        _err(f"could not read market data ({type(exc).__name__}: {exc}). No report was made.")
        return 2
    priced = sum(1 for e in [*poly, *kal] for m in e.markets if m.mid is not None)
    total = sum(len(e.markets) for e in [*poly, *kal])
    print(f"snapshot: {len(poly)} Polymarket events, {len(kal)} Kalshi events, "
          f"{priced}/{total} markets priced", file=sys.stderr)
    if not poly or not kal or priced == 0:
        _err("a venue returned no events or no usable prices. The API may have changed or be down. "
             "This is not a clean result, so no report was made.")
        return 2

    if args.cmd == "propose":
        seen = {(r.a, r.b) for r in rels}
        new: list[relations.Relation] = []
        for a, b, score in relations.propose_matches(poly, kal, args.threshold):
            if (a.ref, b.ref) in seen:
                continue
            print(f"\n[{score:.0f}] {a.ref}\n     {a.question}\n   ~ {b.ref}\n     {b.question}")
            print(f"   Polymarket rules: {a.rules[:200].strip()!r}\n   Kalshi rules:     {b.rules[:200].strip()!r}")
            new.append(relations.Relation(relations.next_id(rels + new), "equivalent", a.ref, b.ref, "proposed"))
        relations.save(args.relations, rels + new)
        sys.stdout.flush()
        print(f"\n{len(new)} proposals added to {args.relations}. "
              "Read each pair, then set status to 'approved' for the pairs you trust.", file=sys.stderr)
        return 0

    viol = scan(poly, kal, rels)
    viol.sort(key=lambda v: (-v.edge, -abs(v.deviation)))
    print(f"{'kind':14s} {'dev':>7s} {'edge':>7s}  title")
    for v in viol[: args.top]:
        print(f"{v.kind:14s} {v.deviation:+7.3f} {v.edge:+7.3f}  {v.title[:80]}")
    sys.stdout.flush()
    n_edge = sum(1 for v in viol if v.edge > 0)
    print(f"\n{len(viol)} incoherent sets. {n_edge} show a positive edge at the best quotes after modelled fees.\n"
          "Quotes are top of book only and ignore depth. This is research output, not advice to trade.",
          file=sys.stderr)
    if args.json:
        args.json.write_text(json.dumps([v.__dict__ for v in viol], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
