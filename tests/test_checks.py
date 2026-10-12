import json
from pathlib import Path

import numpy as np
import pytest

from coherence_scanner import checks, relations
from coherence_scanner.models import Event, Market
from coherence_scanner.project import project
from coherence_scanner.venues import parse_kalshi_event, parse_polymarket_event

FIX = Path(__file__).parent / "fixtures"


def mk(venue, id_, bid, ask, label=None):
    return Market(venue, id_, label or id_, f"Question {id_}", bid, ask)


# ---------- parsing real recorded payloads ----------
def test_polymarket_negrisk_event_is_exclusive_and_exhaustive():
    e = parse_polymarket_event(json.loads((FIX / "polymarket_negrisk.json").read_text())[0])
    assert e.exclusive and e.exhaustive and len(e.markets) >= 3
    assert all(0 <= m.mid <= 1 for m in e.markets)
    total = sum(m.mid for m in e.markets)
    assert 0.9 < total < 1.1  # negRisk sets sum to ~1


def test_kalshi_exclusive_event_is_not_assumed_exhaustive():
    e = parse_kalshi_event(json.loads((FIX / "kalshi_exclusive.json").read_text())[0])
    assert e.exclusive and not e.exhaustive
    assert all(m.venue == "kalshi" and m.bid is not None for m in e.markets)


def test_augmented_negrisk_events_are_not_treated_as_exhaustive():
    """Regression: a live augmented event had 43 active of 128 markets, listed sum 0.83. Not an arbitrage."""
    raw = {"id": "1", "title": "Nominee", "negRisk": True, "enableNegRisk": True, "negRiskAugmented": True,
           "markets": [{"id": "a", "question": "A?", "outcomePrices": '["0.40","0.60"]', "bestBid": 0.39, "bestAsk": 0.41, "active": True, "closed": False},
                       {"id": "b", "question": "B?", "outcomePrices": '["0.43","0.57"]', "bestBid": 0.42, "bestAsk": 0.44, "active": True, "closed": False},
                       {"id": "other", "question": "Other?", "outcomePrices": None, "bestBid": 0, "bestAsk": 1, "active": False, "closed": False}]}
    e = parse_polymarket_event(raw)
    assert e.exclusive and not e.exhaustive and len(e.markets) == 2  # inactive placeholder dropped
    assert checks.check_exclusive(e) is None  # 0.83 listed is fine for a non-exhaustive set


# ---------- exclusive sets ----------
def test_coherent_exhaustive_set_has_no_edge():
    e = Event("polymarket", "1", "t", [mk("polymarket", "a", .39, .41), mk("polymarket", "b", .29, .31), mk("polymarket", "c", .29, .31)], True, True)
    v = checks.check_exclusive(e)
    assert v.deviation == pytest.approx(0.0, abs=1e-9) and v.edge <= 0


def test_exhaustive_set_priced_over_one_gives_a_sell_edge_only_if_bids_clear():
    e = Event("polymarket", "1", "t", [mk("polymarket", "a", .55, .57), mk("polymarket", "b", .50, .52)], True, True)
    v = checks.check_exclusive(e)
    assert v.deviation == pytest.approx(0.07, abs=1e-9) and v.edge == pytest.approx(0.05) and v.legs[0].startswith("SELL")


def test_wide_spreads_mean_deviation_without_edge():
    e = Event("polymarket", "1", "t", [mk("polymarket", "a", .30, .70), mk("polymarket", "b", .30, .70)], True, True)
    v = checks.check_exclusive(e)
    assert v.deviation == pytest.approx(0.0) and v.edge < 0 or v.edge == 0


def test_underpriced_exhaustive_set_gives_a_buy_edge():
    e = Event("polymarket", "1", "t", [mk("polymarket", "a", .40, .42), mk("polymarket", "b", .40, .42)], True, True)
    v = checks.check_exclusive(e)
    assert v.edge == pytest.approx(0.16) and v.legs[0].startswith("BUY")


def test_non_exhaustive_set_only_flags_sums_above_one():
    under = Event("kalshi", "k", "t", [mk("kalshi", "a", .2, .3), mk("kalshi", "b", .2, .3)], True, False)
    assert checks.check_exclusive(under) is None
    over = Event("kalshi", "k", "t", [mk("kalshi", "a", .6, .7), mk("kalshi", "b", .6, .7)], True, False)
    assert checks.check_exclusive(over).deviation > 0


# ---------- nesting / cross venue ----------
def test_nesting_violation_needs_bid_above_ask():
    a, b = mk("polymarket", "a", .62, .64), mk("polymarket", "b", .55, .57)
    v = checks.check_nesting(a, b)
    assert v.deviation == pytest.approx(0.07) and v.edge == pytest.approx(0.62 - 0.57)
    ok = checks.check_nesting(mk("polymarket", "a", .30, .32), mk("polymarket", "b", .50, .52))
    assert ok.deviation == 0 and ok.edge < 0


def test_cross_venue_picks_the_profitable_direction_and_charges_kalshi_fees():
    p, k = mk("polymarket", "p", .60, .62), mk("kalshi", "k", .50, .52)
    v = checks.check_cross_venue(p, k)
    fee = checks.kalshi_fee(0.52)
    assert v.legs[0].startswith("SELL YES polymarket") and v.legs[1].startswith("BUY YES kalshi")
    assert v.edge == pytest.approx(0.60 - 0.52 - fee)


