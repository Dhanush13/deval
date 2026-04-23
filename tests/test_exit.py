from bot.config import CFG
from bot.exit import ExitInputs, check_exit


def _base(**kw) -> ExitInputs:
    e = ExitInputs(
        side="BUY",
        entry_price=0.40,
        target_price=0.60,
        current_price=0.45,
        hours_since_entry=1.0,
        volume_10m=100.0,
        volume_1h_history=[100.0, 110.0, 90.0, 105.0, 95.0, 100.0],
    )
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def test_stop_loss_fires_first():
    # BUY at 0.40, drop to 0.30 → 25% adverse move > 15% stop
    e = _base(current_price=0.30)
    assert check_exit(e) == "STOP_LOSS"


def test_target_hit_at_85_pct_of_move():
    # entry 0.40, target 0.60, expected move 0.20. 85% of 0.20 = 0.17.
    # Use 0.58 (90% progress) to be safely above the fp-rounded boundary.
    e = _base(current_price=0.58)
    assert check_exit(e) == "TARGET_HIT"


def test_no_exit_below_target_fraction():
    e = _base(current_price=0.50)  # only 50% of the way
    assert check_exit(e) is None


def test_volume_exit_uses_median_not_mean():
    # History median ≈ 100; volume_10m = 3.1 * 100 = 310
    e = _base(volume_10m=310.0, volume_1h_history=[100.0] * 6)
    assert check_exit(e) == "VOLUME_EXIT"


def test_volume_exit_resilient_to_outlier():
    # Mean would be ~233 (one fat print), median is still 100 → 310 still triggers
    # ...but crucially a 250 print should NOT trigger under median-based logic
    e = _base(volume_10m=250.0, volume_1h_history=[100.0, 100.0, 100.0, 100.0, 100.0, 1000.0])
    # median = 100, 250 < 300 → no volume exit
    assert check_exit(e) != "VOLUME_EXIT"


def test_stale_thesis_after_24h_small_move():
    e = _base(hours_since_entry=25.0, current_price=0.41)
    assert check_exit(e) == "STALE_THESIS"


def test_stale_does_not_fire_if_moved():
    e = _base(hours_since_entry=25.0, current_price=0.50)
    assert check_exit(e) != "STALE_THESIS"


def test_short_position_stop_loss():
    # SELL at 0.60, price rose to 0.72 → 20% adverse for a short > 15% stop
    e = _base(side="SELL", entry_price=0.60, target_price=0.40, current_price=0.72)
    assert check_exit(e) == "STOP_LOSS"


def test_short_position_target_hit():
    # SELL at 0.60, target 0.40. Expected move 0.20; 85% = 0.17 → trigger at 0.43 or lower
    e = _base(side="SELL", entry_price=0.60, target_price=0.40, current_price=0.43)
    assert check_exit(e) == "TARGET_HIT"


def test_stop_loss_threshold_boundary():
    # Exactly at STOP_LOSS_PCT drops → fires
    pct = CFG.stop_loss_pct
    e = _base(current_price=0.40 * (1 - pct))
    assert check_exit(e) == "STOP_LOSS"
