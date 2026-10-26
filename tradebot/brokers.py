"""Brokers — quem de fato executa a ordem. Hoje só existe o `PaperBroker` (demo local).

Contrato pensado pra receber depois um broker da Binance Demo e um real sem mudar o motor:
o motor só chama `open`/`close`/`cash`/`equity`. Stop/alvo/trailing são gerenciados pelo
motor (stop "por software", como o PositionExecutor do Hummingbot) — num broker real vale
também mandar um stop na própria corretora como rede de segurança, caso o app caia.

Modelo de margem (spot e futuros sem alavancagem — decisão do projeto, nunca alavancagem):
abrir reserva `qty × preço` do caixa + taxa; fechar devolve a reserva + P&L − taxa. No spot
isso equivale a comprar e vender a moeda; em futuros 1x é a margem isolada.
"""
from __future__ import annotations

from dataclasses import dataclass

from tradebot.market_data import OrderBook
from tradebot.models import LONG, Position


class OrderRejected(Exception):
    """Ordem não executada (saldo, slippage, tamanho mínimo...). O motor registra e segue."""


@dataclass(frozen=True)
class Fill:
    price: float  # preço médio executado
    qty: float
    fee: float  # em USDT


def simulate_market_fill(book: OrderBook, buy: bool, qty: float) -> float:
    """Preço médio de uma ordem a mercado "comendo" o livro de ofertas real, nível a nível —
    mesma ideia do dry-run do Freqtrade. Ordem maior que a profundidade disponível herda o
    pior nível visto + 0,5% (pessimista de propósito: na prática o livro tem mais níveis,
    mas não sabemos a que preço)."""
    levels = book.asks if buy else book.bids
    if not levels:
        raise OrderRejected("Livro de ofertas vazio")
    remaining = qty
    cost = 0.0
    for price, available in levels:
        take = min(remaining, available)
        cost += take * price
        remaining -= take
        if remaining <= 1e-12:
            break
    if remaining > 1e-12:
        worst = levels[-1][0] * (1.005 if buy else 0.995)
        cost += remaining * worst
    return cost / qty


class PaperBroker:
    """Conta demo local: preço e livro de ofertas reais, dinheiro de mentira. Uma carteira por
    (robô, mercado) — robôs diferentes nunca dividem saldo."""

    account = "paper"

    def __init__(self, market: str, store, market_data, fee_rate: float, max_slippage: float = 0.005,
                 bot_id: int = 1) -> None:
        self.market = market
        self.bot_id = bot_id
        self.store = store
        self.data = market_data
        self.fee_rate = fee_rate
        self.max_slippage = max_slippage

    def ensure_wallet(self, initial: float) -> None:
        if self.store.get_wallet(self.account, self.bot_id, self.market) is None:
            self.store.reset_wallet(self.account, self.bot_id, self.market, initial)

    def cash(self) -> float:
        wallet = self.store.get_wallet(self.account, self.bot_id, self.market)
        return wallet["cash"] if wallet else 0.0

    def equity(self, positions: list[Position], prices: dict[str, float]) -> float:
        total = self.cash()
        for p in positions:
            price = prices.get(p.symbol, p.entry_price)
            total += p.qty * p.entry_price + p.gross_pnl(price)
        return total

    def open(self, symbol: str, direction: str, qty: float, ref_price: float) -> Fill:
        book = self.data.order_book(symbol)
        buy = direction == LONG
        price = simulate_market_fill(book, buy, qty)
        slippage = (price / ref_price - 1) if buy else (1 - price / ref_price)
        if slippage > self.max_slippage:
            raise OrderRejected(f"Slippage estimado {slippage:.2%} acima do máximo {self.max_slippage:.2%}")
        notional = qty * price
        fee = notional * self.fee_rate
        if notional + fee > self.cash() + 1e-9:
            raise OrderRejected(f"Saldo insuficiente: precisa {notional + fee:.2f}, tem {self.cash():.2f}")
        self.store.add_cash(self.account, self.bot_id, self.market, -(notional + fee))
        return Fill(price, qty, fee)

    def close(self, position: Position) -> Fill:
        """Fechamento nunca é recusado por slippage — sair da posição tem prioridade."""
        book = self.data.order_book(position.symbol)
        price = simulate_market_fill(book, buy=position.direction != LONG, qty=position.qty)
        fee = position.qty * price * self.fee_rate
        margin = position.qty * position.entry_price
        self.store.add_cash(self.account, self.bot_id, self.market, margin + position.gross_pnl(price) - fee)
        return Fill(price, position.qty, fee)
