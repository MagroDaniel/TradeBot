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


def cap_group_exposure(stakes: list[float], max_stake: float = 0.03) -> list[float]:
    """Reduz proporcionalmente um grupo de stakes se a soma ultrapassar `max_stake` — mesmo teto
    usado por `capped_stake` numa aposta individual, aqui aplicado à soma do grupo inteiro.

    Existe porque `capped_stake` só trava CADA aposta, não a soma de várias apostas que não são
    independentes entre si (ex: vários mercados do mesmo jogo — "empate" e "under 2.5" tendem a
    ganhar ou perder juntos, já que dependem do mesmo resultado final). Sem isso, um jogo com
    valor em 5 mercados diferentes pode concentrar 5× o teto pretendido na banca de uma vez —
    foi exatamente o que aconteceu num dia real de operação (ver main.py::_cap_match_exposure e
    docs/estrategias_extraidas_livros.md).

    Não faz nada se a soma já estiver dentro do limite (ou se `stakes` for vazio/soma zero)."""
    total = sum(stakes)
    if total <= max_stake or total <= 0:
        return list(stakes)
    scale = max_stake / total
    return [s * scale for s in stakes]
