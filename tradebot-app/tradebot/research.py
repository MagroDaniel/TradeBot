"""Pesquisa de estratégias contra histórico REAL da Binance.

    python -m tradebot.research --market futures --days 365
    python -m tradebot.research --strategy donchian_breakout --set entry_channel=55 --days 540
    python -m tradebot.research --source archive --months 12      # usa data.binance.vision

Critério de aprovação (o mesmo que o crypto-daytrade usou pra adotar/descartar filtros):
R líquido positivo em TODAS as fatias do período (`--parts`), não só no total, amostra
razoável e bootstrap com p baixo. Resultado bom num pedaço só = provável ruído (foi assim
que o "quase zero a zero" do forex virou -0,31R na janela longa).

Universo fixo de pares líquidos por padrão (não o top de hoje aplicado ao passado — viés de
sobrevivência documentado no crypto-daytrade).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import time
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import requests

from tradebot.backtest import (Limits, bootstrap_p_value, default_costs, run_backtest, simulate_equity,
                               split_by_period, summarize)
from tradebot.market_data import BinanceMarketData
from tradebot.models import FUTURES, SPOT, Candle
from tradebot.paths import data_dir
from tradebot.strategies import STRATEGIES, get_strategy

# copy trading não tem backtest por candles (a análise é a do histórico da carteira copiada)
CANDLE_STRATEGIES = sorted(name for name, s in STRATEGIES.items() if s.kind == "candles")
from tradebot.strategies.base import TIMEFRAME_MINUTES

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
    "LINKUSDT", "DOTUSDT", "LTCUSDT", "TRXUSDT", "BCHUSDT", "ATOMUSDT", "NEARUSDT",
]
ARCHIVE_BASE = "https://data.binance.vision/data"


def _cache_dir() -> Path:
    path = data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save(path: Path, candles: list[Candle]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        for c in candles:
            w.writerow([c.open_time_ms, c.open, c.high, c.low, c.close, c.volume, c.close_time_ms])


def _load(path: Path) -> list[Candle]:
    with path.open() as f:
        return [Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]), int(r[6]))
                for r in csv.reader(f)]


def fetch_api(market: str, symbol: str, interval: str, start_ms: int, end_ms: int) -> list[Candle]:
    path = _cache_dir() / f"api_{market}_{symbol}_{interval}_{start_ms}_{end_ms}.csv"
    if path.exists():
        return _load(path)
    candles = BinanceMarketData(market).historical_klines(symbol, interval, start_ms, end_ms)
    _save(path, candles)
    return candles


def _to_ms(value: str) -> int:
    v = int(value)
    return v // 1000 if v > 10**14 else v  # spot a partir de 2025 vem em microssegundos


def fetch_archive_month(market: str, symbol: str, interval: str, year: int, month: int) -> list[Candle]:
    path = _cache_dir() / f"arc_{market}_{symbol}_{interval}_{year}-{month:02d}.csv"
    if path.exists():
        return _load(path)
    segment = "spot" if market == SPOT else "futures/um"
    name = f"{symbol}-{interval}-{year}-{month:02d}"
    url = f"{ARCHIVE_BASE}/{segment}/monthly/klines/{symbol}/{interval}/{name}.zip"
    response = requests.get(url, timeout=60)
    if response.status_code == 404:
        return []  # par ainda não existia nesse mês
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        text = z.read(z.namelist()[0]).decode()
    candles = []
    for row in csv.reader(io.StringIO(text)):
        if not row or not row[0].isdigit():
            continue  # cabeçalho (arquivos de futuros têm)
        candles.append(Candle(_to_ms(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]),
                              float(row[5]), _to_ms(row[6])))
    _save(path, candles)
    return candles


def fetch_archive(market: str, symbol: str, interval: str, months: int) -> list[Candle]:
    now = datetime.now(timezone.utc)
    y, m = now.year, now.month
    out: list[Candle] = []
    for _ in range(months):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out = fetch_archive_month(market, symbol, interval, y, m) + out
    return out


def load_data(market, symbols, interval, start_ms, end_ms, source, months):
    data = {}
    for symbol in symbols:
        try:
            candles = (fetch_archive(market, symbol, interval, months) if source == "archive"
                       else fetch_api(market, symbol, interval, start_ms, end_ms))
        except Exception as exc:
            print(f"  ! {symbol} {interval}: {exc}")
            continue
        if candles:
            data[symbol] = candles
    return data


def parse_overrides(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs or []:
        key, _, value = pair.partition("=")
        out[key.strip()] = value.strip()
    return out


def evaluate(name, overrides, market, data_cache, args, start_ms, end_ms):
    strategy = get_strategy(name)
    params = strategy.resolve(overrides)
    tf = strategy.timeframe(params)
    htf = strategy.higher_timeframe(params)
    for interval in filter(None, {tf, htf}):
        if (market, interval) not in data_cache:
            print(f"Baixando {market} {interval} ({len(args.symbols)} pares)...")
            data_cache[(market, interval)] = load_data(market, args.symbols, interval, start_ms, end_ms,
                                                       args.source, args.months)
    candles = data_cache[(market, tf)]
    htf_candles = data_cache[(market, htf)] if htf else None
    limits = Limits(long_only=market == SPOT)
    t0 = time.time()
    trades, _ = run_backtest(strategy, params, candles, htf_candles, default_costs(market), limits)
    all_c = [c for cs in candles.values() for c in cs]
    first, last = min(c.open_time_ms for c in all_c), max(c.close_time_ms for c in all_c)
    parts = split_by_period(trades, first, last, args.parts)
    s = summarize(trades)
    return {
        "strategy": name, "market": market, "params": params, "summary": asdict(s),
        "parts_avg_r": [summarize(p).avg_r_net for p in parts], "parts_trades": [len(p) for p in parts],
        "p_value": bootstrap_p_value(trades), "equity_1pct": simulate_equity(trades, 1000, 1.0),
        "seconds": round(time.time() - t0, 1), "period": [first, last],
    }


def verdict(r: dict) -> str:
    s = r["summary"]
    if s["trades"] < 30:
        return "amostra pequena"
    if all(x > 0 for x in r["parts_avg_r"]) and r["p_value"] < 0.10:
        return "CANDIDATA"
    if s["avg_r_net"] > 0:
        return "positiva, inconsistente"
    return "reprovada"


def print_table(results: list[dict], parts: int) -> None:
    header = f"{'estratégia':<22}{'mercado':<9}{'trades':>7}{'win%':>7}{'R méd':>8}{'PF':>6}{'maxDD':>7}" \
             f"{'  R por fatia':<{9 * parts + 2}}{'p':>6}{'1%→':>9}  veredito"
    print(header)
    print("-" * len(header))
    for r in results:
        s = r["summary"]
        parts_txt = " ".join(f"{x:+.2f}" for x in r["parts_avg_r"])
        print(f"{r['strategy']:<22}{r['market']:<9}{s['trades']:>7}{s['win_rate'] * 100:>6.1f}%{s['avg_r_net']:>+8.3f}"
              f"{min(s['profit_factor'], 99):>6.2f}{s['max_drawdown_r']:>7.1f}  {parts_txt:<{9 * parts}}"
              f"{r['p_value']:>6.2f}{r['equity_1pct']:>9.0f}  {verdict(r)}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strategy", choices=CANDLE_STRATEGIES, action="append",
                    help="pode repetir; default = todas")
    ap.add_argument("--market", choices=[SPOT, FUTURES], action="append", help="default = futures")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--source", choices=["api", "archive"], default="api")
    ap.add_argument("--months", type=int, default=12, help="só com --source archive")
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    ap.add_argument("--parts", type=int, default=3, help="fatias do período pra checar consistência")
    ap.add_argument("--set", action="append", default=[], metavar="param=valor",
                    help="sobrescreve parâmetro (aplica a todas as estratégias selecionadas que o tiverem)")
    ap.add_argument("--json", type=Path, help="salva resultados completos em JSON")
    args = ap.parse_args(argv)

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - args.days * 86_400_000
    overrides = parse_overrides(args.set)
    data_cache: dict = {}
    results = []
    for market in args.market or [FUTURES]:
        for name in args.strategy or CANDLE_STRATEGIES:
            strategy = get_strategy(name)
            own = {k: v for k, v in overrides.items() if k in strategy.params}
            print(f"→ {name} ({market}) {own or ''}")
            results.append(evaluate(name, own, market, data_cache, args, start_ms, end_ms))
    print()
    print_table(results, args.parts)
    print("\nR méd = expectância líquida por trade (taxa+slippage). maxDD em R. p = bootstrap "
          "(chance de ser sorte). 1%→ = US$1000 arriscando 1% por trade.")
    if args.json:
        args.json.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
