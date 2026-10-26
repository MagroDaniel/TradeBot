"""Copy trading: segue as posições de uma carteira da Hyperliquid (ver `tradebot/hyperliquid.py`).

Não decide nada por candles — o motor (`Engine._sync_copy`) compara, a cada ciclo, as
posições do trader com as do robô:
- o trader ABRE uma moeda nova → o robô abre a mesma direção em futuros na Binance;
- o trader FECHA (ou inverte) → o robô fecha (e, se inverteu, abre o lado novo);
- posições que o trader já tinha quando o robô foi ligado NÃO são copiadas (entrar no meio de
  um movimento que outro começou é o pior caso do copy trading), a não ser que se peça;
- o trader AUMENTA ou REDUZ a posição (mais que `min_change_pct`) → o robô aumenta/reduz na
  mesma proporção. Redução parcial vira uma linha fechada própria no histórico (com o
  resultado daquela parte); aumento recalcula preço médio e stop.

Tamanho: a fatia da posição na carteira dele, sem a alavancagem dele. Se ele usa 5x, o robô
reduz tudo na mesma proporção pra ficar a 1x — nunca alavancagem (regra do projeto).
Stop próprio obrigatório: não dá pra ver onde está o stop do trader.
"""
from __future__ import annotations

from tradebot.strategies.base import Param, Strategy


class CopyWalletStrategy(Strategy):
    kind = "copy"
    name = "copy_wallet"
    label = "Copiar carteira (Hyperliquid)"
    description = (
        "Segue as aberturas e fechamentos de um trader da Hyperliquid, executando em futuros da "
        "Binance a 1x, com stop próprio."
    )
    params = {
        "wallet": Param("", "Carteira a copiar (0x...)", "text",
                        help="Endereço público do trader na Hyperliquid"),
        "copy_pct": Param(90.0, "Quanto do patrimônio usar (%)", min=5, max=100,
                          help="Se o trader estiver 100% exposto (ou alavancado), o robô usa esta fração do saldo"),
        "stop_pct": Param(5.0, "Stop próprio (% da entrada)", min=0.5, max=50),
        "copy_existing": Param(False, "Copiar também posições que ele já tinha ao ligar", "bool"),
        "follow_size_changes": Param(True, "Acompanhar aumentos e reduções dele", "bool"),
        "min_change_pct": Param(10.0, "Mudança mínima no tamanho dele para acompanhar (%)", min=1, max=90,
                                help="Ignora ajustes pequenos (evita uma ordem por variação mínima)"),
    }

    def timeframe(self, p):
        return "15m"  # só usado pra desenhar o gráfico da posição

    def warmup(self, p):
        return 1

    def generate(self, symbol, candles, htf_candles, p):
        return None
