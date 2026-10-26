from tests.helpers import make_candles, random_walk
from tradebot import research


def test_research_cli_runs_all_strategies_offline(monkeypatch, capsys, tmp_path):
    def fake_load(market, symbols, interval, start_ms, end_ms, source, months):
        minutes = {"15m": 15, "1h": 60}[interval]
        n = 3000 if minutes == 15 else 800
        return {s: make_candles(random_walk(n, seed=i, vol=0.006), minutes=minutes) for i, s in enumerate(symbols)}

    monkeypatch.setattr(research, "load_data", fake_load)
    out = tmp_path / "r.json"
    research.main(["--symbols", "AAAUSDT", "BBBUSDT", "--json", str(out), "--market", "futures", "--market", "spot"])
    text = capsys.readouterr().out
    for name in research.CANDLE_STRATEGIES:
        assert name in text
    assert out.exists()
