"""Copy trading: sincronização com a carteira copiada, tamanho sem alavancagem, análise e painel."""
import pytest
from fastapi.testclient import TestClient

from tests.helpers import FakeMarketData
from tradebot.engine import Engine
from tradebot.hyperliquid import LeaderPosition, LeaderState, analyze, binance_symbol, parse_state, valid_address
from tradebot.settings import BotConfig
from tradebot.store import Store
from tradebot.web.server import create_app

WALLET = "0x" + "ab" * 20
T0 = 1_750_000_000_000


class FakeHyperliquid:
    def __init__(self):
        self.account_value = 10_000.0
        self.positions: dict[str, LeaderPosition] = {}
        self.fail = False
        self.calls = 0

    def set(self, coin, direction, notional, leverage=1.0):
        self.positions[coin] = LeaderPosition(coin, direction, notional / 100, 100.0, notional, leverage, 0.0)

    def state(self, address):
        self.calls += 1
        if self.fail:
            raise ConnectionError("hyperliquid fora do ar")
        return LeaderState(address.lower(), self.account_value, dict(self.positions))

    def fills(self, address):
        return [
            {"coin": "BTC", "dir": "Open Long", "closedPnl": "0", "fee": "1", "time": T0},
            {"coin": "BTC", "dir": "Close Long", "closedPnl": "120", "fee": "1", "time": T0 + 86_400_000},
            {"coin": "ETH", "dir": "Close Short", "closedPnl": "-40", "fee": "1", "time": T0 + 2 * 86_400_000},
        ]

    def portfolio(self, address):
        return {"perpAllTime": {"pnlHistory": [[T0, "0"], [T0 + 1, "500"], [T0 + 2, "200"], [T0 + 3, "900"]],
                                "accountValueHistory": [[T0, "1000"], [T0 + 3, "2000"]]},
                "perpMonth": {"pnlHistory": [[T0, "100"], [T0 + 3, "400"]], "accountValueHistory": []}}

    def leaderboard(self, limit=25, window="month", min_account=0):
        return [{"address": WALLET, "name": "teste", "account_value": 1e6, "pnl": 5e4, "roi": 0.05, "all_time_pnl": 2e5}]


@pytest.fixture
def setup(tmp_path):
    store = Store(":memory:")
    md = FakeMarketData("futures")
    for coin, price in (("BTC", 100.0), ("ETH", 50.0), ("SOL", 10.0)):
        md.prices[f"{coin}USDT"] = price
    hl = FakeHyperliquid()
    engine = Engine(store, tmp_path, market_data={"spot": FakeMarketData("spot"), "futures": md}, hyperliquid=hl)
    cfg = BotConfig.from_dict({"name": "copia", "strategy": "copy_wallet", "markets": {"spot": {"enabled": False}},
                               "strategy_params": {"wallet": WALLET}, "risk": {"max_position_pct": 100}})
    bot_id = engine.create_bot(cfg)
    return engine, hl, md, store, bot_id


def test_symbol_mapping_and_address():
    assert binance_symbol("BTC") == "BTCUSDT"
    assert binance_symbol("kPEPE") == "1000PEPEUSDT"
    assert binance_symbol("xyz:TSLA") is None and binance_symbol("@107") is None
    assert valid_address(WALLET) and not valid_address("0x123") and not valid_address("")


def test_parse_real_response_format():
    raw = {"marginSummary": {"accountValue": "1000.5"}, "assetPositions": [
        {"type": "oneWay", "position": {"coin": "BTC", "szi": "-2.5", "leverage": {"type": "cross", "value": 5},
                                        "entryPx": "76331.0", "positionValue": "190000.0", "unrealizedPnl": "-10"}},
        {"type": "oneWay", "position": {"coin": "ETH", "szi": "0", "positionValue": "0"}}]}
    state = parse_state(WALLET, raw)
    assert state.account_value == 1000.5
    assert list(state.positions) == ["BTC"]
    btc = state.positions["BTC"]
    assert (btc.direction, btc.size, btc.leverage) == ("short", 2.5, 5)


