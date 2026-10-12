# coherence-scanner

> Find where linked prediction markets contradict each other.

**Status:** v0.1 core built: read-only snapshots, coherence checks, fair-value projection, relations file. No LLM matcher yet. No trading, ever. · Portfolio project #12 · see `../README.md`

## The idea

Related prices must obey probability rules: mutually exclusive outcomes sum to about 1, P(A and B) can't exceed P(A), and the same event on two venues should trade at the same price. A gap that survives fees is either a mispricing or a resolution-rule difference, and both are worth knowing.

## Before you start

ACMA has blocked Polymarket in Australia. This is a research project on read-only public data: **don't trade**. Public on-chain data (Dune or a Polygon RPC node) is a legitimate fallback if API endpoints aren't reachable.

## Stack

Python (uv), httpx, pandas, SciPy (constrained optimisation), an LLM via tool calling (local or Claude), pytest.

Python project managed with `uv`; target a one-command run (`uv run ...`).

## Build plan (v1)

- [ ] (partly done: **top-of-book bid/ask only, no full order books yet**; both public APIs are reachable from here) Snapshot open markets and order books from Polymarket and Kalshi
- [ ] (not built: `propose` uses fuzzy title matching only and prints both venues' resolution rules side by side) LLM agent proposes cross-venue matches and nested relationships, showing each pair's resolution criteria side by side
- [x] Human approval step; approved matches stored as versioned YAML
- [x] Coherence checks: exclusive sets, nesting, cross-venue equality
- [x] Fair value: project prices onto the nearest coherent set (minimise KL divergence under the constraints)
- [ ] (partly done: net of modelled fees and spread, **not depth-aware**) Edge report net of fees, spread and actual order-book depth

## Run it

```bash
uv sync
uv run coherence-scanner scan             # snapshot both venues, print violations
uv run coherence-scanner propose          # suggest cross-venue pairs for review
uv run pytest -q                          # 23 tests
```

Read-only public endpoints, no keys. This is research: **do not trade** (ACMA has blocked Polymarket in Australia).

## How I know it's right

- **Synthetic incoherent book**: 50 random 5-outcome books (Dirichlet truth × 15 % log-normal noise). Projection onto "sums to 1" always sums to 1 and lands closer to the truth on average than the raw noisy prices (tested).
- Projection leaves a coherent book unchanged, enforces `P(A) ≤ P(B)` and `P(A) = P(B)`, and works on a real recorded negRisk event.
- Checks are tested on hand-built books, including: wide spreads give deviation without edge; sell/buy direction; Kalshi fee schedule.
- **Live negRisk sum check** (500 Polymarket events, 167 exhaustive negRisk sets with 3 or more priced markets): median sum of mids 1.006, p5 0.972, p95 1.133; **69 % within ±3 % of 1**. The other 31 % are mostly sets that are not truly exhaustive in the listed outcomes (ranges, missing buckets) or that have stale quotes, so a deviation is a prompt to read the market, not evidence of mispricing. (That explanation is my reading; I have not checked the 31 % one by one.)
- **A bug the live data caught**: "augmented" negRisk events (e.g. Republican Presidential Nominee 2028: 128 markets, 43 active, listed sum 0.83) have inactive placeholder outcomes, so the listed outcomes need not sum to 1. They were first reported as a +0.147 "edge". They are now treated as exclusive but not exhaustive (regression test).
- After that fix (and a review that stopped counting coherent books and unpriced markets as violations): **168 incoherent sets (|deviation| > 0.01 or an edge), 10 with a positive edge at the touch after modelled fees**. None checked by hand, and since depth is ignored they are candidates, not opportunities. Exhaustive sets with an unpriced outcome make no claim at all, unresolved or mistyped approved relations are reported, and an empty or unpriced snapshot is an error (exit 2), not "no violations".

**Not done**: match precision/recall (no matcher yet) and cross-venue results (no approved relations yet).

## Limits

Fees are modelled (Kalshi's published schedule, none for Polymarket) and may be out of date. Prices are best bid/ask at snapshot time; thin or stale books produce phantom edges.

Research on read-only public data. A violation may reflect different resolution rules rather than mispricing; the report says which.

## Next (tomorrow)

- Order-book depth from Polymarket's CLOB `/book` and Kalshi's order-book endpoint; recompute edges at realistic size.
- LLM matcher (Ollama or Claude) with a hand-labelled match set; hand-review the 10 candidates.
- Nesting relations (e.g. "wins by more than 5 pts" implies "wins").

## Stretch

Rebuild fills from Polygon on-chain data to measure how long violations persist.

## Definition of done

- [ ] Hero GIF or screenshot at the top of this README
- [x] Live demo link or one-command run (`uv run coherence-scanner scan`)
- [ ] "How I know it's right" section filled in with real results
- [ ] Tests passing in CI, badge added
- [ ] "Limits" section written
- [ ] Licence chosen, repo description and topics set
- [ ] Pinned on GitHub profile and added to guinerve.github.io
- [ ] Added to `career-radar/data/cv/portfolio.json`
