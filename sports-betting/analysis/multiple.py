"""Bilhete de múltipla sugerido: combina as seleções de MAIOR PROBABILIDADE do dia (uma por
jogo), não as de maior EV — é uma aposta de confiança, não de valor.

Deliberadamente separado de `ev.py`/`kelly.py`: aqui o critério de escolha é
`model_probability`, ignorando se a seleção teria EV positivo sozinha. Isso é esperado gerar
EV combinado negativo com frequência (a casa de apostas cobra margem em cada perna, e o produto
dessas margens cresce rápido) — decisão explícita do usuário depois de eu apresentar a
alternativa (só combinar picks já +EV, o que na prática teria pernas demais dias sem picks
suficientes para montar um bilhete com odd relevante). Puramente informativo: não alimenta
`storage/picks_store.py` nem o sizing de stake do resto do bot (mesmo espírito do aviso de
notícias em `data/news_check.py` — contexto extra, não um pick tratado como os demais).

Função pura, sem I/O — só combina odds/probabilidades já calculadas em main.py.
"""
from __future__ import annotations

from dataclasses import dataclass

from analysis.ev import calculate_ev


@dataclass
class MultipleLeg:
    match: str
    selection: str
    odds: float
    bookmaker: str | None
    model_probability: float


@dataclass
class Multiple:
    legs: list[MultipleLeg]
    combined_odds: float
    combined_probability: float
    combined_ev: float  # informativo — pode ser negativo, não é critério de seleção


def build_multiple(candidates: list[MultipleLeg], num_legs: int) -> Multiple | None:
    """Monta o bilhete com as `num_legs` pernas de maior `model_probability` entre `candidates`.

    Assume que quem chama já garante **uma perna por jogo** em `candidates` (ver
    `main.py::_best_leg_for_multiple`) — combinar duas seleções do mesmo jogo violaria a
    independência assumida no produto de probabilidades/odds abaixo. Retorna `None` se
    `num_legs <= 0` (recurso desativado via `config.MULTIPLE_LEGS=0`) ou se não houver jogos
    suficientes hoje para preencher o bilhete (ex: 2 jogos no calendário e `num_legs=4`) — nesse
    caso não sugere um bilhete "incompleto".

    Odd combinada = produto das odds; probabilidade combinada = produto das probabilidades do
    modelo — assume jogos independentes entre si, aproximação razoável pra jogos diferentes
    (mesma aproximação implícita em qualquer bilhete de múltipla real).
    """
    if num_legs <= 0 or len(candidates) < num_legs:
        return None

    top = sorted(candidates, key=lambda c: c.model_probability, reverse=True)[:num_legs]

    combined_odds = 1.0
    combined_probability = 1.0
    for leg in top:
        combined_odds *= leg.odds
        combined_probability *= leg.model_probability

    return Multiple(
        legs=top,
        combined_odds=combined_odds,
        combined_probability=combined_probability,
        combined_ev=calculate_ev(combined_probability, combined_odds),
    )
