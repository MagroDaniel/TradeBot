"""CLI do backtest — roda a estratégia atual e algumas variantes com filtro lado a lado contra
histórico real da Binance, pra decidir com dado (não só observação de poucos sinais ao vivo)
se vale a pena mudar `analysis/signals.py`.

Uso:
    python -m backtest.run                 # 90 dias, top 25 pares por volume (atual)
    python -m backtest.run --days 30
    python -m backtest.run --symbols BTCUSDT,ETHUSDT,SOLUSDT

Importa `config.py` (por isso exige `.env` com credencial do Telegram, mesmo não mandando
nenhuma mensagem) só pra reaproveitar TOP_SYMBOLS_COUNT/TIMEFRAME/SIGNAL_EXPIRY_HOURS em vez de
duplicar esses valores — módulos que o backtest realmente executa (`engine.py`, `filters.py`,
`history.py`) continuam sem essa dependência, testáveis sem `.env` como o resto do projeto.
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

import config
from backtest.engine import Variant, run_backtest
from backtest.history import fetch_candles
from backtest.report import build_report, format_report_table
from data.binance_client import BinanceClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HIGHER_TIMEFRAME = "1h"

VARIANTS = [
    # Desde 2026-09-09, "produção atual" É a variante com filtro de 1h — confirmada em dois
    # backtests (60 e 180 dias) como a única com expectância positiva e consistente entre
    # janelas. As outras ficam aqui só pra reavaliar de vez em quando, não pra reabrir sem
    # motivo (ver CLAUDE.md, "Decisões já tomadas" e "Backtest walk-forward").
    Variant(name="sem filtro (pré-2026-09-09)"),
    Variant(name="+ ADX >= 25 (descartado, piora)", min_adx=25.0),
    Variant(name="+ tendência 1h (produção atual)", use_htf_trend_filter=True),
    Variant(name="+ ADX + tendência 1h", min_adx=25.0, use_htf_trend_filter=True),
    Variant(
        name="+ ADX + 1h + máx 3 correlacionados",
        min_adx=25.0,
        use_htf_trend_filter=True,
        max_concurrent_same_direction=3,
    ),
    # Candidatos extraídos dos livros de referência (docs/estrategias_extraidas_livros.md,
    # item 1 da lista priorizada) — em cima da produção atual (1h), exige que o candle do
    # sinal tenha corpo inteiro além da EMA21 e fechamento na metade "forte" do candle a
    # favor da direção. Duas exigências (metade do candle vs. 65% dela) pra ver se a força
    # extra compensa perder sinais.
    Variant(
        name="+ 1h + qualidade do candle (50%)",
        use_htf_trend_filter=True,
        min_signal_candle_close_position=0.5,
    ),
    Variant(
        name="+ 1h + qualidade do candle (65%)",
        use_htf_trend_filter=True,
        min_signal_candle_close_position=0.65,
    ),
    # Item 2 da lista priorizada (docs/estrategias_extraidas_livros.md) — o livro Análise
    # Técnica cita que day traders costumam usar múltiplo de ATR maior (3-4x) que o 1.5x atual
    # do bot; nunca foi comparado contra outro valor. Alvo escala junto (RISK_REWARD_RATIO
    # continua fixo), então isso alarga entrada/stop/alvo proporcionalmente, não só o stop.
    Variant(name="+ 1h + ATR stop 2x", use_htf_trend_filter=True, atr_stop_multiplier=2.0),
    Variant(name="+ 1h + ATR stop 3x", use_htf_trend_filter=True, atr_stop_multiplier=3.0),
    # Item 3 da lista priorizada — a faixa de RSI já é por direção (long/short), e como o
    # sinal só confirma quando o 1h concorda com a direção, a faixa aceita já representa um
    # regime confirmado. Constance Brown (citada no livro Análise Técnica) sugere que em
    # tendência de alta o RSI oscila mais entre 40-90 (não 0-100), e em baixa entre 10-60 —
    # bem mais largo que o (30,65)/(35,70) atual do bot, que rejeita sinal só por RSI já
    # elevado mesmo com tendência forte confirmada.
    Variant(
        name="+ 1h + RSI faixa Constance Brown (40-90 / 10-60)",
        use_htf_trend_filter=True,
        long_rsi_range=(40.0, 90.0),
        short_rsi_range=(10.0, 60.0),
    ),
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90, help="Quantos dias de histórico buscar")
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Lista separada por vírgula (ex: BTCUSDT,ETHUSDT). Default: top por volume atual.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    client = BinanceClient()

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    else:
        symbols = client.get_top_symbols_by_volume(limit=config.TOP_SYMBOLS_COUNT)
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
    for variant in VARIANTS:
        result = run_backtest(
            candles_by_symbol,
            variant,
            higher_tf_candles_by_symbol=higher_tf_by_symbol,
            expiry_hours=config.SIGNAL_EXPIRY_HOURS,
        )
        reports.append(build_report(result))

    print()
    print(f"Backtest: {len(symbols)} pares, {args.days} dias, timeframe {config.TIMEFRAME}")
    print(f"Período: {start.date()} a {end.date()}")
    print()
    print(format_report_table(reports))
    print()
    print(
        "win% e exp(R) só contam sinais fechados (alvo/stop); 'aberto' é quanto ainda estava\n"
        "em aberto no fim do período (não entra nas métricas). exp(R) > 0 = expectativa\n"
        "positiva; PF (profit factor) > 1 = ganhos de R somam mais que perdas."
    )


if __name__ == "__main__":
    main()
