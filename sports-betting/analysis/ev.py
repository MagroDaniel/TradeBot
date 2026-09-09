"""Cálculo de probabilidade implícita, remoção de overround (vig) e Expected Value."""
from __future__ import annotations


def implied_probability(decimal_odds: float) -> float:
    if decimal_odds <= 1:
        raise ValueError("Odds decimais devem ser maiores que 1")
    return 1 / decimal_odds


def remove_overround(implied_probs: list[float]) -> list[float]:
    """Normaliza as probabilidades implícitas de um mercado completo (ex: casa/empate/fora)
    para remover a margem da casa de apostas (overround), assumindo distribuição proporcional.
    Útil para comparar a "odd justa" do mercado com a probabilidade do modelo."""
    total = sum(implied_probs)
    if total <= 0:
        raise ValueError("Soma das probabilidades implícitas deve ser positiva")
    return [p / total for p in implied_probs]


def calculate_ev(model_probability: float, decimal_odds: float) -> float:
    """EV percentual de uma aposta: (prob_modelo * odds) - 1.

    EV > 0 significa que, segundo o modelo, a odd oferecida é maior do que
    a probabilidade real do evento justificaria (aposta de valor / +EV).
    """
    return (model_probability * decimal_odds) - 1


def market_hold(decimal_odds: list[float]) -> float:
    """Hold (margem/vig) de um mercado completo e mutuamente exclusivo: soma das
    probabilidades implícitas de todas as seleções, menos 1. Mesmo cálculo que alimenta
    `remove_overround`, só que aqui devolvemos o hold em si, não as probabilidades normalizadas.

    Usado tanto pro hold "normal" (todas as odds da mesma casa) quanto pro "hold sintético"
    entre casas diferentes — pegando a melhor odd de cada seleção antes de somar, como descrito
    em "The Logic of Sports Betting" (Miller & Davidow) e resumido em
    docs/estrategias_extraidas_livros.md, item 1. Hold baixo/negativo nesse segundo caso é sinal
    de que as casas discordam entre si o suficiente pra que o mercado fique "mais aberto" —
    um sinal independente da nossa própria estimativa de probabilidade.

    `decimal_odds` precisa cobrir TODAS as seleções do mercado (ex: as 3 do 1X2, ou as 2 de
    over/under) — hold de um subconjunto não tem o mesmo significado.
    """
    return sum(implied_probability(o) for o in decimal_odds) - 1
