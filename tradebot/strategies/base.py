"""Contrato de uma estratégia: decide ENTRADA (e opcionalmente saída antecipada), nada mais.

Separação controller/executor do Hummingbot: a estratégia não sabe de saldo, ordem, taxa ou
risco — só olha candles fechados e devolve um `Signal` (ou `None`). Dimensionar posição,
checar limites e executar é trabalho de `risk.py`, `engine.py` e do broker. Assim a mesma
estratégia roda igual no backtest e ao vivo, e trocar de estratégia não mexe no resto.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tradebot.models import Candle, Position, Signal


@dataclass(frozen=True)
class Param:
    """Um parâmetro ajustável pelo painel. `kind` decide o widget e a conversão."""

    default: Any
    label: str
    kind: str = "float"  # float | int | bool | choice | text
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] = ()
    help: str = ""

    def coerce(self, raw: Any) -> Any:
        if self.kind == "bool":
            if isinstance(raw, str):
                return raw.strip().lower() in {"1", "true", "on", "sim", "yes"}
            return bool(raw)
        if self.kind == "text":
            return str(raw).strip()
        if self.kind == "choice":
            value = str(raw)
            if value not in self.choices:
                raise ValueError(f"{self.label}: '{value}' não é uma opção válida")
            return value
        value = int(float(raw)) if self.kind == "int" else float(raw)
        if self.min is not None and value < self.min:
            raise ValueError(f"{self.label}: mínimo é {self.min}")
        if self.max is not None and value > self.max:
            raise ValueError(f"{self.label}: máximo é {self.max}")
        return value


TIMEFRAMES = ("5m", "15m", "30m", "1h", "2h", "4h")

TIMEFRAME_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440}


class Strategy:
    # "candles": decide por candles (backtest/pesquisa se aplicam). "copy": segue outra carteira
    # (o motor usa `engine._sync_copy`, sem `generate`).
    kind: str = "candles"
    name: str = ""
    label: str = ""
    description: str = ""
    params: dict[str, Param] = {}

    def defaults(self) -> dict[str, Any]:
        return {key: p.default for key, p in self.params.items()}

    def resolve(self, overrides: dict[str, Any] | None) -> dict[str, Any]:
        """Defaults + overrides validados. Chave desconhecida é ignorada (config antiga de
        uma versão anterior da estratégia não deve impedir o app de abrir)."""
        resolved = self.defaults()
        for key, raw in (overrides or {}).items():
            if key in self.params:
                resolved[key] = self.params[key].coerce(raw)
        return resolved

    def timeframe(self, p: dict[str, Any]) -> str:
        return p.get("timeframe", "15m")

    def higher_timeframe(self, p: dict[str, Any]) -> str | None:
        return None

    def warmup(self, p: dict[str, Any]) -> int:
        """Quantos candles fechados a estratégia precisa pra decidir."""
        return 100

    def generate(
        self, symbol: str, candles: list[Candle], htf_candles: list[Candle] | None, p: dict[str, Any]
    ) -> Signal | None:
        raise NotImplementedError

    def should_exit(self, position: Position, candles: list[Candle], p: dict[str, Any]) -> bool:
        """Saída antecipada decidida pela estratégia (ex: preço voltou pra média). Avaliada só
        no fechamento de candle. Default: nunca — stop/alvo/tempo/trailing cuidam da saída."""
        return False
