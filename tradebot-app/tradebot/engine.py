"""Motor de execução: um ciclo (`tick`) a cada `poll_seconds`, numa thread própria.

Cada ciclo, por mercado habilitado (spot / futuros):
1. Lê o último preço de todos os pares (1 requisição) e passa cada posição aberta por
   `position.evaluate_bar` — stop, alvo, trailing e tempo-limite. Sair vem SEMPRE antes de
   entrar (mesma ordem do crypto-daytrade: resolver antes de escanear).
2. Quando fecha um candle do timeframe da estratégia: pergunta à estratégia se alguma posição
   deve sair (`should_exit`) e, se entradas estiverem liberadas, escaneia o universo de pares
   atrás de sinal novo. Cada sinal passa pelo portão de risco (`risk.py`) antes de virar ordem.

Estados: `stopped` (nada roda — posições ficam SEM gerenciamento, o painel avisa),
`running` (tudo) e `paused` (só gerencia/fecha posições, não abre novas — o "parar novas
entradas" do Freqtrade). O estado é salvo e restaurado quando o app reabre, pra uma queda do
app não deixar posições órfãs sem stop.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from tradebot import risk
from tradebot.brokers import OrderRejected, PaperBroker
from tradebot.market_data import BinanceMarketData, closed_only
from tradebot.models import FUTURES, MARKETS, SPOT, Position, reprice_exit_plan
from tradebot.position import evaluate_bar
from tradebot.settings import Settings, load_settings, save_settings
from tradebot.store import Store, now_ms
from tradebot.strategies import get_strategy
from tradebot.strategies.base import TIMEFRAME_MINUTES

logger = logging.getLogger(__name__)

STATES = ("stopped", "running", "paused")
EXIT_REASON_LABELS = {
    "stop_loss": "stop", "trailing_stop": "trailing stop", "take_profit": "alvo", "time_limit": "tempo-limite",
    "strategy_exit": "saída da estratégia", "manual": "manual", "emergency": "PARAR TUDO",
}
CANDLE_SETTLE_MS = 5_000  # espera a Binance consolidar o candle recém-fechado
EQUITY_SNAPSHOT_MS = 5 * 60_000
UNIVERSE_REFRESH_MS = 60 * 60_000


class Engine:
    def __init__(self, store: Store, data_dir: Path, market_data: dict | None = None) -> None:
        self.store = store
        self.data_dir = Path(data_dir)
        self.data = market_data or {m: BinanceMarketData(m) for m in MARKETS}
        self.settings: Settings = load_settings(store)
        self.lock = threading.RLock()
        self.brokers: dict[str, PaperBroker] = {}
        self._last_bucket: dict[str, int] = {}
        self._universe: dict[str, tuple[int, list[str]]] = {}
        self._last_equity_snapshot: dict[str, int] = {}
        self.last_prices: dict[str, dict[str, float]] = {m: {} for m in MARKETS}
        self.last_tick_ms: int | None = None
        self.last_error: str | None = None
        self._last_logged_error: dict[str, tuple[str | None, int]] = {}
        self.protection_status: dict[str, str | None] = {m: None for m in MARKETS}
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()
        self._shutdown = threading.Event()
        self._build_brokers()

    # --- estado e configuração ---
    @property
    def state(self) -> str:
        return self.store.get_json("engine_state", "stopped")

    def _set_state(self, state: str, message: str) -> None:
        if state not in STATES:
            raise ValueError(state)
        self.store.set_json("engine_state", state)
        self.store.log_event("state", message)

    def _build_brokers(self) -> None:
        self.brokers = {}
        for market, ms in self.settings.markets.items():
            broker = PaperBroker(market, self.store, self.data[market], ms.fee_rate,
                                 self.settings.risk.max_slippage_pct / 100)
            broker.ensure_wallet(ms.initial_balance)
            self.brokers[market] = broker

    def update_settings(self, settings: Settings) -> None:
        with self.lock:
            save_settings(self.store, settings)
            self.settings = settings
            self._build_brokers()
            self._universe.clear()
            self.store.log_event("settings", "Configurações atualizadas", data=settings.to_dict())

    @property
    def account(self) -> str:
        return self.settings.account

    def enabled_markets(self) -> list[str]:
        return [m for m in (SPOT, FUTURES) if self.settings.markets[m].enabled]

    # --- ciclo de vida da thread ---
    def start_loop(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._shutdown.clear()
        self._thread = threading.Thread(target=self._run, name="tradebot-engine", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._shutdown.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=30)

    def _run(self) -> None:
        while not self._shutdown.is_set():
            if self.state != "stopped":
                try:
                    self.tick()
                except Exception as exc:  # o loop nunca pode morrer — posições dependem dele
                    logger.exception("Erro no ciclo do motor")
                    self.last_error = str(exc)
                    self.store.log_event("error", f"Erro no ciclo: {exc}", level="error")
            self._wake.wait(self.settings.poll_seconds)
            self._wake.clear()

    # --- comandos do painel ---
    def start(self) -> None:
        with self.lock:
            self._last_bucket.clear()  # não entra no candle que já fechou antes de ligar
            self._set_state("running", "Bot ligado")
        self._wake.set()

    def pause_entries(self) -> None:
        with self.lock:
            self._set_state("paused", "Novas entradas pausadas (posições abertas continuam gerenciadas)")

    def stop(self) -> None:
        with self.lock:
            self._set_state("stopped", "Bot desligado")

    def emergency_close_all(self) -> int:
        """Botão de pânico: aciona o kill switch e fecha tudo a mercado."""
        with self.lock:
            risk.set_halt(self.data_dir, "Fechar tudo acionado no painel")
            self.store.log_event("halt", "PARAR TUDO: kill switch acionado, fechando todas as posições", level="warning")
            closed = 0
            for market in MARKETS:
                for p in self.store.open_positions(self.account, market):
                    if self._close(p, "emergency"):
                        closed += 1
            self._set_state("paused", "Bot em pausa após PARAR TUDO")
            return closed

    def release_halt(self) -> None:
        with self.lock:
            risk.clear_halt(self.data_dir)
            self.store.log_event("halt", "Kill switch liberado")

    def close_position(self, position_id: int) -> bool:
        with self.lock:
            p = self.store.get_position(position_id)
            if p is None or p.status != "open" or self.store.position_account(position_id) != self.account:
                return False
            return self._close(p, "manual")

    def reset_wallet(self, market: str) -> None:
        with self.lock:
            if self.store.open_positions(self.account, market):
                raise ValueError("Feche as posições abertas deste mercado antes de resetar a carteira")
            self.store.clear_account(self.account, market)
            self.store.reset_wallet(self.account, market, self.settings.markets[market].initial_balance)
            self.store.set_json(self._key(market, "peak"), None)
            self.store.set_json(self._key(market, "day_start"), None)
            self.store.log_event("wallet", f"Carteira demo de {market} resetada", market=market)

    def release_drawdown(self, market: str) -> None:
        """Libera a proteção de drawdown: o pico passa a ser o patrimônio atual."""
        with self.lock:
            self.store.set_json(self._key(market, "peak"), self.equity(market))
            self.store.log_event("protection", "Proteção de drawdown liberada manualmente", market=market)

    # --- leitura pro painel ---
    def equity(self, market: str) -> float:
        positions = self.store.open_positions(self.account, market)
        return self.brokers[market].equity(positions, self.last_prices.get(market, {}))

    # --- ciclo ---
    def tick(self, now: int | None = None) -> None:
        with self.lock:
            now = now or now_ms()
            for market in self.enabled_markets():
                try:
                    self._tick_market(market, now)
                except Exception as exc:
                    self._log_error(market, f"Erro no mercado {market}: {exc}", now)
            self.last_tick_ms = now

    def _tick_market(self, market: str, now: int) -> None:
        md = self.data[market]
        prices = md.last_prices()
        self.last_prices[market] = prices

        # 1) gerenciar posições abertas com o preço atual
        for p in self.store.open_positions(self.account, market):
            price = prices.get(p.symbol)
            if price is None:
                continue
            best_before, stop_before = p.best_price, p.stop_loss
            decision = evaluate_bar(p, price, price, price, price, now)
            if decision:
                self._close(p, decision.reason, now)
            elif (p.best_price, p.stop_loss) != (best_before, stop_before):
                if p.stop_loss != stop_before:
                    self.store.log_event("trailing", f"Trailing moveu o stop para {p.stop_loss:.6g}",
                                         market=market, symbol=p.symbol)
                self.store.update_position(p)

        self._update_equity_marks(market, now)

        # 2) candle fechado → saída por estratégia + busca de entradas
        strategy = get_strategy(self.settings.strategy)
        params = self.settings.params_for()
        tf_ms = TIMEFRAME_MINUTES[strategy.timeframe(params)] * 60_000
        bucket = (now - CANDLE_SETTLE_MS) // tf_ms
        last = self._last_bucket.get(market)
        self._last_bucket[market] = bucket
        if last is None or bucket <= last:
            return

        open_positions = self.store.open_positions(self.account, market)
        for p in open_positions:
            if p.strategy != strategy.name:
                continue
            candles = self._closed_candles(md, p.symbol, strategy.timeframe(params), strategy.warmup(params), now)
            if candles and strategy.should_exit(p, candles, params):
                self._close(p, "strategy_exit", now)

        self._scan(market, strategy, params, now)

    def _closed_candles(self, md, symbol: str, interval: str, count: int, now: int):
        candles = closed_only(md.klines(symbol, interval, limit=count + 2), now)
        return candles[-count:] if len(candles) >= count else []

    def _scan(self, market: str, strategy, params: dict, now: int) -> None:
        if self.state != "running":
            return
        if risk.is_halted(self.data_dir):
            self._set_protection(market, "Kill switch acionado — entradas bloqueadas")
            return
        recent_closed = self.store.closed_positions_market(self.account, market, now - 24 * 3600_000)
        equity = self.equity(market)
        reason = risk.active_protection(
            self.settings, recent_closed, equity,
            self.store.get_json(self._key(market, "peak")) or equity,
            (self.store.get_json(self._key(market, "day_start")) or {}).get("equity", equity), now,
        )
        self._set_protection(market, reason)
        if reason:
            return

        md = self.data[market]
        interval = strategy.timeframe(params)
        htf = strategy.higher_timeframe(params)
        for symbol in self._symbols(market, now):
            open_positions = self.store.open_positions(self.account, market)
            if any(p.symbol == symbol for p in open_positions):
                continue
            if risk.symbol_in_cooldown(self.settings, symbol, recent_closed, now):
                continue
            try:
                candles = self._closed_candles(md, symbol, interval, strategy.warmup(params), now)
                if not candles:
                    continue
                htf_candles = self._closed_candles(md, symbol, htf, 60, now) if htf else None
                signal = strategy.generate(symbol, candles, htf_candles, params)
                if signal:
                    self._try_open(market, signal, open_positions, now)
            except Exception as exc:
                self.store.log_event("error", f"Erro ao analisar {symbol}: {exc}", level="error",
                                     market=market, symbol=symbol)

    def _try_open(self, market: str, signal, open_positions: list[Position], now: int) -> None:
        self.store.log_event("signal", f"Sinal {signal.direction}: {signal.reason}", market=market,
                             symbol=signal.symbol, data={"entry": signal.entry, "stop": signal.exit_plan.stop_loss,
                                                         "target": signal.exit_plan.take_profit})
        trades_today = self.store.count_opened_since(self.account, market, risk.utc_day_start_ms(now))
        decision = risk.check_entry(signal, market, self.settings, open_positions, trades_today)
        if not decision.allowed:
            self.store.log_event("denied", f"Entrada negada: {decision.reason}", market=market, symbol=signal.symbol)
            return

        broker = self.brokers[market]
        rules = self.data[market].symbol_rules(signal.symbol)
        qty = rules.round_qty(risk.position_size(signal, self.equity(market), broker.cash(), self.settings))
        if qty < rules.min_qty or qty <= 0 or qty * signal.entry < rules.min_notional:
            self.store.log_event("denied", f"Entrada negada: tamanho {qty} abaixo do mínimo do par", market=market,
                                 symbol=signal.symbol)
            return
        try:
            fill = broker.open(signal.symbol, signal.direction, qty, self.last_prices[market].get(signal.symbol, signal.entry))
        except OrderRejected as exc:
            self.store.log_event("denied", f"Ordem recusada: {exc}", market=market, symbol=signal.symbol)
            return

        plan = reprice_exit_plan(signal, fill.price)
        position = Position(
            market=market, symbol=signal.symbol, direction=signal.direction, qty=fill.qty,
            entry_price=fill.price, stop_loss=plan.stop_loss, initial_stop=plan.stop_loss,
            take_profit=plan.take_profit, time_limit_minutes=plan.time_limit_minutes,
            trailing_activation=plan.trailing_activation, trailing_distance=plan.trailing_distance,
            opened_at_ms=now, strategy=signal.strategy, reason=signal.reason, entry_fee=fill.fee,
            best_price=fill.price,
        )
        self.store.insert_position(self.account, position)
        self.store.log_event("open", f"Abriu {signal.direction} {fill.qty:g} @ {fill.price:.6g} "
                             f"(stop {plan.stop_loss:.6g}, alvo {plan.take_profit if plan.take_profit else '—'})",
                             market=market, symbol=signal.symbol, data={"position_id": position.id})

    def _close(self, p: Position, reason: str, now: int | None = None) -> bool:
        try:
            fill = self.brokers[p.market].close(p)
        except Exception as exc:
            self.store.log_event("error", f"Falha ao fechar posição: {exc}", level="error", market=p.market, symbol=p.symbol)
            return False
        p.status = "closed"
        p.exit_price = fill.price
        p.exit_fee = fill.fee
        p.exit_reason = reason
        p.closed_at_ms = now or now_ms()
        self.store.update_position(p)
        pnl = p.net_pnl()
        self.store.log_event("close", f"Fechou ({EXIT_REASON_LABELS.get(reason, reason)}) @ {fill.price:.6g}: {pnl:+.2f} USDT ({p.r_multiple():+.2f}R)",
                             level="info" if pnl >= 0 else "warning", market=p.market, symbol=p.symbol,
                             data={"position_id": p.id, "pnl": pnl})
        return True

    def _log_error(self, market: str, message: str, now: int) -> None:
        """Sem internet o mesmo erro se repetiria a cada ciclo — registra 1x a cada 5 min."""
        self.last_error = message
        last_msg, last_at = self._last_logged_error.get(market, (None, 0))
        if message != last_msg or now - last_at > 5 * 60_000:
            self.store.log_event("error", message, level="error", market=market)
            self._last_logged_error[market] = (message, now)

    def _set_protection(self, market: str, reason: str | None) -> None:
        if reason and reason != self.protection_status.get(market):
            self.store.log_event("protection", reason, level="warning", market=market)
        self.protection_status[market] = reason

    def _symbols(self, market: str, now: int) -> list[str]:
        if self.settings.symbols:
            return self.settings.symbols
        cached = self._universe.get(market)
        if cached and now - cached[0] < UNIVERSE_REFRESH_MS:
            return cached[1]
        symbols = self.data[market].top_symbols(self.settings.top_symbols)
        self._universe[market] = (now, symbols)
        return symbols

    def _key(self, market: str, name: str) -> str:
        return f"{self.account}:{market}:{name}"

    def _update_equity_marks(self, market: str, now: int) -> None:
        equity = self.equity(market)
        peak_key = self._key(market, "peak")
        peak = self.store.get_json(peak_key)
        if peak is None or equity > peak:
            self.store.set_json(peak_key, equity)
        day_key = self._key(market, "day_start")
        day = risk.utc_day_start_ms(now)
        current = self.store.get_json(day_key)
        if not current or current.get("day") != day:
            self.store.set_json(day_key, {"day": day, "equity": equity})
        if now - self._last_equity_snapshot.get(market, 0) >= EQUITY_SNAPSHOT_MS:
            self.store.record_equity(self.account, market, equity, now)
            self._last_equity_snapshot[market] = now
