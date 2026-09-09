"""CLI do backtest da estratégia de reversão à média (Bollinger+RSI) — candidato alternativo
ao cruzamento de EMA (`backtest/run.py`), pesquisado depois da estratégia de tendência não
cruzar pra expectância positiva em forex mesmo recalibrada e com filtro de sessão (ver
README.md). Mesmo padrão de CLI dos outros backtests do projeto.

Uso:
    python -m backtest.run_mean_reversion                 # 90 dias, FOREX_SYMBOLS, timeframe 1h
    python -m backtest.run_mean_reversion --days 60
    python -m backtest.run_mean_reversion --timeframe 15min
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

import config
from backtest.engine import ExecutionCosts
from backtest.history import fetch_candles
from backtest.mean_reversion_engine import MeanReversionVariant, run_backtest
from backtest.report import build_report, format_report_table
from data.twelvedata_client import TwelveDataClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

VARIANTS = [
    MeanReversionVariant(name="sem filtro (baseline)"),
    MeanReversionVariant(name="+ sessão Londres+NY (07-21 UTC)", session_hours_utc=(7, 21)),
    MeanReversionVariant(name="+ RSI 25/75 (mais extremo)", rsi_oversold=25.0, rsi_overbought=75.0),
    MeanReversionVariant(name="+ BB 2.5 desvios (banda mais larga)", bb_num_std=2.5),
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90, help="Quantos dias de histórico buscar")
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Lista separada por vírgula (ex: EUR/USD,GBP/USD). Sobrescreve config.BACKTEST_SYMBOLS.",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1h",
        help="Intervalo dos candles (formato Twelve Data: 15min, 1h...). Default 1h — mean reversion não usa filtro de timeframe maior.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    client = TwelveDataClient(config.TWELVEDATA_API_KEY)

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else list(config.BACKTEST_SYMBOLS)
    logger.info("Símbolos: %s | timeframe: %s", ", ".join(symbols), args.timeframe)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)

    candles_by_symbol = {}
    for i, symbol in enumerate(symbols, 1):
        t0 = time.monotonic()
        candles_by_symbol[symbol] = fetch_candles(client, symbol, args.timeframe, start_ms, end_ms)
        logger.info(
            "[%d/%d] %s: %d candles %s (%.1fs)",
            i, len(symbols), symbol, len(candles_by_symbol[symbol]), args.timeframe, time.monotonic() - t0,
        )
        candles = candles_by_symbol[symbol]
        if candles:
            first_dt = datetime.fromtimestamp(candles[0].open_time_ms / 1000, tz=timezone.utc)
            last_dt = datetime.fromtimestamp(candles[-1].open_time_ms / 1000, tz=timezone.utc)
            logger.info("  cobertura real: %s a %s", first_dt.date(), last_dt.date())

    reports = []
    costs = ExecutionCosts(
        taker_fee_rate=config.BACKTEST_TAKER_FEE_RATE,
        slippage_rate=config.BACKTEST_SLIPPAGE_RATE,
        funding_rate_per_8h=config.BACKTEST_FUNDING_RATE_PER_8H,
    )
    for variant in VARIANTS:
        result = run_backtest(candles_by_symbol, variant, expiry_hours=config.SIGNAL_EXPIRY_HOURS, costs=costs)
        reports.append(build_report(result, costs=costs))

    print()
    print(f"Backtest (mean reversion): {len(symbols)} par(es), {args.days} dias, timeframe {args.timeframe}")
    print(f"Período: {start.date()} a {end.date()}")
    print()
    print(format_report_table(reports))
    print()
    print(
        "win% só conta sinais fechados (alvo/stop); 'aberto' é quanto ainda estava no fim do\n"
        "período. 'bruto' usa os preços já afetados pelo slippage (proxy do spread); 'líq(R)'\n"
        f"também desconta comissão de {costs.taker_fee_rate:.3%} por lado e swap de "
        f"{costs.funding_rate_per_8h:.3%}/8h. PF e maxDD usam R líquido."
    )


if __name__ == "__main__":
    main()
