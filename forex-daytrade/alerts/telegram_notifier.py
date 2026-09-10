"""Envio de mensagens pro Telegram — sinal técnico com entrada/stop/alvo. Mesmo bot/grupo do
`crypto-daytrade` (decisão do usuário, 2026-09-09) — reaproveita `TELEGRAM_BOT_TOKEN`/
`TELEGRAM_CHAT_ID`, não são credenciais novas.

**Nunca sugere alavancagem** — mesma decisão do bot de cripto (ver CLAUDE.md): é o que mais
quebra conta de quem segue sinal alheio, e marca registrada de canal predatório de "sinais
VIP". Quem operar decide o próprio gerenciamento de risco fora do bot. Em forex de varejo isso
é ainda mais relevante que em cripto — a maioria das corretoras só opera com margem/alavancagem
embutida no próprio instrumento; o bot continua nunca dizendo QUANTO usar.
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

_EXPERIMENTAL_DISCLAIMER = (
    "🧪 <i>MODO OBSERVAÇÃO — esta estratégia (notícia/surpresa econômica) ainda NÃO foi "
    "validada por backtest contra histórico real (não existe fonte gratuita com esse dado — "
    "ver README). Isto NÃO é uma recomendação de operação, é acompanhamento pra decidir mais "
    "pra frente, com dado real, se vira sinal de produção. Gerencie seu próprio risco; nunca "
    "alavancagem.</i>"
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

    def send_signal_alert(self, signal: SignalRecord) -> None:
        icon = "🟢" if signal.direction == "long" else "🔴"
        direction_label = "COMPRA (long)" if signal.direction == "long" else "VENDA (short)"
        lines = [
            f"{icon} <b>[FOREX] {signal.symbol} — {direction_label}</b>",
            "",
            f"Entrada: {signal.entry:.5f}",
            f"Stop: {signal.stop_loss:.5f}",
            f"Alvo: {signal.target:.5f}",
            f"RSI: {signal.rsi_value:.0f}",
            "",
            f"<i>{signal.reason}</i>",
            "",
            _SIGNAL_DISCLAIMER,
        ]
        self._send("\n".join(lines))

    def send_result(self, signal: SignalRecord) -> None:
        icon, label = _RESULT_LABELS.get(signal.status, ("ℹ️", signal.status))
        close_price = f"{signal.close_price:.5f}" if signal.close_price is not None else "?"
        lines = [
            f"{icon} <b>[FOREX] {signal.symbol} — {label}</b>",
            f"{signal.direction.upper()} · Entrada: {signal.entry:.5f} · Fechou: {close_price}",
        ]
        self._send("\n".join(lines))

    def send_daily_report(
        self, report_date: str, summary: PerformanceSummary, records: list[SignalRecord]
    ) -> None:
        """Relatório do dia anterior — meia-noite BRT é o corte (ver `data/schedule.py`).
        Lista TODOS os sinais resolvidos no dia, vitória e derrota — nunca filtra pra esconder
        perda (ver CLAUDE.md)."""
        if not records:
            self._send(
                f"📊 <b>[FOREX] Relatório do dia — {report_date}</b>\nNenhum sinal resolvido nesse dia."
            )
            return

        lines = [f"📊 <b>[FOREX] Relatório do dia — {report_date}</b>", ""]
        for r in records:
            icon, label = _RESULT_LABELS.get(r.status, ("ℹ️", r.status))
            close_price = f"{r.close_price:.5f}" if r.close_price is not None else "?"
            lines.append(f"{icon} {r.symbol} {r.direction.upper()} — {label} (fechou {close_price})")

        lines.append("")
        lines.append(
            f"<b>Resumo:</b> {summary.wins}✅ / {summary.losses}❌ / {summary.expired}⌛ "
            f"— acerto de {summary.win_rate:.0%} (sobre sinais decisivos, sem contar expirados)"
        )
        self._send("\n".join(lines))

    def _send_periodic_report(
        self,
        title: str,
        period_label: str,
        summary: PerformanceSummary,
        records: list[SignalRecord],
    ) -> None:
        """Mesmo formato do relatório diário (lista TODO sinal resolvido no período, vitória
        e derrota — nunca esconde perda, ver CLAUDE.md do cripto), reaproveitado pelo semanal
        e pelo mensal — só muda o título e a janela de tempo."""
        if not records:
            self._send(f"{title} — {period_label}</b>\nNenhum sinal resolvido nesse período.")
            return

        lines = [f"{title} — {period_label}</b>", ""]
        for r in records:
            icon, label = _RESULT_LABELS.get(r.status, ("ℹ️", r.status))
            close_price = f"{r.close_price:.5f}" if r.close_price is not None else "?"
            lines.append(f"{icon} {r.symbol} {r.direction.upper()} — {label} (fechou {close_price})")

        lines.append("")
        lines.append(
            f"<b>Resumo:</b> {summary.wins}✅ / {summary.losses}❌ / {summary.expired}⌛ "
            f"— acerto de {summary.win_rate:.0%} (sobre sinais decisivos, sem contar expirados)"
        )
        self._send("\n".join(lines))

    def send_weekly_report(
        self, period_start: str, period_end: str, summary: PerformanceSummary, records: list[SignalRecord]
    ) -> None:
        """Toda segunda-feira (BRT) — resume os sinais fechados nos últimos 7 dias."""
        self._send_periodic_report(
            "📅 <b>[FOREX] Relatório semanal", f"{period_start} a {period_end}", summary, records
        )

    def send_monthly_report(
        self, month_label: str, summary: PerformanceSummary, records: list[SignalRecord]
    ) -> None:
        """Todo dia 1 (BRT) — resume os sinais fechados no mês calendário anterior."""
        self._send_periodic_report("🗓️ <b>[FOREX] Relatório mensal", month_label, summary, records)

    # --- Estratégia de notícia (experimental — ver analysis/news_signals.py) ---
    #
    # Métodos separados de propósito, em vez de reaproveitar send_signal_alert/send_result:
    # essa estratégia não passou pelo mesmo processo de validação por backtest das outras (não
    # existe fonte gratuita de histórico "actual" pra testar), então a mensagem PRECISA deixar
    # isso explícito — nunca pode ser confundida com um sinal de produção validado.

    def send_experimental_signal_alert(self, signal: SignalRecord) -> None:
        icon = "🟢" if signal.direction == "long" else "🔴"
        direction_label = "COMPRA (long)" if signal.direction == "long" else "VENDA (short)"
        lines = [
            f"🧪 {icon} <b>[FOREX-NOTÍCIA] {signal.symbol} — {direction_label}</b>",
            "",
            f"Entrada: {signal.entry:.5f}",
            f"Stop: {signal.stop_loss:.5f}",
            f"Alvo: {signal.target:.5f}",
            "",
            f"<i>{signal.reason}</i>",
            "",
            _EXPERIMENTAL_DISCLAIMER,
        ]
        self._send("\n".join(lines))

    def send_experimental_result(self, signal: SignalRecord) -> None:
        icon, label = _RESULT_LABELS.get(signal.status, ("ℹ️", signal.status))
        close_price = f"{signal.close_price:.5f}" if signal.close_price is not None else "?"
        lines = [
            f"🧪 {icon} <b>[FOREX-NOTÍCIA] {signal.symbol} — {label}</b>",
            f"{signal.direction.upper()} · Entrada: {signal.entry:.5f} · Fechou: {close_price}",
            "<i>(modo observação — resultado real, mas estratégia ainda não validada)</i>",
        ]
        self._send("\n".join(lines))
