"""Measure how close live Polymarket negRisk sets are to summing to 1, and draw a histogram.

Run from the repo root:  uv run --with matplotlib python scripts/negrisk_sums.py --out docs/negrisk-sums.png
The script reads public market data only.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import httpx
import numpy as np

from coherence_scanner.venues import fetch_polymarket


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pages", type=int, default=5, help="pages of 100 events (default: 5)")
    ap.add_argument("--out", type=Path, help="write a histogram PNG to this path")
    args = ap.parse_args()

    with httpx.Client(timeout=30, headers={"User-Agent": "coherence-scanner/0.1 (research, reads only)"}) as http:
        events = fetch_polymarket(http, args.pages)
    # Exhaustive sets with 3 or more outcomes, every one of them priced.
    sets = [e for e in events if e.exhaustive and len(e.markets) >= 3 and all(m.mid is not None for m in e.markets)]
    sums = np.array([sum(m.mid for m in e.markets) for e in sets])
    within = np.mean(np.abs(sums - 1) <= 0.03)
    p5, med, p95 = np.percentile(sums, [5, 50, 95])
    print(f"{len(events)} events, {len(sets)} exhaustive negRisk sets with 3 or more priced outcomes")
    print(f"sum of mids: median {med:.3f}, p5 {p5:.3f}, p95 {p95:.3f}; {within:.0%} within 0.03 of 1")

    if args.out:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        clipped = np.clip(sums, 0.8, 1.4)
        fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
        ax.axvspan(0.97, 1.03, color="#2a9d8f", alpha=0.15, lw=0, label="within 0.03 of 1")
        ax.hist(clipped, bins=np.arange(0.8, 1.4001, 0.01), color="#264653", edgecolor="white", lw=0.4)
        ax.axvline(1.0, color="#e76f51", lw=1.4, label="coherent (sum = 1)")
        ax.set_xlabel("sum of mid prices across the outcomes of one event (values outside 0.8 to 1.4 shown at the edge)")
        ax.set_ylabel("events")
        ax.set_title(f"Live Polymarket negRisk sets, {dt.date.today():%d %b %Y}: {len(sets)} events, "
                     f"median {med:.3f}, {within:.0%} within 0.03 of 1", fontsize=10, loc="left")
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, fontsize=8)
        fig.tight_layout()
        fig.savefig(args.out)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
