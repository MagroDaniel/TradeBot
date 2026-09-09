"""CLI do backtest — roda a estratégia baseline e variantes com filtro lado a lado contra
histórico real da Twelve Data, pra decidir com dado (não achismo) se vale a pena ligar algum
filtro em `analysis/signals.py`/`config.py`. Mesmo padrão de `crypto-daytrade/backtest/run.py`.

Uso:
    python -m backtest.run                 # 90 dias, FOREX_SYMBOLS, timeframe de config.py
    python -m backtest.run --days 30
    python -m backtest.run --symbols EUR/USD,GBP/USD
    python -m backtest.run --timeframe 1h --higher-timeframe 4h   # candidato de recalibração

A baseline com os parâmetros herdados do cripto (RSI 30-65/35-70, ATR 1.5x, timeframe de
15min) foi testada e REPROVADA em 2 janelas reais (60/180 dias) — expectância negativa
consistente, todo filtro piora em vez de melhorar (ver README.md). `--timeframe`/
`--higher-timeframe` existem pra testar a hipótese de que o candle de 15min é ruidoso demais
pra forex (volatilidade bem menor que cripto) sem precisar editar código a cada tentativa.
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


def _variants_for(higher_timeframe: str) -> list[Variant]:
    return [
        Variant(name="sem filtro (baseline)"),
        Variant(name=f"+ tendência {higher_timeframe}", use_htf_trend_filter=True),
        # ADX, ATR mais apertado/largo e RSI mais estreito (isolados e em combo) já foram
        # testados em 3 janelas e descartados (ver README.md) — ADX piora sempre; RSI+tendência
        # parecia bom em amostra pequena mas reverteu aos 365 dias (overfitting). Removidos
        # daqui pra não reabrir sem motivo — não sumiram, ficam documentados no README.
        #
        # Candidatos de sessão (pesquisa 2026-09-09): forex passa 70-80% do tempo em
        # consolidação, e a liquidez de EUR/USD se concentra nas sessões de Londres+NY —
        # aprox. 07h-21h UTC, com pico no overlap 12h-16h UTC. Fora disso (madrugada UTC, só
        # Tóquio aberto) é onde mais se espera ruído/whipsaw puro.
        Variant(name="+ sessão overlap (12-16 UTC)", session_hours_utc=(12, 16)),
        Variant(name="+ sessão Londres+NY (07-21 UTC)", session_hours_utc=(7, 21)),
        Variant(
            name=f"+ sessão Londres+NY + tendência {higher_timeframe}",
            session_hours_utc=(7, 21),
            use_htf_trend_filter=True,
        ),
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
        default=None,
        help="Intervalo dos candles de sinal (formato Twelve Data: 15min, 1h...). Sobrescreve config.TIMEFRAME.",
    )
    parser.add_argument(
        "--higher-timeframe",
        type=str,
        default=None,
        help="Intervalo do filtro de tendência maior. Default: 1h, ou 4h se --timeframe=1h.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    client = TwelveDataClient(config.TWELVEDATA_API_KEY)

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else list(config.BACKTEST_SYMBOLS)
    timeframe = args.timeframe or config.TIMEFRAME
    higher_timeframe = args.higher_timeframe or ("4h" if timeframe == "1h" else "1h")
    logger.info("Símbolos: %s | timeframe: %s | htf: %s", ", ".join(symbols), timeframe, higher_timeframe)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)

    candles_by_symbol = {}
    higher_tf_by_symbol = {}
    for i, symbol in enumerate(symbols, 1):
        t0 = time.monotonic()
        candles_by_symbol[symbol] = fetch_candles(client, symbol, timeframe, start_ms, end_ms)
        higher_tf_by_symbol[symbol] = fetch_candles(client, symbol, higher_timeframe, start_ms, end_ms)
        logger.info(
            "[%d/%d] %s: %d candles %s + %d candles %s (%.1fs)",
            i, len(symbols), symbol,
            len(candles_by_symbol[symbol]), timeframe,
            len(higher_tf_by_symbol[symbol]), higher_timeframe,
            time.monotonic() - t0,
        )
        # diagnóstico: confere se a cobertura de datas bate com o período pedido — pega erro
        # silencioso de paginação (ex: API truncando outputsize sem devolver tudo que existe
        # no intervalo) antes de confiar no resultado do backtest.
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
    for variant in _variants_for(higher_timeframe):
        result = run_backtest(
            candles_by_symbol,
            variant,
            higher_tf_candles_by_symbol=higher_tf_by_symbol,
            expiry_hours=config.SIGNAL_EXPIRY_HOURS,
            costs=costs,
        )
        reports.append(build_report(result, costs=costs))

    print()
    print(f"Backtest: {len(symbols)} par(es), {args.days} dias, timeframe {timeframe}")
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
