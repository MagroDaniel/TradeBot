"""Envio de mensagens para o Telegram via Bot API.

Mensagens agrupadas por competição e depois por jogo (um jogo pode gerar vários picks —
ex: vencedor + over/under — e listar cada um separado com o confronto repetido fica poluído).
Datas e horários em BRT, formato dd/mm — ver `data/schedule.py`.
"""
from __future__ import annotations

import logging
from collections import defaultdict

import requests

from analysis.multiple import Multiple
from data.schedule import format_date_br, format_time_brt
from storage.picks_store import Pick

logger = logging.getLogger(__name__)

# Nome + emoji de exibição por sport_key (usado só na formatação da mensagem). Competição
# sem entrada aqui cai no fallback genérico — não precisa atualizar isso pra SPORT_KEYS
# funcionar, só deixa a mensagem menos bonita.
_COMPETITION_LABELS: dict[str, str] = {
    "soccer_brazil_campeonato": "🇧🇷 Brasileirão Série A",
    "soccer_epl": "🏴 Premier League",
    "soccer_spain_la_liga": "🇪🇸 La Liga",
    "soccer_germany_bundesliga": "🇩🇪 Bundesliga",
    "soccer_italy_serie_a": "🇮🇹 Serie A",
    "soccer_france_ligue_one": "🇫🇷 Ligue 1",
    "soccer_uefa_champs_league": "🏆 Champions League",
    "soccer_uefa_europa_league": "🥈 Europa League",
    "soccer_uefa_europa_conference_league": "🥉 Conference League",
}

_EV_EXPLAINER = (
    "💡 <i>EV é a vantagem estimada sobre a odd do mercado: quanto o modelo acha que a odd "
    "está paga a mais do que a chance real do resultado. EV +20% ≈ a odd paga uns 20% a mais "
    "do que deveria, se o modelo estiver certo. Quanto maior, mais \"de valor\" — mas EV muito "
    "alto (acima de 50%) também pode ser sinal de erro do modelo, não de oportunidade real. "
    "Revise antes de apostar.</i>"
)

_MULTIPLE_EXPLAINER = (
    "⚠️ <i>Prioriza probabilidade, não valor — as pernas são as de maior chance do dia, mesmo "
    "sem ser pick +EV. EV combinado costuma ser negativo (a casa cobra margem em cada perna) e "
    "uma perna errada derruba o bilhete inteiro. Informativo, não entra no cálculo de stake do "
    "bot — a decisão e o valor apostado são só seus.</i>"
)


def _competition_label(sport_key: str) -> str:
    return _COMPETITION_LABELS.get(sport_key, f"⚽ {sport_key}")


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
        display_date = format_date_br(date)
        resolved = [p for p in picks if p.result is not None]
        if not resolved:
            self._send(f"📊 <b>Resultado — {display_date}</b>\nNenhum pick resolvido nesse dia.")
            return

        by_competition: dict[str, dict[str, list[Pick]]] = defaultdict(lambda: defaultdict(list))
        for p in resolved:
            sport_key = p.market.split(":", 1)[0]
            by_competition[sport_key][p.match].append(p)

        lines = [f"📊 <b>Resultado — {display_date}</b>", ""]
        for sport_key, matches in by_competition.items():
            lines.append(_competition_label(sport_key))
            for match, match_picks in matches.items():
                lines.append(f"<b>{match}</b>")
                for p in match_picks:
                    icon = "✅" if p.result == "green" else "❌"
                    profit = p.profit_units or 0
                    sign = "+" if profit >= 0 else ""
                    odd_label = f"odd {p.odds:.2f}" + (f" ({p.bookmaker})" if p.bookmaker else "")
                    lines.append(f"{icon} {p.selection} · {odd_label} · {sign}{profit:.1%}")
                lines.append("")

        greens = [p for p in resolved if p.result == "green"]
        total_profit = sum(p.profit_units or 0 for p in resolved)
        sign_total = "+" if total_profit >= 0 else ""
        lines.append("━━━━━━━━━━━━━━━")
        lines.append(
            f"💰 <b>Saldo:</b> {sign_total}{total_profit:.1%} da banca  ·  "
            f"🎯 <b>Acertos:</b> {len(greens)}/{len(resolved)}"
        )
        self._send("\n".join(lines).rstrip())

    def send_daily_picks(
        self,
        date: str,
        picks: list[Pick],
        games_today: int = 0,
        news_notes: dict[str, str] | None = None,
        multiple: Multiple | None = None,
    ) -> None:
        display_date = format_date_br(date)
        lines = [f"⚽ <b>Picks de hoje — {display_date}</b>"]

        if not picks:
            if games_today == 0:
                lines.append("😴 Sem jogos hoje nas competições acompanhadas.")
            else:
                lines.append(f"🔍 {games_today} jogo(s) hoje, nenhuma aposta de valor encontrada.")
        else:
            by_competition: dict[str, dict[tuple[str, str], list[Pick]]] = defaultdict(
                lambda: defaultdict(list)
            )
            for p in picks:
                sport_key = p.market.split(":", 1)[0]
                by_competition[sport_key][(p.match, p.commence_time)].append(p)

            lines += ["━━━━━━━━━━━━━━━", ""]
            for sport_key, matches in by_competition.items():
                lines.append(f"<b>{_competition_label(sport_key)}</b>")
                for (match, commence_time), match_picks in sorted(
                    matches.items(), key=lambda kv: kv[0][1]
                ):
                    lines.append(f"🕐 {format_time_brt(commence_time)} — {match}")
                    note = (news_notes or {}).get(match)
                    if note:
                        lines.append(f"   ⚠️ <i>{note}</i>")
                    for p in match_picks:
                        sign = "+" if p.ev >= 0 else ""
                        odd_label = f"odd {p.odds:.2f}" + (f" ({p.bookmaker})" if p.bookmaker else "")
                        lines.append(f"   🎯 {p.selection} — {odd_label}")
                        lines.append(
                            f"   📈 EV {sign}{p.ev:.0%}  ·  💵 {p.suggested_stake_fraction:.1%} banca"
                        )
                    lines.append("")
                lines.append("")

            lines.append("━━━━━━━━━━━━━━━")
            lines.append(f"<i>{len(picks)} pick(s) em {len(by_competition)} competição(ões) hoje</i>")
            lines.append("")
            lines.append(_EV_EXPLAINER)

        if multiple:
            lines.append("")
            lines.extend(self._format_multiple(multiple))

        self._send("\n".join(lines).rstrip())

    def _format_multiple(self, multiple: Multiple) -> list[str]:
        lines = ["━━━━━━━━━━━━━━━", "🎫 <b>Bilhete sugerido (múltipla)</b>", ""]
        for i, leg in enumerate(multiple.legs, start=1):
            bookmaker = f" ({leg.bookmaker})" if leg.bookmaker else ""
            lines.append(f"{i}. {leg.match} — {leg.selection} — odd {leg.odds:.2f}{bookmaker}")
        lines.append("")
        sign = "+" if multiple.combined_ev >= 0 else ""
        lines.append(f"💰 <b>Odd combinada:</b> {multiple.combined_odds:.2f}")
        lines.append(f"🎲 <b>Probabilidade estimada:</b> {multiple.combined_probability:.0%}")
        lines.append(f"📊 <b>EV combinado:</b> {sign}{multiple.combined_ev:.0%}")
        lines.append("")
        lines.append(_MULTIPLE_EXPLAINER)
        return lines
