"""Motor de ponta a ponta com mercado falso e uma estratégia de teste controlável."""
import pytest

from tests.helpers import FakeMarketData, make_candles
from tradebot import risk
from tradebot.engine import Engine
from tradebot.models import ExitPlan, Signal
from tradebot.settings import BotConfig
from tradebot.store import Store
from tradebot.strategies import STRATEGIES
from tradebot.strategies.base import Param, Strategy

MIN = 60_000
T0 = 1_750_000_000_000 - 1_750_000_000_000 % (15 * MIN)


class ScriptedStrategy(Strategy):
    name = "scripted"
    label = "teste"
    params = {"timeframe": Param("15m", "tf", "choice", choices=("15m",))}

    def __init__(self):
        self.fire: dict[str, str] = {}  # symbol -> direção
        self.exit_symbols: set[str] = set()

    def warmup(self, p):
        return 5

    def generate(self, symbol, candles, htf, p):
        direction = self.fire.pop(symbol, None)
        if not direction:
            return None
        entry = candles[-1].close
        stop = entry * (0.98 if direction == "long" else 1.02)
        tp = entry * (1.04 if direction == "long" else 0.96)
        return Signal(symbol, direction, entry, ExitPlan(stop_loss=stop, take_profit=tp), "script", self.name)

    def should_exit(self, position, candles, p):
        return position.symbol in self.exit_symbols


@pytest.fixture
def setup(tmp_path, monkeypatch):
    strategy = ScriptedStrategy()
    monkeypatch.setitem(STRATEGIES, strategy.name, strategy)
    store = Store(":memory:")
    s = BotConfig()
    s.strategy = strategy.name
    s.markets["spot"].enabled = False
    s.symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    s.risk.max_position_pct = 100
    store.set_json("settings", s.to_dict())  # formato da versão 1: vira o robô 1 (testa a migração)
    md = FakeMarketData("futures")
    for sym in s.symbols:
        md.candles[(sym, "15m")] = make_candles([100.0] * 30, start_ms=T0 - 30 * 15 * MIN)
        md.prices[sym] = 100.0
    engine = Engine(store, tmp_path, market_data={"spot": FakeMarketData("spot"), "futures": md})
    return engine, strategy, md, store


def _next_candle_time(k: int) -> int:
    return T0 + k * 15 * MIN + 10_000  # 10s depois do fechamento (passa do CANDLE_SETTLE_MS)


def test_first_tick_after_start_does_not_enter_on_old_candle(setup):
    engine, strategy, md, store = setup
    engine.start(1)
    strategy.fire["BTCUSDT"] = "long"
    engine.tick(_next_candle_time(0))
    assert store.open_positions("paper") == []


def test_opens_sizes_and_closes_on_stop(setup):
    engine, strategy, md, store = setup
    engine.start(1)
    engine.tick(_next_candle_time(0))
    strategy.fire["BTCUSDT"] = "long"
    engine.tick(_next_candle_time(1))
    [p] = store.open_positions("paper")
    assert p.direction == "long" and p.stop_loss == pytest.approx(98.0)
    # 1% de 1000 = 10 USDT de risco / 2 USDT por unidade = 5 unidades
    assert p.qty == pytest.approx(5.0)
    md.prices["BTCUSDT"] = 97.9
    engine.tick(_next_candle_time(1) + 10_000)
    assert store.open_positions("paper") == []
    [closed] = store.closed_positions("paper", 1)
    assert closed.exit_reason == "stop_loss"
    assert closed.r_multiple() < -1  # bateu o stop e ainda pagou taxa


def test_pause_blocks_entries_but_manages_exits(setup):
    engine, strategy, md, store = setup
    engine.start(1)
    engine.tick(_next_candle_time(0))
    strategy.fire["BTCUSDT"] = "long"
    engine.tick(_next_candle_time(1))
    engine.pause_entries(1)
    strategy.fire["ETHUSDT"] = "long"
    engine.tick(_next_candle_time(2))
    assert [p.symbol for p in store.open_positions("paper")] == ["BTCUSDT"]
    md.prices["BTCUSDT"] = 104.5
    engine.tick(_next_candle_time(2) + 10_000)
    assert store.closed_positions("paper", 1)[0].exit_reason == "take_profit"


def test_strategy_exit_on_candle_close(setup):
    engine, strategy, md, store = setup
    engine.start(1)
    engine.tick(_next_candle_time(0))
    strategy.fire["BTCUSDT"] = "short"
    engine.tick(_next_candle_time(1))
    strategy.exit_symbols.add("BTCUSDT")
    engine.tick(_next_candle_time(1) + 20_000)  # mesmo candle: nada
    assert store.open_positions("paper")
    engine.tick(_next_candle_time(2))
    assert store.closed_positions("paper", 1)[0].exit_reason == "strategy_exit"


def test_emergency_close_all_halts(setup):
    engine, strategy, md, store = setup
    engine.start(1)
    engine.tick(_next_candle_time(0))
    strategy.fire.update({"BTCUSDT": "long", "ETHUSDT": "short"})
    engine.tick(_next_candle_time(1))
    assert len(store.open_positions("paper")) == 2
    assert engine.emergency_close_all() == 2
    assert store.open_positions("paper") == []
    assert risk.is_halted(engine.data_dir)
    engine.start(1)
    strategy.fire["SOLUSDT"] = "long"
    engine.tick(_next_candle_time(2))
    engine.tick(_next_candle_time(3))
    assert store.open_positions("paper") == []  # kill switch segura mesmo com o bot ligado
    engine.release_halt()
    strategy.fire["SOLUSDT"] = "long"
    engine.tick(_next_candle_time(4))
    assert len(store.open_positions("paper")) == 1


