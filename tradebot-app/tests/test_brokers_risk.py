import pytest

from tests.helpers import FakeMarketData, make_position
from tradebot import risk
from tradebot.brokers import OrderRejected, PaperBroker, simulate_market_fill
from tradebot.market_data import OrderBook, SymbolRules
from tradebot.models import ExitPlan, Signal
from tradebot.settings import BotConfig as Settings
from tradebot.store import Store


def _broker(market="futures", fee=0.001, price=100.0, cash=1000.0):
    store = Store(":memory:")
    md = FakeMarketData(market)
    md.prices["BTCUSDT"] = price
    broker = PaperBroker(market, store, md, fee_rate=fee, max_slippage=0.005)
    broker.ensure_wallet(cash)
    return broker, md


def test_fill_walks_the_book():
    book = OrderBook(bids=[(99, 1)], asks=[(100, 1), (101, 1), (102, 10)])
    assert simulate_market_fill(book, True, 2) == pytest.approx(100.5)
    assert simulate_market_fill(book, True, 1) == pytest.approx(100.0)


def test_fill_beyond_depth_is_pessimistic():
    book = OrderBook(bids=[(99, 1)], asks=[(100, 1)])
    assert simulate_market_fill(book, True, 2) == pytest.approx((100 + 100.5) / 2)


def test_open_and_close_long_accounting():
    broker, md = _broker(fee=0.001)
    fill = broker.open("BTCUSDT", "long", 2, 100)
    assert broker.cash() == pytest.approx(1000 - 200 - 0.2)
    md.prices["BTCUSDT"] = 110
    p = make_position(qty=2, entry_price=fill.price, entry_fee=fill.fee)
    close = broker.close(p)
    assert broker.cash() == pytest.approx(1000 - 0.2 + 20 - 0.22)
    p.exit_price, p.exit_fee = close.price, close.fee
    assert p.net_pnl() == pytest.approx(20 - 0.2 - 0.22)


def test_short_profits_when_price_falls():
    broker, md = _broker()
    broker.open("BTCUSDT", "short", 1, 100)
    md.prices["BTCUSDT"] = 90
    broker.close(make_position(direction="short", qty=1, entry_price=100))
    assert broker.cash() == pytest.approx(1000 + 10 - 0.1 - 0.09)


def test_equity_marks_open_positions_to_market():
    broker, _ = _broker(fee=0.0)
    broker.open("BTCUSDT", "long", 1, 100)
    assert broker.equity([make_position(qty=1)], {"BTCUSDT": 105}) == pytest.approx(1005)


def test_rejects_without_cash_and_on_slippage():
    broker, md = _broker(cash=50)
    with pytest.raises(OrderRejected, match="Saldo"):
        broker.open("BTCUSDT", "long", 1, 100)
    md.prices["BTCUSDT"] = 101  # livro 1% acima da referência
    with pytest.raises(OrderRejected, match="Slippage"):
        broker.open("BTCUSDT", "long", 0.1, 100)


def _signal(direction="long", entry=100.0, stop=98.0):
    return Signal("BTCUSDT", direction, entry, ExitPlan(stop_loss=stop), "t", "test")


def test_position_size_risks_configured_percent():
    s = Settings()
    qty = risk.position_size(_signal(), equity=1000, cash=1000, settings=s)
    assert qty == pytest.approx(2.5)  # o risco pediria 5, mas o teto de 25% (250 USDT) limita a 2,5
    s.risk.max_position_pct = 100
    qty = risk.position_size(_signal(), equity=1000, cash=1000, settings=s)
    assert qty == pytest.approx(5.0)  # 1% de 1000 = 10 USDT / 2 USDT por unidade


def test_check_entry_limits():
    s = Settings()
    assert not risk.check_entry(_signal("short"), "spot", s, [], 0).allowed
    assert risk.check_entry(_signal("short"), "futures", s, [], 0).allowed
    opened = [make_position(symbol=f"S{i}USDT") for i in range(2)]
    decision = risk.check_entry(_signal(), "futures", s, opened, 0)
    assert not decision.allowed and "long" in decision.reason
    assert not risk.check_entry(_signal(), "futures", s, [make_position()], 0).allowed  # mesmo par
    assert not risk.check_entry(_signal(), "futures", s, [], s.risk.max_trades_per_day).allowed


def _closed(reason, at, pnl=-10.0, symbol="BTCUSDT"):
    p = make_position(symbol=symbol, status="closed", exit_reason=reason, closed_at_ms=at,
                      exit_price=100 + pnl, entry_price=100, qty=1)
    return p


DAY = 1_750_000_000_000 - 1_750_000_000_000 % 86_400_000


def test_daily_loss_protection():
    s = Settings()
    closed = [_closed("stop_loss", DAY + 1000, pnl=-31), _closed("take_profit", DAY - 5000, pnl=+100)]
    reason = risk.active_protection(s, closed, 970, 1000, 1000, DAY + 2000)
    assert reason and "perda diária" in reason


def test_stoploss_streak_pauses_then_releases():
    s = Settings()
    s.protections.daily_loss_limit_pct = 50
    t = DAY + 3_600_000
    closed = [_closed("stop_loss", t + i * 60_000, pnl=-1) for i in range(3)]
    assert "stops seguidos" in risk.active_protection(s, closed, 997, 1000, 1000, t + 5 * 60_000)
    assert risk.active_protection(s, closed, 997, 1000, 1000, t + 200 * 60_000) is None
    closed.append(_closed("take_profit", t + 4 * 60_000, pnl=+1))
    assert risk.active_protection(s, closed, 997, 1000, 1000, t + 5 * 60_000) is None


def test_drawdown_protection():
    s = Settings()
    assert "Drawdown" in risk.active_protection(s, [], 840, 1000, 900, DAY)
    assert risk.active_protection(s, [], 860, 1000, 900, DAY) is None


def test_symbol_cooldown():
    s = Settings()
    closed = [_closed("stop_loss", 1_000_000)]
    assert risk.symbol_in_cooldown(s, "BTCUSDT", closed, 1_000_000 + 30 * 60_000)
    assert not risk.symbol_in_cooldown(s, "BTCUSDT", closed, 1_000_000 + 61 * 60_000)
    assert not risk.symbol_in_cooldown(s, "ETHUSDT", closed, 1_000_000)


def test_halt_file(tmp_path):
    assert not risk.is_halted(tmp_path)
    risk.set_halt(tmp_path, "teste")
    assert risk.is_halted(tmp_path)
    risk.clear_halt(tmp_path)
    assert not risk.is_halted(tmp_path)


def test_round_qty_floors_to_step():
    rules = SymbolRules(step_size=0.001, min_qty=0.001, min_notional=5, tick_size=0.01)
    assert rules.round_qty(1.23456) == pytest.approx(1.234)


def test_settings_roundtrip_and_validation():
    s = Settings()
    s.risk.risk_per_trade_pct = 0.5
    s.strategy_params = {"ema_cross": {"atr_stop": 2}}
    again = Settings.from_dict(s.to_dict())
    assert again.risk.risk_per_trade_pct == 0.5
    assert again.params()["atr_stop"] == 2
    bad = s.to_dict()
    bad["risk"]["risk_per_trade_pct"] = 50
    with pytest.raises(ValueError):
        Settings.from_dict(bad)
    assert Settings.from_dict({"desconhecido": 1, "strategy": "nao_existe"}).strategy == "ema_cross"
