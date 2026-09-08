"""Mapeamento de nomes de times entre a The Odds API e o CSV histórico do Brasileirão
(adaoduque/Brasileirao_Dataset).

As duas fontes usam nomenclaturas diferentes pro mesmo time (ex: "Botafogo" na Odds API
vs. "Botafogo-RJ" no dataset). Sem esse mapeamento, PoissonModel.match_probabilities()
levanta KeyError e o time é pulado silenciosamente em main.py — o que é o comportamento
certo pra times sem dado nenhum, mas errado pra times que só têm nome diferente.

Ajuste este dict sempre que a Odds API retornar um nome que não bate com o CSV
(rode o script de diagnóstico comparando os dois conjuntos de nomes pra achar novos casos).
Times sem entrada aqui são buscados pelo nome original — inclui times genuinamente sem
histórico no CSV (ex: recém-promovidos à Série A), que continuam sendo pulados como hoje.
"""
from __future__ import annotations

TEAM_ALIASES: dict[str, str] = {
    "Atletico Mineiro": "Atletico-MG",
    "Atletico Paranaense": "Athletico-PR",
    "Botafogo": "Botafogo-RJ",
    "Bragantino-SP": "Bragantino",
    "Grêmio": "Gremio",
    "Vasco da Gama": "Vasco",
}


def normalize_team_name(name: str) -> str:
    """Traduz um nome de time da Odds API pro nome equivalente no CSV histórico,
    quando houver um alias cadastrado. Times sem alias voltam inalterados."""
    return TEAM_ALIASES.get(name, name)
