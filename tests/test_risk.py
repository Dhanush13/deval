from bot.config import CFG
from bot.risk import AccountState, Block, check


def _state(**kw) -> AccountState:
    base = AccountState(
        bankroll_usd=50.0,
        peak_bankroll_usd=50.0,
        realized_pnl_today_usd=0.0,
        open_positions=0,
        exposure_per_event_usd={},
        cash_available_usd=50.0,
    )
    for k, v in kw.items():
        setattr(base, k, v)
    return base


def test_blocks_on_daily_loss_limit():
    st = _state(realized_pnl_today_usd=-CFG.daily_loss_limit_usd - 0.01)
    d = check(st, 5.0, "E1")
    assert not d.allowed
    assert d.block == Block.DAILY_LOSS


def test_blocks_on_drawdown():
    st = _state(peak_bankroll_usd=100.0, bankroll_usd=80.0)  # 20% drawdown
    d = check(st, 5.0, "E1")
    assert not d.allowed
    assert d.block == Block.DRAWDOWN


def test_blocks_on_open_positions_cap():
    st = _state(open_positions=CFG.max_open_positions)
    d = check(st, 5.0, "E1")
    assert not d.allowed
    assert d.block == Block.OPEN_CAP


def test_caps_size_to_max_position():
    st = _state()
    d = check(st, intended_size_usd=999.0, event_id="E1")
    assert d.allowed
    assert d.size_usd == CFG.max_position_usd


def test_caps_to_remaining_event_headroom():
    st = _state(exposure_per_event_usd={"E1": CFG.max_per_event_usd - 3.0})
    d = check(st, intended_size_usd=50.0, event_id="E1")
    assert d.allowed
    assert d.size_usd == 3.0


def test_blocks_when_event_already_full():
    st = _state(exposure_per_event_usd={"E1": CFG.max_per_event_usd})
    d = check(st, intended_size_usd=5.0, event_id="E1")
    assert not d.allowed
    assert d.block == Block.EVENT_CAP


def test_blocks_when_no_cash():
    st = _state(cash_available_usd=0.0)
    d = check(st, intended_size_usd=5.0, event_id="E1")
    assert not d.allowed
    assert d.block == Block.BANKROLL


def test_allows_clean_order():
    st = _state()
    d = check(st, intended_size_usd=5.0, event_id="E1")
    assert d.allowed
    assert d.block == Block.OK
    assert d.size_usd == 5.0
