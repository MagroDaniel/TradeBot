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
