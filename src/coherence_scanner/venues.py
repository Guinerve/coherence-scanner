"""Read-only snapshots from public market-data endpoints. No authentication, no order placement."""

from __future__ import annotations

import json

import httpx

from .models import Event, Market

GAMMA = "https://gamma-api.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"


def _f(x) -> float | None:  # noqa: ANN001
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


def parse_polymarket_event(e: dict) -> Event:
    markets = []
    for m in e.get("markets") or []:
        if m.get("closed") or m.get("active") is False:
            continue
        try:
            prices = json.loads(m.get("outcomePrices") or "[]")
        except json.JSONDecodeError:
            prices = []
        markets.append(Market(
            venue="polymarket", id=str(m["id"]), label=m.get("groupItemTitle") or m.get("question", ""),
            question=m.get("question", ""), bid=_f(m.get("bestBid")), ask=_f(m.get("bestAsk")),
            last=_f(prices[0]) if prices else _f(m.get("lastTradePrice")),
            volume_24h=_f(m.get("volume24hr")), rules=m.get("description") or e.get("description") or "",
            end_date=m.get("endDate") or e.get("endDate"),
        ))
    neg = bool(e.get("negRisk") or e.get("enableNegRisk"))
    # "Augmented" negRisk events carry inactive placeholder outcomes ("Person CY", "Other") that can be named
    # later, so the *listed* outcomes need not sum to 1. Found on a live event: 128 markets, 43 active, sum 0.83.
    augmented = bool(e.get("negRiskAugmented"))
    return Event("polymarket", str(e["id"]), e.get("title", ""), markets, exclusive=neg, exhaustive=neg and not augmented,
                 end_date=e.get("endDate"))


def parse_kalshi_event(e: dict) -> Event:
    markets = []
    for m in e.get("markets") or []:
        if m.get("status") not in (None, "active", "open"):
            continue
        markets.append(Market(
            venue="kalshi", id=m["ticker"], label=m.get("yes_sub_title") or m.get("title", ""),
            question=m.get("title", ""), bid=_f(m.get("yes_bid_dollars")), ask=_f(m.get("yes_ask_dollars")),
            last=_f(m.get("last_price_dollars")), volume_24h=_f(m.get("volume_24h_fp")),
            rules=(m.get("rules_primary") or "") + ("\n" + m["rules_secondary"] if m.get("rules_secondary") else ""),
            end_date=m.get("close_time"),
        ))
    # Kalshi's flag says at most one market resolves Yes; it does not promise that one must.
    return Event("kalshi", e["event_ticker"], e.get("title", ""), markets,
                 exclusive=bool(e.get("mutually_exclusive")), exhaustive=False)


def fetch_polymarket(http: httpx.Client, pages: int = 3, page_size: int = 100) -> list[Event]:
    out: list[Event] = []
    for p in range(pages):
        r = http.get(f"{GAMMA}/events", params={"active": "true", "closed": "false", "limit": page_size,
                                                 "offset": p * page_size, "order": "volume24hr", "ascending": "false"})
        r.raise_for_status()
        batch = r.json()
        out += [parse_polymarket_event(e) for e in batch]
        if len(batch) < page_size:
            break
    return out


def fetch_kalshi(http: httpx.Client, pages: int = 3, page_size: int = 100) -> list[Event]:
    out: list[Event] = []
    cursor = ""
    for _ in range(pages):
        params = {"limit": page_size, "status": "open", "with_nested_markets": "true"}
        if cursor:
            params["cursor"] = cursor
        r = http.get(f"{KALSHI}/events", params=params)
        r.raise_for_status()
        data = r.json()
        out += [parse_kalshi_event(e) for e in data.get("events", [])]
        cursor = data.get("cursor") or ""
        if not cursor:
            break
    return out