def test_kalshi_fee_schedule():
    assert checks.kalshi_fee(0.50) == 0.02  # 0.07 * 0.25 = 0.0175 -> rounds up to 2 cents
    assert checks.kalshi_fee(0.99) == 0.01


# ---------- fair-value projection ----------
def test_projection_leaves_a_coherent_book_unchanged():
    p = [0.5, 0.3, 0.2]
    q = project(p, exhaustive_sets=[[0, 1, 2]])
    assert np.allclose(q, p, atol=1e-4)


def test_projection_recovers_known_coherent_probabilities_from_a_noisy_book():
    """Synthetic incoherent book: coherent truth + multiplicative noise. Projection should land closer to the truth."""
    rng = np.random.default_rng(7)
    errs_before, errs_after = [], []
    for _ in range(50):
        truth = rng.dirichlet(np.ones(5))
        noisy = np.clip(truth * rng.lognormal(0, 0.15, 5), 0.01, 0.99)
        q = project(noisy, exhaustive_sets=[list(range(5))])
        assert q.sum() == pytest.approx(1.0, abs=1e-5)
        errs_before.append(np.abs(noisy - truth).mean())
        errs_after.append(np.abs(q - truth).mean())
    assert np.mean(errs_after) < np.mean(errs_before)


def test_projection_enforces_nesting_and_equality():
    q = project([0.7, 0.5], implies=[(0, 1)])
    assert q[0] <= q[1] + 1e-6 and q[0] == pytest.approx(q[1], abs=1e-3) and 0.5 < q[0] < 0.7
    q2 = project([0.4, 0.6], equal=[(0, 1)])
    assert q2[0] == pytest.approx(q2[1], abs=1e-5) and 0.4 < q2[0] < 0.6


def test_projection_on_a_real_negrisk_event_sums_to_one():
    e = parse_polymarket_event(json.loads((FIX / "polymarket_negrisk.json").read_text())[0])
    q = project([m.mid for m in e.markets], exhaustive_sets=[list(range(len(e.markets)))])
    assert q.sum() == pytest.approx(1.0, abs=1e-5)


# ---------- relations ----------
def test_relations_round_trip_and_only_approved_are_scanned(tmp_path):
    from coherence_scanner.cli import scan

    path = tmp_path / "r.yaml"
    relations.save(path, [relations.Relation("r1", "equivalent", "polymarket:p", "kalshi:k", "approved"),
                          relations.Relation("r2", "equivalent", "polymarket:p", "kalshi:k2", "proposed")])
    rels = relations.load(path)
    assert [r.status for r in rels] == ["approved", "proposed"]
    poly = [Event("polymarket", "e", "e", [mk("polymarket", "p", .6, .62)])]
    kal = [Event("kalshi", "e", "e", [mk("kalshi", "k", .5, .52), mk("kalshi", "k2", .1, .12)])]
    out = scan(poly, kal, rels)
    assert [v.kind for v in out] == ["cross_venue"]


def test_unknown_relation_version_is_rejected(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("version: 99\nrelations: []\n")
    with pytest.raises(ValueError):
        relations.load(p)


def test_unpriced_market_is_not_treated_as_zero():
    a, b = Market("polymarket", "a", "a", "q", None, None), mk("polymarket", "b", .55, .57)
    assert checks.check_nesting(a, b) is None and checks.check_cross_venue(b, a) is None


def test_exhaustive_set_with_an_unpriced_outcome_makes_no_claim():
    e = Event("polymarket", "1", "t", [mk("polymarket", "a", .30, .32), mk("polymarket", "b", .30, .32),
                                       Market("polymarket", "c", "c", "q", None, None)], True, True)
    assert checks.check_exclusive(e) is None


def test_unresolvable_or_malformed_relations_are_reported_not_silent():
    from coherence_scanner.cli import scan

    msgs = []
    rels = [relations.Relation("r1", "equivalent", "polymarket:gone", "kalshi:k", "approved"),
            relations.Relation("r2", "equivalent", "polymarket:p", "kalshi:k", "aproved"),
            relations.Relation("r3", "implys", "polymarket:p", "kalshi:k", "approved")]
    poly = [Event("polymarket", "e", "e", [mk("polymarket", "p", .6, .62)])]
    kal = [Event("kalshi", "e", "e", [mk("kalshi", "k", .5, .52)])]
    assert scan(poly, kal, rels, warn=msgs.append) == []
    assert len(msgs) == 3


def test_projection_failure_raises(monkeypatch):
    import scipy.optimize

    class R:
        success, message, x = False, "infeasible", None
    monkeypatch.setattr("coherence_scanner.project.minimize", lambda *a, **k: R())
    with pytest.raises(ValueError):
        project([0.5, 0.5], exhaustive_sets=[[0, 1]])


def test_coherent_sets_are_not_counted_as_violations():
    from coherence_scanner.cli import scan

    coherent = Event("polymarket", "1", "t", [mk("polymarket", "a", .39, .41), mk("polymarket", "b", .59, .61)], True, True)
    assert scan([coherent], [], []) == []


def test_save_creates_missing_directory(tmp_path):
    relations.save(tmp_path / "data" / "r.yaml", [])
    assert (tmp_path / "data" / "r.yaml").exists()