def test_existing_positions_are_not_copied_only_new_ones(setup):
    engine, hl, md, store, bot_id = setup
    hl.set("BTC", "long", 5_000)
    engine.start(bot_id)
    engine.tick(T0)
    assert store.open_positions("paper", bot_id) == []  # já estava aberta ao ligar
    hl.set("ETH", "short", 2_000)
    engine.tick(T0 + 10_000)
    [p] = store.open_positions("paper", bot_id)
    assert (p.symbol, p.direction, p.extra["coin"]) == ("ETHUSDT", "short", "ETH")
    # 2000 de 10000 da carteira dele = 20%; × 90% de uso × 1000 nossos = 180 USDT
    assert p.qty * p.entry_price == pytest.approx(180, rel=0.01)
    assert p.stop_loss == pytest.approx(50 * 1.05)  # stop próprio de 5% acima (short)


def test_leader_close_and_flip(setup):
    engine, hl, md, store, bot_id = setup
    engine.start(bot_id)
    engine.tick(T0)
    hl.set("BTC", "long", 1_000)
    hl.set("SOL", "long", 1_000)
    engine.tick(T0 + 10_000)
    assert {p.symbol for p in store.open_positions("paper", bot_id)} == {"BTCUSDT", "SOLUSDT"}
    del hl.positions["BTC"]
    hl.set("SOL", "short", 1_000)  # inverteu
    engine.tick(T0 + 20_000)
    [p] = store.open_positions("paper", bot_id)
    assert (p.symbol, p.direction) == ("SOLUSDT", "short")
    reasons = {x.symbol: x.exit_reason for x in store.closed_positions("paper", bot_id)}
    assert reasons == {"BTCUSDT": "leader_exit", "SOLUSDT": "leader_exit"}


def test_leverage_is_scaled_down_to_1x(setup):
    engine, hl, md, store, bot_id = setup
    engine.start(bot_id)
    engine.tick(T0)
    # 5x: 50 mil em posições sobre 10 mil de patrimônio
    hl.set("BTC", "long", 30_000, leverage=5)
    hl.set("ETH", "long", 20_000, leverage=5)
    engine.bots[bot_id].config.risk.max_open_per_direction = 5
    engine.tick(T0 + 10_000)
    total = sum(p.qty * p.entry_price for p in store.open_positions("paper", bot_id))
    assert total == pytest.approx(900, rel=0.01)  # 90% do patrimônio, nunca mais que 1x
    assert engine.bots[bot_id].brokers["futures"].cash() > 0


def test_stop_exit_waits_for_leader_to_reopen(setup):
    engine, hl, md, store, bot_id = setup
    engine.start(bot_id)
    engine.tick(T0)
    hl.set("BTC", "long", 1_000)
    engine.tick(T0 + 10_000)
    md.prices["BTCUSDT"] = 94.0  # stop de 5%
    engine.tick(T0 + 20_000)
    assert store.closed_positions("paper", bot_id)[0].exit_reason == "stop_loss"
    md.prices["BTCUSDT"] = 100.0
    engine.tick(T0 + 30_000 + 3_600_000)  # passou o cooldown, mas ele ainda está na mesma posição
    assert store.open_positions("paper", bot_id) == []
    del hl.positions["BTC"]
    engine.tick(T0 + 40_000 + 3_600_000)
    hl.set("BTC", "long", 1_000)
    engine.tick(T0 + 50_000 + 3_600_000)
    assert len(store.open_positions("paper", bot_id)) == 1


def test_fetch_failure_never_closes_positions(setup):
    engine, hl, md, store, bot_id = setup
    engine.start(bot_id)
    engine.tick(T0)
    hl.set("BTC", "long", 1_000)
    engine.tick(T0 + 10_000)
    hl.fail = True
    engine.tick(T0 + 20_000)
    engine.tick(T0 + 30_000)
    assert len(store.open_positions("paper", bot_id)) == 1
    assert sum(1 for e in store.recent_events() if e["kind"] == "error") == 1  # erro registrado 1x


