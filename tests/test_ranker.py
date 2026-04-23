from bot.ranker import rank


def _gen_trades(
    wallet: str,
    n: int,
    is_winner: bool,
    start_ts: int = 0,
    end_ts: int = 10_000,
    market: str = "M1",
):
    """Generate n round-trips evenly spread over [start_ts, end_ts) so wallets with
    different n still share the same time range — the ranker's global 80/20 split
    would otherwise squeeze short-history wallets entirely out of OOS."""
    trades = []
    span = max(1, (end_ts - start_ts) // n)
    for i in range(n):
        ts = start_ts + i * span
        if is_winner:
            buy_p, sell_p = 0.40, 0.50
        else:
            buy_p, sell_p = 0.60, 0.50
        trades.append({"wallet": wallet, "market_id": market, "ts": ts, "side": "BUY", "size": 10, "price": buy_p})
        trades.append({"wallet": wallet, "market_id": market, "ts": ts + 1, "side": "SELL", "size": 10, "price": sell_p})
    return trades


def test_winner_wallet_included():
    # 200 round-trips all winning → 100 IS events (on 80/20 split 200 trades → 160 IS = 80 pairs)
    # Each pair is fully closed within its window as long as split respects timestamp ordering.
    # Use enough to satisfy MIN_IS (100 closed) and MIN_OOS (20 closed).
    trades = _gen_trades("alice", n=150, is_winner=True)
    out = rank(trades)
    assert len(out) == 1
    assert out[0]["wallet"] == "alice"
    assert out[0]["oos_pnl"] > 0
    assert out[0]["oos_win_rate"] >= 0.65


def test_loser_wallet_excluded():
    trades = _gen_trades("bob", n=150, is_winner=False)
    out = rank(trades)
    assert out == []


def test_low_volume_wallet_excluded():
    # 50 round-trips only — under MIN_IS_CLOSED_EVENTS=100
    trades = _gen_trades("charlie", n=50, is_winner=True)
    out = rank(trades)
    assert out == []


def test_category_filter_drops_wrong_categories():
    crypto = _gen_trades("alice", n=150, is_winner=True, market="M_CRYPTO")
    sports = _gen_trades("bob", n=150, is_winner=True, market="M_SPORTS")
    cats = {"M_CRYPTO": "crypto", "M_SPORTS": "sports"}
    out = rank(crypto + sports, category_filter="crypto", market_categories=cats)
    wallets = {r["wallet"] for r in out}
    assert "alice" in wallets
    assert "bob" not in wallets


def test_ranking_order_by_oos_pnl():
    a = _gen_trades("alice", n=200, is_winner=True)
    b = _gen_trades("bob", n=150, is_winner=True)
    out = rank(a + b)
    assert [r["wallet"] for r in out] == ["alice", "bob"]
