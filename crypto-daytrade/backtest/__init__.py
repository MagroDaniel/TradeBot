"""Backtest walk-forward sobre candles históricos reais da Binance — diferente de
`analysis/performance.py` (que só resume sinais que o bot já emitiu de verdade), este módulo
*simula* a estratégia (e variantes com filtro) contra meses de histórico, pra validar qualquer
mudança em `analysis/signals.py` com uma amostra estatisticamente relevante ANTES dela ir pra
produção. Motivado pela investigação de 2026-09-09 (ver CLAUDE.md) — os primeiros sinais reais
saíram com win rate baixo, mas numa amostra pequena e correlacionada demais pra significar algo
sozinha.
"""
