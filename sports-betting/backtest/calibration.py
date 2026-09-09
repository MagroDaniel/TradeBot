"""Calibração do modelo de Poisson: a probabilidade prevista bate com a frequência observada?

Contexto (ver docs/estrategias_extraidas_livros.md, item 3): o Soccermatics (David Sumpter)
mostra, com dados reais de odds da Premier League 2014/15, que o MERCADO subprecifica favoritos
fortes e empates entre times equilibrados. A gente não pode repetir esse teste — os CSVs em
`data/historical/` (ver `data/historical_loader.py`) só têm placar, nunca tiveram odds. O que dá
pra testar com o dado que existe é uma pergunta relacionada, mas diferente: **o nosso próprio
modelo de Poisson é bem calibrado**, ou tem viés sistemático em alguma faixa de probabilidade
(favorito forte, jogo equilibrado etc.)? Isso não confirma nem descarta o viés de mercado do
livro — só testa se o `PoissonModel` já tem, por conta própria, algum desvio sistemático entre o
que prevê e o que realmente acontece.

Método: separa os jogos por data em treino (mais antigos) e teste (mais recentes), calibra o
modelo só com o treino, prevê cada jogo do teste, e agrupa as previsões em faixas de
probabilidade (bins) por resultado (`home_win`/`draw`/`away_win`), comparando a probabilidade
média prevista de cada faixa com a frequência real de acerto nela. Não é walk-forward completo
(não recalibra a cada jogo/temporada) — um split simples é suficiente pra detectar viés
sistemático sem centenas de re-treinos, e o modelo já pondera jogos recentes mais que antigos via
`half_life_days`. Função pura, sem I/O — quem chama fornece a lista de partidas (já carregada via
`data/historical_loader.py`) e decide o que fazer com o relatório.
"""
from __future__ import annotations

from dataclasses import dataclass

from model.poisson_model import MatchResult, PoissonModel

_OUTCOMES = ("home_win", "draw", "away_win")


@dataclass(frozen=True)
class CalibrationBin:
    outcome: str  # "home_win" | "draw" | "away_win"
    prob_low: float
    prob_high: float
    n: int
    predicted_avg: float
    observed_rate: float

    @property
    def gap(self) -> float:
        """Observado menos previsto — positivo significa que o modelo SUBESTIMA esse resultado
        nessa faixa (aconteceu mais do que o modelo achava); negativo, que SUPERESTIMA."""
        return self.observed_rate - self.predicted_avg


def split_train_test(
    matches: list[MatchResult], test_fraction: float = 0.2
) -> tuple[list[MatchResult], list[MatchResult]]:
    """Separa por data (jogos sem data ficam no treino, no início — não há como situá-los no
    tempo em relação aos demais). `test_fraction` dos jogos MAIS RECENTES vira o conjunto de
    teste, nunca visto pelo `fit()`."""
    dated = sorted((m for m in matches if m.match_date is not None), key=lambda m: m.match_date)
    undated = [m for m in matches if m.match_date is None]
    cutoff = int(len(dated) * (1 - test_fraction))
    return undated + dated[:cutoff], dated[cutoff:]


def _outcome_of(match: MatchResult) -> str:
    if match.home_goals > match.away_goals:
        return "home_win"
    if match.home_goals == match.away_goals:
        return "draw"
    return "away_win"


def calibration_report(
    train: list[MatchResult],
    test: list[MatchResult],
    half_life_days: float | None = 1095,
    bin_size: float = 0.1,
    min_bin_size: int = 20,
) -> list[CalibrationBin]:
    """Calibra um `PoissonModel` só com `train` e avalia contra `test`. Times do teste sem
    histórico no treino são pulados (mesmo comportamento de produção: `KeyError` capturado e
    ignorado, não derruba o relatório). Bins com menos de `min_bin_size` jogos são descartados —
    amostra pequena demais pra falar de viés sistemático."""
    model = PoissonModel(half_life_days=half_life_days).fit(train)

    # (outcome, prob_prevista, aconteceu) por combinação resultado×jogo — cada jogo do teste
    # gera 3 pontos, um por resultado possível, igual ao gráfico de calibração do Soccermatics.
    points: list[tuple[str, float, bool]] = []
    for match in test:
        try:
            probs = model.match_probabilities(match.home_team, match.away_team)
        except KeyError:
            continue
        actual = _outcome_of(match)
        for outcome in _OUTCOMES:
            points.append((outcome, probs[outcome], outcome == actual))

    bins: list[CalibrationBin] = []
    n_bins = max(1, round(1 / bin_size))
    for outcome in _OUTCOMES:
        outcome_points = [p for p in points if p[0] == outcome]
        for i in range(n_bins):
            low, high = i * bin_size, (i + 1) * bin_size
            in_bin = [
                p for p in outcome_points if low <= p[1] < high or (high >= 1.0 and p[1] == 1.0)
            ]
            if len(in_bin) < min_bin_size:
                continue
            predicted_avg = sum(p[1] for p in in_bin) / len(in_bin)
            observed_rate = sum(1 for p in in_bin if p[2]) / len(in_bin)
            bins.append(
                CalibrationBin(
                    outcome=outcome,
                    prob_low=low,
                    prob_high=high,
                    n=len(in_bin),
                    predicted_avg=predicted_avg,
                    observed_rate=observed_rate,
                )
            )
    return bins