def test_unmapped_coin_is_skipped_and_logged_once(setup):
    engine, hl, md, store, bot_id = setup
    engine.start(bot_id)
    engine.tick(T0)
    hl.set("DOGE", "long", 1_000)  # sem preço no mercado falso = sem par na Binance
    engine.tick(T0 + 10_000)
    engine.tick(T0 + 20_000)
    assert store.open_positions("paper", bot_id) == []
    assert sum(1 for e in store.recent_events() if "sem par" in e["message"]) == 1


def test_paused_bot_still_follows_exits_but_not_entries(setup):
    engine, hl, md, store, bot_id = setup
    engine.start(bot_id)
    engine.tick(T0)
    hl.set("BTC", "long", 1_000)
    engine.tick(T0 + 10_000)
    engine.pause_entries(bot_id)
    hl.set("ETH", "long", 1_000)
    del hl.positions["BTC"]
    engine.tick(T0 + 20_000)
    assert store.open_positions("paper", bot_id) == []
    assert store.closed_positions("paper", bot_id)[0].exit_reason == "leader_exit"


def test_same_wallet_is_fetched_once_per_cycle(setup):
    engine, hl, md, store, bot_id = setup
    second = engine.create_bot(BotConfig.from_dict(engine.bots[bot_id].config.to_dict() | {"name": "b"}))
    engine.start(bot_id)
    engine.start(second)
    engine.tick(T0)
    assert hl.calls == 1


def test_config_rules():
    with pytest.raises(ValueError, match="futuros"):
        BotConfig.from_dict({"strategy": "copy_wallet", "strategy_params": {"wallet": WALLET}})
    with pytest.raises(ValueError, match="inválida"):
        BotConfig.from_dict({"strategy": "copy_wallet", "markets": {"spot": {"enabled": False}},
                             "strategy_params": {"wallet": "0xabc"}})


def test_cannot_start_without_wallet(setup):
    engine, hl, md, store, bot_id = setup
    empty = engine.create_bot(BotConfig.from_dict({"strategy": "copy_wallet", "markets": {"spot": {"enabled": False}}}))
    with pytest.raises(ValueError, match="carteira"):
        engine.start(empty)


def test_analyze_report():
    hl = FakeHyperliquid()
    hl.set("BTC", "long", 60_000, leverage=10)
    report = analyze(WALLET, hl.state(WALLET), hl.fills(WALLET), hl.portfolio(WALLET))
    assert report["closed_trades"] == 2 and report["wins"] == 1
    assert report["closed_pnl"] == pytest.approx(80)
    assert report["periods"]["allTime"]["pnl"] == pytest.approx(900)
    assert report["periods"]["allTime"]["max_drawdown"] == pytest.approx(300)
    assert report["effective_leverage"] == pytest.approx(6.0)
    assert any("Alavancagem" in w for w in report["warnings"])
    assert any("Poucas operações" in w for w in report["warnings"])


def test_panel_copy_flow(setup):
    engine, hl, md, store, bot_id = setup
    client = TestClient(create_app(engine, "t"))
    client.get("/?token=t")
    client.cookies.set("tradebot_token", "t")
    assert WALLET[:8] in client.get("/copy").text
    page = client.get(f"/copy/analyze?address={WALLET}")
    assert page.status_code == 200 and "Criar robô de cópia" in page.text and "copia" in page.text
    assert "inválido" in client.get("/copy/analyze?address=0x12").text
    r = client.post("/bots", data={"strategy": "copy_wallet", "wallet": WALLET, "name": "Baleia", "copy_from": "1"},
                    follow_redirects=False)
    new_id = int(r.headers["location"].split("/")[2])
    cfg = engine.bots[new_id].config
    assert cfg.params()["wallet"] == WALLET and not cfg.markets["spot"].enabled
    settings = client.get(f"/bots/{new_id}/settings").text
    assert WALLET in settings and "analisar esta carteira" in settings
    empty = engine.create_bot(BotConfig.from_dict({"strategy": "copy_wallet", "markets": {"spot": {"enabled": False}}}))
    r = client.post(f"/api/bots/{empty}/start")
    assert r.status_code == 409 and "carteira" in r.headers["HX-Trigger"]


