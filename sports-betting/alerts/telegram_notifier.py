"""Envio de mensagens para o Telegram via Bot API."""
from __future__ import annotations

import logging

import requests

from storage.picks_store import Pick

logger = logging.getLogger(__name__)


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

    def send_results_summary(self, date: str, picks: list[Pick]) -> None:
        resolved = [p for p in picks if p.result is not None]
        if not resolved:
            self._send(f"📊 <b>Resultado de {date}</b>\nNenhum pick registrado nesse dia.")
            return

        greens = [p for p in resolved if p.result == "green"]
        total_profit = sum(p.profit_units or 0 for p in resolved)

        lines = [f"📊 <b>Resultado de {date}</b>", "━━━━━━━━━━━━━━━━━━"]
        for p in resolved:
            icon = "✅" if p.result == "green" else "❌"
            profit = p.profit_units or 0
            sign = "+" if profit >= 0 else ""
            lines.append(f"{icon} {p.match} — {p.selection} ({sign}{profit:.2f}u)")

        lines.append("")
        sign_total = "+" if total_profit >= 0 else ""
        lines.append(
            f"Saldo do dia: {sign_total}{total_profit:.2f}u | {len(greens)}/{len(resolved)} acertos"
        )
        self._send("\n".join(lines))

    def send_daily_picks(self, date: str, picks: list[Pick]) -> None:
        if not picks:
            self._send(f"⚽ <b>Picks de hoje — {date}</b>\nNenhuma aposta de valor encontrada hoje.")
            return

        lines = [f"⚽ <b>Picks de hoje — {date}</b>", "━━━━━━━━━━━━━━━━━━"]
        for i, p in enumerate(picks, start=1):
            sign = "+" if p.ev >= 0 else ""
            lines.append(
                f"{i}. {p.match}\n"
                f"   Pick: {p.selection}\n"
                f"   Odd: {p.odds:.2f} | Prob. modelo: {p.model_probability:.0%} | "
                f"EV: {sign}{p.ev:.1%} | Stake sugerida: {p.suggested_stake_fraction:.1%} da banca"
            )
        self._send("\n".join(lines))