def test_denied_entries_are_logged(setup):
    engine, strategy, md, store = setup
    engine.start(1)
    engine.tick(_next_candle_time(0))
    strategy.fire.update({"BTCUSDT": "long", "ETHUSDT": "long", "SOLUSDT": "long"})
    engine.tick(_next_candle_time(1))
    assert len(store.open_positions("paper")) == 2  # max 2 por direção
    assert any(e["kind"] == "denied" for e in store.recent_events())


def test_manual_close_and_wallet_reset(setup):
    engine, strategy, md, store = setup
    engine.start(1)
    engine.tick(_next_candle_time(0))
    strategy.fire["BTCUSDT"] = "long"
    engine.tick(_next_candle_time(1))
    [p] = store.open_positions("paper")
    with pytest.raises(ValueError):
        engine.reset_wallet(1, "futures")
    assert engine.close_position(p.id)
    engine.reset_wallet(1, "futures")
    assert engine.bots[1].brokers["futures"].cash() == pytest.approx(1000)
    assert store.closed_positions("paper", 1) == []


def test_state_persists_across_restart(setup, tmp_path):
    engine, strategy, md, store = setup
    engine.pause_entries(1)
    again = Engine(store, tmp_path, market_data=engine.data)
    assert again.bots[1].state == "paused"


def test_network_errors_are_not_logged_every_cycle(setup):
    engine, strategy, md, store = setup

    def boom():
        raise ConnectionError("sem internet")
    md.last_prices = boom
    engine.start(1)
    for k in range(10):
        engine.tick(_next_candle_time(0) + k * 10_000)
    errors = [e for e in store.recent_events() if e["kind"] == "error"]
    assert len(errors) == 1
    assert "sem internet" in engine.last_error


def test_bots_are_isolated_wallets_and_limits(setup):
    engine, strategy, md, store = setup
    cfg = BotConfig.from_dict(engine.bots[1].config.to_dict() | {"name": "segundo"})
    cfg.risk.max_open_per_direction = 1
    second = engine.create_bot(cfg)
    engine.start(1)
    engine.start(second)
    engine.tick(_next_candle_time(0))
    # a estratégia de teste é a mesma instância: dispara pros dois robôs no mesmo ciclo
    strategy.fire.update({"BTCUSDT": "long"})
    engine.tick(_next_candle_time(1))
    first_open = store.open_positions("paper", 1)
    second_open = store.open_positions("paper", second)
    assert len(first_open) + len(second_open) == 1  # o sinal é consumido pelo primeiro robô que o vê
    # carteiras separadas: só quem abriu gastou caixa
    owner = 1 if first_open else second
    other = second if owner == 1 else 1
    assert engine.bots[owner].brokers["futures"].cash() < 1000
    assert engine.bots[other].brokers["futures"].cash() == pytest.approx(1000)


def test_each_bot_has_own_state_and_emergency_hits_all(setup):
    engine, strategy, md, store = setup
    second = engine.create_bot(BotConfig.from_dict(engine.bots[1].config.to_dict() | {"name": "b2"}))
    engine.start(1)
    assert engine.bots[1].state == "running" and engine.bots[second].state == "stopped"
    engine.tick(_next_candle_time(0))
    strategy.fire["BTCUSDT"] = "long"
    engine.tick(_next_candle_time(1))
    engine.start(second)
    engine.tick(_next_candle_time(2))
    strategy.fire["ETHUSDT"] = "long"
    engine.tick(_next_candle_time(3))
    assert store.open_positions("paper", 1) and len(store.open_positions("paper")) == 2
    assert engine.emergency_close_all() == 2
    assert all(b.state == "paused" for b in engine.bots.values())


def test_delete_bot_rules(setup):
    engine, strategy, md, store = setup
    with pytest.raises(ValueError):
        engine.delete_bot(1)  # último robô
    second = engine.create_bot(BotConfig.from_dict(engine.bots[1].config.to_dict() | {"name": "b2"}))
    engine.start(second)
    engine.tick(_next_candle_time(0))
    strategy.fire["BTCUSDT"] = "long"
    engine.tick(_next_candle_time(1))
    holder = second if store.open_positions("paper", second) else 1
    with pytest.raises(ValueError):
        engine.delete_bot(holder)
    [p] = store.open_positions("paper", holder)
    engine.close_position(p.id)
    engine.delete_bot(second)
    assert second not in engine.bots
    assert store.closed_positions("paper", second) == []


def test_candles_are_shared_between_bots_in_a_cycle(setup):
    engine, strategy, md, store = setup
    calls = []
    original = md.klines
    md.klines = lambda *a, **k: calls.append(a) or original(*a, **k)
    second = engine.create_bot(BotConfig.from_dict(engine.bots[1].config.to_dict() | {"name": "b2"}))
    engine.start(1)
    engine.start(second)
    engine.tick(_next_candle_time(0))
    engine.tick(_next_candle_time(1))
    assert len(calls) == len(set(calls)) == 3  # 3 pares, 1 chamada cada, mesmo com 2 robôs
