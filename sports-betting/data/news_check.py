"""Checa notícias recentes (lesões, suspensões, desfalques) pros jogos que geraram picks
hoje, usando o Claude com busca na web.

Puramente informativo — NÃO ajusta a probabilidade do modelo nem o EV. Só anexa um aviso
textual curto na mensagem do Telegram pro usuário decidir manualmente. Traduzir "jogador X
machucado" num ajuste numérico na força do time seria uma heurística subjetiva demais pra
confiar sem supervisão — decisão deliberada de manter isso como contexto, não como input do
modelo.

Opcional: requer ANTHROPIC_API_KEY no .env. Sem ela, main.py simplesmente pula essa etapa
(ver `config.ANTHROPIC_API_KEY`) — o bot funciona normal sem esse recurso.
"""
from __future__ import annotations

import logging

import anthropic

logger = logging.getLogger(__name__)

_MODEL = "claude-opus-5"
_NO_NEWS_MARKER = "NADA"

_PROMPT_TEMPLATE = (
    "Pesquise notícias recentes sobre a partida de futebol {home_team} x {away_team} "
    "({competition}). Há algum jogador importante machucado, suspenso, ou fora por qualquer "
    "motivo relevante pra esse jogo específico? Responda em português, no máximo 2 frases "
    'curtas e diretas. Se não encontrar nada relevante ou não tiver certeza, responda '
    f'exatamente "{_NO_NEWS_MARKER}", sem mais nada. Não narre o que você está fazendo (não '
    'diga "vou pesquisar" etc.) — só a resposta final.'
)


class NewsChecker:
    def __init__(self, api_key: str) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)

    def check_match(self, home_team: str, away_team: str, competition: str) -> str | None:
        """Retorna um aviso curto em português se achar algo relevante pro confronto, ou
        None se não achar nada relevante ou a checagem falhar (nunca levanta exceção —
        essa é uma etapa opcional, não pode derrubar o envio dos picks)."""
        prompt = _PROMPT_TEMPLATE.format(
            home_team=home_team, away_team=away_team, competition=competition
        )
        try:
            response = self._client.messages.create(
                model=_MODEL,
                max_tokens=1024,
                output_config={"effort": "low"},
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 2}],
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception:
            logger.exception("Falha ao checar notícias para %s x %s", home_team, away_team)
            return None

        # Pega só o último bloco de texto — blocos anteriores podem ser narração do processo
        # ("vou pesquisar...") intercalada com o uso da ferramenta de busca, não a resposta final.
        text_blocks = [b.text for b in response.content if b.type == "text"]
        text = text_blocks[-1].strip() if text_blocks else ""
        if not text or _NO_NEWS_MARKER in text:
            return None
        return text