# --- aumentos e reduções do trader ---
def _open_btc(setup, notional=1_000):
    engine, hl, md, store, bot_id = setup
    engine.start(bot_id)
    engine.tick(T0)
    hl.set("BTC", "long", notional)
    engine.tick(T0 + 10_000)
    [p] = store.open_positions("paper", bot_id)
    return p


def test_leader_reduction_closes_same_fraction_as_own_history_row(setup):
    engine, hl, md, store, bot_id = setup
    p = _open_btc(setup)
    md.prices["BTCUSDT"] = 110.0
    hl.set("BTC", "long", 500)  # reduziu pela metade
    engine.tick(T0 + 20_000)
    [still] = store.open_positions("paper", bot_id)
    [part] = store.closed_positions("paper", bot_id)
    assert still.qty == pytest.approx(p.qty / 2, rel=0.01)
    assert part.qty == pytest.approx(p.qty / 2, rel=0.01)
    assert part.exit_reason == "leader_reduce" and part.extra["partial_of"] == p.id
    assert part.net_pnl() > 0  # vendeu a parte com lucro
    assert still.entry_fee + part.entry_fee == pytest.approx(p.entry_fee)


def test_leader_increase_adds_and_recomputes_average_and_stop(setup):
    engine, hl, md, store, bot_id = setup
    p = _open_btc(setup)
    md.prices["BTCUSDT"] = 120.0
    hl.set("BTC", "long", 1_500)  # +50%
    engine.tick(T0 + 20_000)
    [q] = store.open_positions("paper", bot_id)
    assert q.qty == pytest.approx(p.qty * 1.5, rel=0.01)
    expected_avg = (100 * p.qty + 120 * (q.qty - p.qty)) / q.qty
    assert q.entry_price == pytest.approx(expected_avg, rel=0.001)
    assert q.stop_loss == pytest.approx(q.entry_price * 0.95)


def test_small_changes_ignored_but_accumulate(setup):
    engine, hl, md, store, bot_id = setup
    p = _open_btc(setup)
    hl.set("BTC", "long", 950)  # -5%: abaixo dos 10%
    engine.tick(T0 + 20_000)
    assert store.open_positions("paper", bot_id)[0].qty == pytest.approx(p.qty)
    hl.set("BTC", "long", 880)  # -12% acumulado desde a referência
    engine.tick(T0 + 30_000)
    assert store.open_positions("paper", bot_id)[0].qty == pytest.approx(p.qty * 0.88, rel=0.02)


def test_reduction_leaving_dust_closes_everything(setup):
    engine, hl, md, store, bot_id = setup
    _open_btc(setup, notional=1_000)
    hl.set("BTC", "long", 10)  # sobraria ~1 USDT, abaixo do mínimo de 5
    engine.tick(T0 + 20_000)
    assert store.open_positions("paper", bot_id) == []
    assert store.closed_positions("paper", bot_id)[0].exit_reason == "leader_reduce"


def test_follow_size_can_be_disabled(setup):
    engine, hl, md, store, bot_id = setup
    cfg = engine.bots[bot_id].config
    cfg.strategy_params["follow_size_changes"] = False
    engine.update_bot(bot_id, cfg)
    p = _open_btc(setup)
    hl.set("BTC", "long", 400)
    engine.tick(T0 + 20_000)
    assert store.open_positions("paper", bot_id)[0].qty == pytest.approx(p.qty)


def test_cash_matches_history_after_adds_reductions_and_close(setup):
    engine, hl, md, store, bot_id = setup
    _open_btc(setup)
    steps = [(104, 1_600), (102, 800), (103, 1_200), (105, 300), (104, None)]  # sem bater o stop de 5%
    for k, (price, size) in enumerate(steps):
        md.prices["BTCUSDT"] = price
        if size is None:
            del hl.positions["BTC"]
        else:
            hl.set("BTC", "long", size)
        engine.tick(T0 + 20_000 + k * 10_000)
    assert store.open_positions("paper", bot_id) == []
    closed = store.closed_positions("paper", bot_id)
    assert len(closed) >= 3
    cash = engine.bots[bot_id].brokers["futures"].cash()
    assert cash == pytest.approx(1000 + sum(p.net_pnl() for p in closed), abs=1e-6)
