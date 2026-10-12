from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Market:
    venue: str  # "polymarket" | "kalshi"
    id: str
    label: str  # short outcome label within its event
    question: str
    bid: float | None  # best price to SELL yes at (what a seller receives), 0..1
    ask: float | None  # best price to BUY yes at, 0..1
    last: float | None = None
    volume_24h: float | None = None
    rules: str = ""  # resolution criteria, shown side by side when matching venues
    end_date: str | None = None

    @property
    def ref(self) -> str:
        return f"{self.venue}:{self.id}"

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None and self.ask >= self.bid:
            return (self.bid + self.ask) / 2
        return self.last if self.last is not None else (self.bid if self.bid is not None else self.ask)

    @property
    def spread(self) -> float | None:
        return None if self.bid is None or self.ask is None else self.ask - self.bid


@dataclass
class Event:
    venue: str
    id: str
    title: str
    markets: list[Market] = field(default_factory=list)
    exclusive: bool = False  # at most one market resolves Yes
    exhaustive: bool = False  # exactly one market resolves Yes (sum of Yes probabilities is 1)
    end_date: str | None = None
