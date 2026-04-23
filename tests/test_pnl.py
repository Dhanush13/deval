import pytest

from bot.pnl import reconcile, win_rate


def T(wallet, mid, ts, side, size, price):
    return {"wallet": wallet, "market_id": mid, "ts": ts, "side": side, "size": size, "price": price}


def test_simple_winning_round_trip():
    # Buy 100 @ 0.40, sell 100 @ 0.60 → +20
    trades = [
        T("alice", "M1", 1, "BUY", 100, 0.40),
        T("alice", "M1", 2, "SELL", 100, 0.60),
    ]
    s = reconcile(trades)["alice"]
    assert s.realized_pnl == pytest.approx(20.0)
    assert s.wins == 1
    assert s.losses == 0
    assert win_rate(s) == 1.0


def test_simple_losing_round_trip():
    trades = [
        T("alice", "M1", 1, "BUY", 100, 0.60),
        T("alice", "M1", 2, "SELL", 100, 0.40),
    ]
    s = reconcile(trades)["alice"]
    assert s.realized_pnl == pytest.approx(-20.0)
    assert s.wins == 0
    assert s.losses == 1


def test_fifo_partial_fills():
    # Buy 50@0.40, buy 50@0.50, sell 80@0.55
    # First 50 close @ 0.55 from 0.40 → +7.5
    # Next 30 close @ 0.55 from 0.50 → +1.5
    # Total +9.0, two closing events (both wins).
    trades = [
        T("alice", "M1", 1, "BUY", 50, 0.40),
        T("alice", "M1", 2, "BUY", 50, 0.50),
        T("alice", "M1", 3, "SELL", 80, 0.55),
    ]
    s = reconcile(trades)["alice"]
    assert round(s.realized_pnl, 4) == 9.0
    assert s.wins == 2
    assert s.closed_events == 2


def test_sell_more_than_held_opens_short():
    # Buy 50@0.40, sell 100@0.55
    # Close 50 @ 0.55 vs 0.40 → +7.5
    # Open short 50 @ 0.55
    trades = [
        T("alice", "M1", 1, "BUY", 50, 0.40),
        T("alice", "M1", 2, "SELL", 100, 0.55),
    ]
    stats = reconcile(trades)
    s = stats["alice"]
    assert round(s.realized_pnl, 4) == 7.5
    # Now cover the short at 0.50 → short profits +2.5
    stats2 = reconcile(trades + [T("alice", "M1", 3, "BUY", 50, 0.50)])
    assert round(stats2["alice"].realized_pnl, 4) == 10.0


def test_different_markets_do_not_cross():
    # SELL on M2 should not close a BUY on M1
    trades = [
        T("alice", "M1", 1, "BUY", 100, 0.40),
        T("alice", "M2", 2, "SELL", 100, 0.55),
    ]
    s = reconcile(trades)["alice"]
    # M1 long still open (no mark), M2 short opened — both unrealized
    assert s.realized_pnl == 0.0
    assert s.closed_events == 0


def test_mark_to_final_captures_unrealized():
    trades = [T("alice", "M1", 1, "BUY", 100, 0.40)]
    s = reconcile(trades, mark_to_final={"M1": 1.0})["alice"]
    # 100 tokens @ 0.40 cost, resolved at $1.00 → +60
    assert round(s.realized_pnl, 4) == 60.0


def test_multiple_wallets_are_independent():
    trades = [
        T("alice", "M1", 1, "BUY", 100, 0.40),
        T("alice", "M1", 2, "SELL", 100, 0.60),
        T("bob", "M1", 3, "BUY", 100, 0.70),
        T("bob", "M1", 4, "SELL", 100, 0.50),
    ]
    stats = reconcile(trades)
    assert stats["alice"].realized_pnl == pytest.approx(20.0)
    assert stats["bob"].realized_pnl == pytest.approx(-20.0)
