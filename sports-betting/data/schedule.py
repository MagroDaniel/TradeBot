"""Utilitários de data/hora em horário de Brasília (BRT, UTC-3 fixo — Brasil não observa
horário de verão desde 2019).

Existem porque o bot precisa alinhar "hoje" e "ontem" ao fuso do público (Brasil), independente
do fuso do processo que roda o job (os runners do GitHub Actions rodam em UTC). Usadas tanto
pra filtrar só os jogos de hoje (`is_same_day_brt`) quanto pra formatar datas/horários nas
mensagens do Telegram (`format_date_br`, `format_time_brt`).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

BRT = timezone(timedelta(hours=-3))


def today_brt() -> date:
    """Data de hoje em BRT, a partir do relógio do sistema."""
    return datetime.now(BRT).date()


def is_same_day_brt(iso_datetime: str, reference: date) -> bool:
    """True se o timestamp ISO (ex: commence_time da Odds API, em UTC) cai no mesmo dia
    calendário de `reference`, uma vez convertido pra BRT."""
    dt = datetime.fromisoformat(iso_datetime.replace("Z", "+00:00"))
    return dt.astimezone(BRT).date() == reference


def format_date_br(iso_date: str) -> str:
    """'2026-09-08' -> '08/09' — formato de data mais natural pra mensagens em pt-BR."""
    return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d/%m")


def format_time_brt(iso_datetime: str) -> str:
    """Timestamp ISO em UTC (ex: commence_time da Odds API) -> horário local BRT, ex: '19h00'."""
    dt = datetime.fromisoformat(iso_datetime.replace("Z", "+00:00"))
    return dt.astimezone(BRT).strftime("%Hh%M")
