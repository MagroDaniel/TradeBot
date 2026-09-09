"""Envio de mensagens pro Telegram — sinal técnico com entrada/stop/alvo.

**Nunca sugere alavancagem** — decisão deliberada (ver CLAUDE.md): é o que mais quebra conta
de quem segue sinal alheio, e marca registrada de canal predatório de "sinais VIP". Quem
operar decide o próprio gerenciamento de risco fora do bot.
"""
from __future__ import annotations

import logging

import requests

from analysis.performance import PerformanceSummary
from storage.signals_store import SignalRecord

logger = logging.getLogger(__name__)

_SIGNAL_DISCLAIMER = (
    "⚠️ <i>Análise técnica não é garantia de nada — é um método transparente, não uma "
    "certeza. Gerencie seu próprio risco; este bot NUNCA sugere alavancagem.</i>"
)

_RESULT_LABELS = {
    "target_hit": ("✅", "Alvo atingido"),
    "stop_hit": ("❌", "Stop atingido"),
    "expired": ("⌛", "Expirado sem bater alvo ou stop"),
}


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

    def send_signal_alert(self, signal: SignalRecord) -> None:
        icon = "🟢" if signal.direction == "long" else "🔴"
        direction_label = "COMPRA (long)" if signal.direction == "long" else "VENDA (short)"
        lines = [
            f"{icon} <b>{signal.symbol} — {direction_label}</b>",
            "",
            f"Entrada: {signal.entry:.6g}",
            f"Stop: {signal.stop_loss:.6g}",
            f"Alvo: {signal.target:.6g}",
            f"RSI: {signal.rsi_value:.0f}",
            f"Mercado: {signal.market_mode.upper()}",
            "",
            f"<i>{signal.reason}</i>",
            "",
            _SIGNAL_DISCLAIMER,
        ]
        self._send("\n".join(lines))

    def send_result(self, signal: SignalRecord) -> None:
        icon, label = _RESULT_LABELS.get(signal.status, ("ℹ️", signal.status))
        close_price = f"{signal.close_price:.6g}" if signal.close_price is not None else "?"
        lines = [
            f"{icon} <b>{signal.symbol} — {label}</b>",
            f"{signal.direction.upper()} · Entrada: {signal.entry:.6g} · Fechou: {close_price}",
        ]
        self._send("\n".join(lines))

    def send_daily_report(
        self, report_date: str, summary: PerformanceSummary, records: list[SignalRecord]
    ) -> None:
        """Relatório do dia anterior — meia-noite BRT é o corte (ver `data/schedule.py`),
        já que cripto não tem "fechamento de pregão". Lista TODOS os sinais resolvidos no
        dia, vitória e derrota — nunca filtra pra esconder perda (ver CLAUDE.md)."""
        if not records:
            self._send(f"📊 <b>Relatório do dia — {report_date}</b>\nNenhum sinal resolvido nesse dia.")
            return

        lines = [f"📊 <b>Relatório do dia — {report_date}</b>", ""]
        for r in records:
            icon, label = _RESULT_LABELS.get(r.status, ("ℹ️", r.status))
            close_price = f"{r.close_price:.6g}" if r.close_price is not None else "?"
            lines.append(f"{icon} {r.symbol} {r.direction.upper()} — {label} (fechou {close_price})")

        lines.append("")
        lines.append(
            f"<b>Resumo:</b> {summary.wins}✅ / {summary.losses}❌ / {summary.expired}⌛ "
            f"— acerto de {summary.win_rate:.0%} (sobre sinais decisivos, sem contar expirados)"
        )
        self._send("\n".join(lines))
