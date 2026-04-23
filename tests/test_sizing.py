from bot.sizing import full_kelly_fraction, kelly_size


def test_full_kelly_zero_when_price_out_of_range():
    assert full_kelly_fraction(0.8, 0.0) == 0.0
    assert full_kelly_fraction(0.8, 1.0) == 0.0
    assert full_kelly_fraction(0.8, -0.1) == 0.0


def test_full_kelly_negative_ev_returns_zero():
    # at p=0.3, price=0.7: b = 1/0.7 - 1 ≈ 0.428, q=0.7
    # f = (0.3*0.428 - 0.7)/0.428 < 0 → clamp 0
    assert full_kelly_fraction(0.3, 0.7) == 0.0


def test_full_kelly_matches_formula():
    # p=0.82, price=0.65: b = 1/0.65 - 1 ≈ 0.5385
    # f = (0.82*0.5385 - 0.18)/0.5385 ≈ (0.4416 - 0.18)/0.5385 ≈ 0.4858
    f = full_kelly_fraction(0.82, 0.65)
    assert 0.48 < f < 0.50


def test_kelly_size_applies_quarter_multiplier_and_cap():
    # With raw f ≈ 0.49, quarter-Kelly = 0.122, below 0.25 cap.
    # $800 bankroll * 0.122 ≈ $97.7 — but MAX_POSITION_USD default is $10 so capped.
    s = kelly_size(0.82, 0.65, bankroll_usd=800.0)
    assert s == 10.0  # capped at MAX_POSITION_USD


def test_kelly_size_zero_when_negative_ev():
    assert kelly_size(0.3, 0.7, bankroll_usd=1000.0) == 0.0


def test_half_position_halves_size():
    full = kelly_size(0.82, 0.65, bankroll_usd=800.0)
    half = kelly_size(0.82, 0.65, bankroll_usd=800.0, half_position=True)
    assert half == round(full * 0.5, 2)


def test_kelly_size_respects_small_bankroll():
    # $20 bankroll, quarter-Kelly fraction ~0.122 → $2.44
    s = kelly_size(0.82, 0.65, bankroll_usd=20.0)
    assert 2.0 < s < 3.0
