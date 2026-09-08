"""Utilitários de data/hora em horário de Brasília (BRT, UTC-3 fixo — Brasil não observa
horário de verão desde 2019). Mesmo módulo (mesma lógica) do bot de apostas
(`../sports-betting/data/schedule.py`) — cripto roda 24/7, sem "horário de jogo", mas o
relatório diário ainda precisa de um corte de dia, e meia-noite BRT é a referência natural
pro público do bot.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

BRT = timezone(timedelta(hours=-3))


def today_brt() -> date:
    return datetime.now(BRT).date()


def date_brt(iso_datetime: str) -> date:
    """Converte um datetime ISO (qualquer fuso, ex: `SignalRecord.closed_at` em UTC) pro
    dia calendário correspondente em BRT."""
    return datetime.fromisoformat(iso_datetime).astimezone(BRT).date()
