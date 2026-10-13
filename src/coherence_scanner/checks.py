"""Coherence checks. All prices are probabilities in 0..1 for the Yes side of each market.

Two views of every violation:
  deviation  - how far mid prices are from satisfying the rule (is the book incoherent?)
  edge       - what a round trip at the touch would leave after fees (is it executable?)
A deviation without an edge is usually just spread; an edge is rare and should be read with the
resolution rules next to it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .models import Event, Market


def kalshi_fee(price: float, contracts: int = 1) -> float:
    """Kalshi's published taker fee schedule: round_up(0.07 x C x P x (1 - P)) in dollars (approximate)."""
    return math.ceil(0.07 * contracts * price * (1 - price) * 100) / 100


def fee_for(market: Market, price: float) -> float:
    return kalshi_fee(price) if market.venue == "kalshi" else 0.0  # Polymarket: most markets carry no taker fee


@dataclass
class Violation:
    kind: str  # "exclusive_sum" | "nesting" | "cross_venue"
    title: str
    deviation: float  # signed: how far mids are outside the rule
    edge: float  # best executable profit per $1 payoff after fees; <= 0 means none
    legs: list[str] = field(default_factory=list)
    note: str = ""


def check_exclusive(event: Event) -> Violation | None:
    ms = [m for m in event.markets if m.mid is not None]
    if not event.exclusive or len(ms) < 2:
        return None
    if event.exhaustive and len(ms) < len(event.markets):
        return None  # an unpriced outcome could be the winner: neither the sum nor a buy-all edge means anything
    mid_sum = sum(m.mid for m in ms if m.mid is not None)
    asks = [m.ask for m in ms if m.ask is not None]
    bids = [m.bid for m in ms if m.bid is not None]
    all_asks, all_bids = len(asks) == len(ms), len(bids) == len(ms)
    edge, legs, note = 0.0, [], ""
    if event.exhaustive:
        deviation = mid_sum - 1
        if all_asks:  # buy Yes on everything: exactly one pays $1
            cost = sum(a + fee_for(m, a) for m, a in zip(ms, asks, strict=True))
            if 1 - cost > edge:
                edge, legs = 1 - cost, [f"BUY YES {m.ref} @ {a:.3f}" for m, a in zip(ms, asks, strict=True)]
    else:  # at most one resolves yes: only a sum above 1 is a violation
        deviation = max(0.0, mid_sum - 1)
        note = "not exhaustive: sum below 1 is allowed"
    if all_bids:  # sell Yes on everything: at most one pays $1
        proceeds = sum(b - fee_for(m, b) for m, b in zip(ms, bids, strict=True))
        if proceeds - 1 > edge:
            edge, legs = proceeds - 1, [f"SELL YES {m.ref} @ {b:.3f}" for m, b in zip(ms, bids, strict=True)]
    if not event.exhaustive and deviation == 0 and edge <= 0:
        return None
    return Violation("exclusive_sum", f"{event.venue}: {event.title}", deviation, edge, legs, note)


def check_nesting(a: Market, b: Market, why: str = "") -> Violation | None:
    """If A implies B then P(A) <= P(B). Violation when A is priced above B. None if either is unpriced."""
    if a.mid is None or b.mid is None:
        return None
    dev = a.mid - b.mid
    edge, legs = 0.0, []
    if a.bid is not None and b.ask is not None:  # sell A, buy B: B pays whenever A does
        edge = a.bid - fee_for(a, a.bid) - b.ask - fee_for(b, b.ask)
        legs = [f"SELL YES {a.ref} @ {a.bid:.3f}", f"BUY YES {b.ref} @ {b.ask:.3f}"]
    return Violation("nesting", f"{a.label} implies {b.label}", max(0.0, dev), edge, legs, why)


def check_cross_venue(a: Market, b: Market, why: str = "") -> Violation | None:
    """Same event on two venues should trade at the same price. None if either is unpriced."""
    if a.mid is None or b.mid is None:
        return None
    dev = a.mid - b.mid
    cands: list[tuple[float, list[str]]] = []
    if a.bid is not None and b.ask is not None:
        cands.append((a.bid - fee_for(a, a.bid) - b.ask - fee_for(b, b.ask), [f"SELL YES {a.ref} @ {a.bid:.3f}", f"BUY YES {b.ref} @ {b.ask:.3f}"]))
    if b.bid is not None and a.ask is not None:
        cands.append((b.bid - fee_for(b, b.bid) - a.ask - fee_for(a, a.ask), [f"SELL YES {b.ref} @ {b.bid:.3f}", f"BUY YES {a.ref} @ {a.ask:.3f}"]))
    edge, legs = max(cands, key=lambda c: c[0]) if cands else (0.0, [])
    return Violation("cross_venue", f"{a.ref} vs {b.ref}: {a.label}", dev, edge, legs, why)
