"""Dimensionamento de stake via critério de Kelly (fracionário).

O bot só SUGERE o percentual de banca na mensagem do Telegram — a decisão
final e a execução da aposta continuam manuais e são do usuário.
"""
from __future__ import annotations


def kelly_fraction(model_probability: float, decimal_odds: float, fraction: float = 0.25) -> float:
    """Fração da banca sugerida para a aposta (0.0 se não há edge positivo)."""
    b = decimal_odds - 1  # lucro líquido por unidade apostada
    if b <= 0:
        return 0.0

    q = 1 - model_probability
    full_kelly = (b * model_probability - q) / b
    if full_kelly <= 0:
        return 0.0

    return full_kelly * fraction


def capped_stake(
    model_probability: float,
    decimal_odds: float,
    fraction: float = 0.25,
    max_stake: float = 0.03,
) -> float:
    """Kelly fracionário com trava de segurança (percentual máximo da banca por aposta)."""
    return min(kelly_fraction(model_probability, decimal_odds, fraction), max_stake)
