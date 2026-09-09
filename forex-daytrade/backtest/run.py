"""CLI do backtest — roda a estratégia baseline e variantes com filtro lado a lado contra
histórico real da Twelve Data, pra decidir com dado (não achismo) se vale a pena ligar algum
filtro em `analysis/signals.py`/`config.py`. Mesmo padrão de `crypto-daytrade/backtest/run.py`.

Uso:
    python -m backtest.run                 # 90 dias, FOREX_SYMBOLS configurado
    python -m backtest.run --days 30
    python -m backtest.run --symbols EUR/USD,GBP/USD

Primeira rodada de sempre pra este módulo — ainda não existe nenhuma decisão de produção
tomada aqui (ver README.md), só a pergunta em aberto "essa estratégia tem expectância positiva
em forex, do jeito que já está calibrada pra cripto?".
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

import config
from backtest.engine import ExecutionCosts, Variant, run_backtest
from backtest.history import fetch_candles
from backtest.report import build_report, format_report_table
from data.twelvedata_client import TwelveDataClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HIGHER_TIMEFRAME = "1h"

VARIANTS = [
    Variant(name="sem filtro (baseline)"),
    Variant(name="+ tendência 1h", use_htf_trend_filter=True),
    Variant(name="+ ADX >= 25", min_adx=25.0),
    Variant(name="+ ADX + tendência 1h", min_adx=25.0, use_htf_trend_filter=True),
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
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    client = TwelveDataClient(config.TWELVEDATA_API_KEY)

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else list(config.BACKTEST_SYMBOLS)
    logger.info("Símbolos: %s", ", ".join(symbols))

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)

    candles_by_symbol = {}
    higher_tf_by_symbol = {}
    for i, symbol in enumerate(symbols, 1):
        t0 = time.monotonic()
        candles_by_symbol[symbol] = fetch_candles(client, symbol, config.TIMEFRAME, start_ms, end_ms)
        higher_tf_by_symbol[symbol] = fetch_candles(client, symbol, HIGHER_TIMEFRAME, start_ms, end_ms)
        logger.info(
            "[%d/%d] %s: %d candles %s + %d candles %s (%.1fs)",
            i, len(symbols), symbol,
            len(candles_by_symbol[symbol]), config.TIMEFRAME,
            len(higher_tf_by_symbol[symbol]), HIGHER_TIMEFRAME,
            time.monotonic() - t0,
        )

    reports = []
    costs = ExecutionCosts(
        taker_fee_rate=config.BACKTEST_TAKER_FEE_RATE,
        slippage_rate=config.BACKTEST_SLIPPAGE_RATE,
        funding_rate_per_8h=config.BACKTEST_FUNDING_RATE_PER_8H,
    )
    for variant in VARIANTS:
        result = run_backtest(
            candles_by_symbol,
            variant,
            higher_tf_candles_by_symbol=higher_tf_by_symbol,
            expiry_hours=config.SIGNAL_EXPIRY_HOURS,
            costs=costs,
        )
        reports.append(build_report(result, costs=costs))

    print()
    print(f"Backtest: {len(symbols)} par(es), {args.days} dias, timeframe {config.TIMEFRAME}")
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
