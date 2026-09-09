"""Script temporário — dump do R líquido por trade (não só a média) da variante "range 6x" pra
simular uma curva de banca com juros compostos. NÃO faz parte do backtest de decisão de
variantes (isso continua em run.py); serve só pra responder "quanto eu teria hoje partindo de
R$X" com o dado real, em vez de aproximar pela expectância média (que subestima o efeito de
variância no juro composto). Remover depois de responder.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import config
from backtest.engine import ExecutionCosts, Variant, run_backtest
from backtest.history import fetch_candles
from backtest.report import net_r_multiple
from data.binance_client import BinanceClient

HIGHER_TIMEFRAME = "1h"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=365)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    client = BinanceClient()
    symbols = list(config.BACKTEST_SYMBOLS)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)

    candles_by_symbol = {}
    higher_tf_by_symbol = {}
    for symbol in symbols:
        candles_by_symbol[symbol] = fetch_candles(client, symbol, config.TIMEFRAME, start_ms, end_ms)
        higher_tf_by_symbol[symbol] = fetch_candles(client, symbol, HIGHER_TIMEFRAME, start_ms, end_ms)

    costs = ExecutionCosts(
        taker_fee_rate=config.BACKTEST_TAKER_FEE_RATE,
        slippage_rate=config.BACKTEST_SLIPPAGE_RATE,
        funding_rate_per_8h=config.BACKTEST_FUNDING_RATE_PER_8H,
    )
    variant = Variant(name="range 6x (produção atual)", use_htf_trend_filter=True, min_range_expansion=6.0)
    result = run_backtest(
        candles_by_symbol,
        variant,
        higher_tf_candles_by_symbol=higher_tf_by_symbol,
        expiry_hours=config.SIGNAL_EXPIRY_HOURS,
        costs=costs,
        allowed_directions=config.ALLOWED_DIRECTIONS,
    )

    closed = sorted(result.closed, key=lambda s: s.closed_at or "")
    print(f"\nTotal de trades fechados: {len(closed)}")
    print("closed_at,symbol,direction,status,net_r")
    for s in closed:
        print(f"{s.closed_at},{s.symbol},{s.direction},{s.status},{net_r_multiple(s, costs):.4f}")

    # Simulação de banca com juros compostos, arriscando uma fração fixa por trade
    print("\nSimulação de banca (R$100 inicial), arriscando fração fixa por trade:")
    for risk_pct in (0.01, 0.02, 0.05):
        balance = 100.0
        for s in closed:
            balance *= 1 + risk_pct * net_r_multiple(s, costs)
        print(f"  risco {risk_pct:.0%} por trade -> R$ {balance:.2f}")


if __name__ == "__main__":
    main()
