"""Envio de mensagens pro Telegram — bot/grupo separados do bot de apostas esportivas.

Formato parecido (emoji, HTML), mas com um disclaimer de risco mais forte: listagem nova de
cripto é MUITO mais volátil e arriscada do que apostar contra uma odd de mercado — não existe
edge matemático objetivo aqui, só sinais descritivos (ver `analysis/scoring.py`).
"""
from __future__ import annotations

import logging

import requests

from analysis.scoring import Assessment

logger = logging.getLogger(__name__)

_DISCLAIMER = (
    "⚠️ <i>Isto NÃO é uma previsão de alta. É só o risco que a própria Binance sinalizou no "
    "anúncio e o momentum de mercado, quando já disponível. Listagens novas são extremamente "
    "voláteis, muitas vezes ligadas a golpe (rug pull), e bots profissionais costumam capturar "
    "o movimento inicial antes de qualquer alerta público chegar. Faça sua própria pesquisa "
    "antes de comprar qualquer coisa.</i>"
)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def _send(self, text: str) -> None:
        response = requests.post(
            f"{self.base_url}/sendMessage",
            data={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        if not response.ok:
            logger.error("Falha ao enviar mensagem no Telegram: %s", response.text)
        response.raise_for_status()

    def send_listing_alert(self, title: str, ticker: str | None, assessment: Assessment) -> None:
        icon = "🚨" if assessment.is_high_risk else "🆕"
        header = f"{icon} <b>Nova listagem na Binance</b>" + (f" — {ticker}" if ticker else "")
        lines = [
            header,
            "",
            title,
            "",
            assessment.summary(),
            "",
            _DISCLAIMER,
        ]
        self._send("\n".join(lines))
