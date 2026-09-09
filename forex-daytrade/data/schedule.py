"""Utilitários de data/hora em horário de Brasília (BRT, UTC-3 fixo — Brasil não observa
horário de verão desde 2019). Mesmo módulo de `crypto-daytrade/data/schedule.py` — cripto roda
24/7 então não precisava de checagem de mercado aberto; forex fecha no fim de semana, então
este módulo ganhou `is_forex_market_open` a mais.
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


def is_forex_market_open(now: datetime | None = None) -> bool:
    """Aproximação da janela em que o mercado de forex costuma negociar: abre domingo às
    22:00 UTC (início da sessão de Sydney) e fecha sexta às 22:00 UTC (fim da sessão de Nova
    York) — convenção comum entre corretoras de varejo, mas os minutos exatos variam um pouco
    de corretora pra corretora (feriados bancários também fecham cedo/abrem tarde, não
    tratados aqui). Fora dessa janela, escanear é inútil: preço não se move de verdade, só
    ruído de cotação, e qualquer "sinal" seria em cima de candle sem negociação real por trás.
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    weekday = moment.weekday()  # segunda=0 ... domingo=6
    hour = moment.hour

    if weekday == 5:  # sábado inteiro fechado
        return False
    if weekday == 6:  # domingo — abre às 22:00 UTC
        return hour >= 22
    if weekday == 4:  # sexta — fecha às 22:00 UTC
        return hour < 22
    return True  # segunda a quinta, mercado aberto o dia todo
