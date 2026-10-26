"""Motor de execução: vários robôs (`Bot`), cada um com estratégia, risco e carteira demo
próprios, rodando no mesmo ciclo (`tick`) a cada `poll_seconds`, numa thread só.

Por ciclo, o motor busca o preço de todos os pares UMA vez por mercado e entrega pra todos os
robôs; candles também são compartilhados dentro do ciclo (dois robôs olhando BTCUSDT 15m fazem
uma requisição só). Cada robô, por mercado habilitado nele:
1. Passa cada posição aberta por `position.evaluate_bar` — stop, alvo, trailing e
   tempo-limite. Sair vem SEMPRE antes de entrar (resolver antes de escanear).
2. Quando fecha um candle do timeframe da estratégia: pergunta à estratégia se alguma posição
   deve sair (`should_exit`) e, se entradas estiverem liberadas, escaneia os pares atrás de
   sinal novo. Cada sinal passa pelo portão de risco (`risk.py`) antes de virar ordem.

Estados por robô: `stopped` (posições ficam SEM gerenciamento — o painel avisa), `running` e
`paused` (só gerencia/fecha posições — o "parar novas entradas" do Freqtrade). Salvo no
banco e restaurado ao reabrir o app. O kill switch (`HALT`) e o PARAR TUDO valem pra todos.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from tradebot import risk
from tradebot.brokers import OrderRejected, PaperBroker
from tradebot.market_data import BinanceMarketData, closed_only
from tradebot.models import FUTURES, MARKETS, SPOT, Position, reprice_exit_plan
from tradebot.position import evaluate_bar
from tradebot.settings import MAX_BOTS, AppSettings, BotConfig
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


class Bot:
    """Estado em memória de um robô. A verdade persistente (config, estado, carteira,
    posições) fica no `Store`; isto aqui é cache por execução."""

    def __init__(self, bot_id: int, name: str, config: BotConfig, engine: "Engine") -> None:
        self.id = bot_id
        self.name = name
        self.config = config
        self.engine = engine
        self.brokers: dict[str, PaperBroker] = {}
        self.last_bucket: dict[str, int] = {}
        self.universe: dict[str, tuple[int, list[str]]] = {}
        self.last_equity_snapshot: dict[str, int] = {}
        self.protection_status: dict[str, str | None] = {m: None for m in MARKETS}
        self.build_brokers()

    def build_brokers(self) -> None:
        e = self.engine
        self.brokers = {}
        for market, ms in self.config.markets.items():
            broker = PaperBroker(market, e.store, e.data[market], ms.fee_rate,
                                 self.config.risk.max_slippage_pct / 100, bot_id=self.id)
            broker.ensure_wallet(ms.initial_balance)
            self.brokers[market] = broker

    @property
    def state(self) -> str:
        return self.engine.store.get_bot_state(self.id)

    def enabled_markets(self) -> list[str]:
        return [m for m in (SPOT, FUTURES) if self.config.markets[m].enabled]

    def equity(self, market: str) -> float:
        e = self.engine
        positions = e.store.open_positions(e.account, self.id, market)
        return self.brokers[market].equity(positions, e.last_prices.get(market, {}))

    def key(self, market: str, name: str) -> str:
        return f"{self.engine.account}:bot{self.id}:{market}:{name}"


class Engine:
    def __init__(self, store: Store, data_dir: Path, market_data: dict | None = None) -> None:
        self.store = store
        self.data_dir = Path(data_dir)
        self.data = market_data or {m: BinanceMarketData(m) for m in MARKETS}
        self.app_settings = AppSettings.from_dict(store.get_json("app_settings") or store.get_json("settings"))
        self.lock = threading.RLock()
        self.bots: dict[int, Bot] = {}
        self.last_prices: dict[str, dict[str, float]] = {m: {} for m in MARKETS}
        self.last_tick_ms: int | None = None
        self.last_error: str | None = None
        self._last_logged_error: dict[str, tuple[str | None, int]] = {}
        self._candle_cache: dict[tuple, list] = {}
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()
        self._shutdown = threading.Event()
        self._load_bots()

    @property
    def account(self) -> str:
        return self.app_settings.account

    def _load_bots(self) -> None:
        rows = self.store.list_bots()
        if not rows:
            # primeira execução (ou banco da versão 1, de robô único): cria o robô 1 com a
            # config antiga, se houver, e o estado antigo do motor
            legacy = self.store.get_json("settings")
            config = BotConfig.from_dict(legacy) if legacy else BotConfig()
            state = self.store.get_json("engine_state", "stopped")
            self.store.insert_bot(config.name, config.to_dict(), state)
            rows = self.store.list_bots()
        for row in rows:
            config = BotConfig.from_dict(row["config"])
            self.bots[row["id"]] = Bot(row["id"], row["name"], config, self)

    def get_bot(self, bot_id: int) -> Bot:
        try:
            return self.bots[bot_id]
        except KeyError:
            raise ValueError(f"Robô {bot_id} não existe") from None

    # --- gestão de robôs ---
    def create_bot(self, config: BotConfig) -> int:
        with self.lock:
            if len(self.bots) >= MAX_BOTS:
                raise ValueError(f"Máximo de {MAX_BOTS} robôs")
            config.validate()
            bot_id = self.store.insert_bot(config.name, config.to_dict())
            self.bots[bot_id] = Bot(bot_id, config.name, config, self)
            self.store.log_event("bot", f"Robô '{config.name}' criado ({config.strategy})", bot_id=bot_id)
            return bot_id

    def update_bot(self, bot_id: int, config: BotConfig) -> None:
        with self.lock:
            bot = self.get_bot(bot_id)
            config.validate()
            self.store.update_bot(bot_id, config.name, config.to_dict())
            strategy_changed = config.strategy != bot.config.strategy
            bot.name, bot.config = config.name, config
            bot.build_brokers()
            bot.universe.clear()
            if strategy_changed:
                bot.last_bucket.clear()
            self.store.log_event("settings", "Configurações do robô atualizadas", bot_id=bot_id, data=config.to_dict())

    def delete_bot(self, bot_id: int) -> None:
        with self.lock:
            self.get_bot(bot_id)
            if self.store.open_positions(self.account, bot_id):
                raise ValueError("Feche as posições abertas deste robô antes de apagá-lo")
            if len(self.bots) == 1:
                raise ValueError("Precisa existir pelo menos um robô")
            self.store.delete_bot(bot_id)
            del self.bots[bot_id]
            self.store.log_event("bot", f"Robô {bot_id} apagado")

    def update_app_settings(self, settings: AppSettings) -> None:
        with self.lock:
            self.store.set_json("app_settings", settings.to_dict())
            self.app_settings = settings
        self._wake.set()

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
            try:
                self.tick()
            except Exception as exc:  # o loop nunca pode morrer — posições dependem dele
                logger.exception("Erro no ciclo do motor")
                self.last_error = str(exc)
                self.store.log_event("error", f"Erro no ciclo: {exc}", level="error")
            self._wake.wait(self.app_settings.poll_seconds)
            self._wake.clear()

    # --- comandos do painel ---
    def _set_state(self, bot: Bot, state: str, message: str) -> None:
        if state not in STATES:
            raise ValueError(state)
        self.store.set_bot_state(bot.id, state)
        self.store.log_event("state", message, bot_id=bot.id)

    def start(self, bot_id: int) -> None:
        with self.lock:
            bot = self.get_bot(bot_id)
            bot.last_bucket.clear()  # não entra no candle que já fechou antes de ligar
            self._set_state(bot, "running", "Robô ligado")
        self._wake.set()

    def pause_entries(self, bot_id: int) -> None:
        with self.lock:
            self._set_state(self.get_bot(bot_id), "paused",
                            "Novas entradas pausadas (posições abertas continuam gerenciadas)")

    def stop(self, bot_id: int) -> None:
        with self.lock:
            self._set_state(self.get_bot(bot_id), "stopped", "Robô desligado")

    def emergency_close_all(self) -> int:
        """Botão de pânico: aciona o kill switch e fecha tudo, de todos os robôs, a mercado."""
        with self.lock:
            risk.set_halt(self.data_dir, "Fechar tudo acionado no painel")
            self.store.log_event("halt", "PARAR TUDO: kill switch acionado, fechando todas as posições", level="warning")
            closed = 0
            for bot in self.bots.values():
                for p in self.store.open_positions(self.account, bot.id):
                    if self._close(bot, p, "emergency"):
                        closed += 1
                if bot.state == "running":
                    self._set_state(bot, "paused", "Robô em pausa após PARAR TUDO")
            return closed

    def release_halt(self) -> None:
        with self.lock:
            risk.clear_halt(self.data_dir)
            self.store.log_event("halt", "Kill switch liberado")

    def close_position(self, position_id: int) -> bool:
        with self.lock:
            owner = self.store.position_owner(position_id)
            p = self.store.get_position(position_id)
            if p is None or p.status != "open" or owner is None or owner[0] != self.account or owner[1] not in self.bots:
                return False
            return self._close(self.bots[owner[1]], p, "manual")

    def reset_wallet(self, bot_id: int, market: str) -> None:
        with self.lock:
            bot = self.get_bot(bot_id)
            if self.store.open_positions(self.account, bot_id, market):
                raise ValueError("Feche as posições abertas deste mercado antes de resetar a carteira")
            self.store.clear_bot_market(self.account, bot_id, market)
            self.store.reset_wallet(self.account, bot_id, market, bot.config.markets[market].initial_balance)
            self.store.set_json(bot.key(market, "peak"), None)
            self.store.set_json(bot.key(market, "day_start"), None)
            self.store.log_event("wallet", f"Carteira demo de {market} resetada", bot_id=bot_id, market=market)

    def release_drawdown(self, bot_id: int, market: str) -> None:
        """Libera a proteção de drawdown: o pico passa a ser o patrimônio atual."""
        with self.lock:
            bot = self.get_bot(bot_id)
            self.store.set_json(bot.key(market, "peak"), bot.equity(market))
            self.store.log_event("protection", "Proteção de drawdown liberada manualmente", bot_id=bot_id, market=market)

    # --- ciclo ---
    def tick(self, now: int | None = None) -> None:
        with self.lock:
            now = now or now_ms()
            self._candle_cache = {}
            active = [b for b in self.bots.values() if b.state != "stopped"]
            markets = {m for b in active for m in b.enabled_markets()}
            for market in (SPOT, FUTURES):
                if market not in markets:
                    continue
                try:
                    self.last_prices[market] = self.data[market].last_prices()
                except Exception as exc:
                    self._log_error(market, f"Erro no mercado {market}: {exc}", now)
                    continue
                for bot in active:
                    if market not in bot.enabled_markets():
                        continue
                    try:
                        self._tick_bot_market(bot, market, now)
                    except Exception as exc:
                        self._log_error(f"{bot.id}:{market}", f"Erro no robô '{bot.name}' ({market}): {exc}", now, bot.id)
            self.last_tick_ms = now

    def _tick_bot_market(self, bot: Bot, market: str, now: int) -> None:
        prices = self.last_prices[market]

        # 1) gerenciar posições abertas com o preço atual
        for p in self.store.open_positions(self.account, bot.id, market):
            price = prices.get(p.symbol)
            if price is None:
                continue
            best_before, stop_before = p.best_price, p.stop_loss
            decision = evaluate_bar(p, price, price, price, price, now)
            if decision:
                self._close(bot, p, decision.reason, now)
            elif (p.best_price, p.stop_loss) != (best_before, stop_before):
                if p.stop_loss != stop_before:
                    self.store.log_event("trailing", f"Trailing moveu o stop para {p.stop_loss:.6g}",
                                         bot_id=bot.id, market=market, symbol=p.symbol)
                self.store.update_position(p)

        self._update_equity_marks(bot, market, now)

        # 2) candle fechado → saída por estratégia + busca de entradas
        strategy = get_strategy(bot.config.strategy)
        params = bot.config.params()
        tf_ms = TIMEFRAME_MINUTES[strategy.timeframe(params)] * 60_000
        bucket = (now - CANDLE_SETTLE_MS) // tf_ms
        last = bot.last_bucket.get(market)
        bot.last_bucket[market] = bucket
        if last is None or bucket <= last:
            return

        for p in self.store.open_positions(self.account, bot.id, market):
            if p.strategy != strategy.name:
                continue
            candles = self._closed_candles(market, p.symbol, strategy.timeframe(params), strategy.warmup(params), now)
            if candles and strategy.should_exit(p, candles, params):
                self._close(bot, p, "strategy_exit", now)

        self._scan(bot, market, strategy, params, now)

    def _closed_candles(self, market: str, symbol: str, interval: str, count: int, now: int):
        key = (market, symbol, interval)
        if key not in self._candle_cache:
            # pede folga pro maior warmup entre os robôs (o cache é compartilhado no ciclo);
            # 1000 é o máximo por chamada da Binance
            raw = self.data[market].klines(symbol, interval, limit=min(1000, max(count + 2, 502)))
            self._candle_cache[key] = closed_only(raw, now)
        candles = self._candle_cache[key]
        return candles[-count:] if len(candles) >= count else []

    def _scan(self, bot: Bot, market: str, strategy, params: dict, now: int) -> None:
        if bot.state != "running":
            return
        if risk.is_halted(self.data_dir):
            self._set_protection(bot, market, "Kill switch acionado — entradas bloqueadas")
            return
        cfg = bot.config
        recent_closed = self.store.closed_positions(self.account, bot.id, market, since_ms=now - 24 * 3600_000)
        equity = bot.equity(market)
        reason = risk.active_protection(
            cfg, recent_closed, equity,
            self.store.get_json(bot.key(market, "peak")) or equity,
            (self.store.get_json(bot.key(market, "day_start")) or {}).get("equity", equity), now,
        )
        self._set_protection(bot, market, reason)
        if reason:
            return

        interval = strategy.timeframe(params)
        htf = strategy.higher_timeframe(params)
        for symbol in self._symbols(bot, market, now):
            open_positions = self.store.open_positions(self.account, bot.id, market)
            if any(p.symbol == symbol for p in open_positions):
                continue
            if risk.symbol_in_cooldown(cfg, symbol, recent_closed, now):
                continue
            try:
                candles = self._closed_candles(market, symbol, interval, strategy.warmup(params), now)
                if not candles:
                    continue
                htf_candles = self._closed_candles(market, symbol, htf, 60, now) if htf else None
                signal = strategy.generate(symbol, candles, htf_candles, params)
                if signal:
                    self._try_open(bot, market, signal, open_positions, now)
            except Exception as exc:
                self.store.log_event("error", f"Erro ao analisar {symbol}: {exc}", level="error",
                                     bot_id=bot.id, market=market, symbol=symbol)

    def _try_open(self, bot: Bot, market: str, signal, open_positions: list[Position], now: int) -> None:
        log = self.store.log_event
        log("signal", f"Sinal {signal.direction}: {signal.reason}", bot_id=bot.id, market=market, symbol=signal.symbol,
            data={"entry": signal.entry, "stop": signal.exit_plan.stop_loss, "target": signal.exit_plan.take_profit})
        trades_today = self.store.count_opened_since(self.account, bot.id, market, risk.utc_day_start_ms(now))
        decision = risk.check_entry(signal, market, bot.config, open_positions, trades_today)
        if not decision.allowed:
            log("denied", f"Entrada negada: {decision.reason}", bot_id=bot.id, market=market, symbol=signal.symbol)
            return

        broker = bot.brokers[market]
        rules = self.data[market].symbol_rules(signal.symbol)
        qty = rules.round_qty(risk.position_size(signal, bot.equity(market), broker.cash(), bot.config))
        if qty < rules.min_qty or qty <= 0 or qty * signal.entry < rules.min_notional:
            log("denied", f"Entrada negada: tamanho {qty} abaixo do mínimo do par", bot_id=bot.id, market=market,
                symbol=signal.symbol)
            return
        try:
            fill = broker.open(signal.symbol, signal.direction, qty, self.last_prices[market].get(signal.symbol, signal.entry))
        except OrderRejected as exc:
            log("denied", f"Ordem recusada: {exc}", bot_id=bot.id, market=market, symbol=signal.symbol)
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
        self.store.insert_position(self.account, bot.id, position)
        log("open", f"Abriu {signal.direction} {fill.qty:g} @ {fill.price:.6g} "
            f"(stop {plan.stop_loss:.6g}, alvo {plan.take_profit if plan.take_profit else '—'})",
            bot_id=bot.id, market=market, symbol=signal.symbol, data={"position_id": position.id})

    def _close(self, bot: Bot, p: Position, reason: str, now: int | None = None) -> bool:
        try:
            fill = bot.brokers[p.market].close(p)
        except Exception as exc:
            self.store.log_event("error", f"Falha ao fechar posição: {exc}", level="error", bot_id=bot.id,
                                 market=p.market, symbol=p.symbol)
            return False
        p.status = "closed"
        p.exit_price = fill.price
        p.exit_fee = fill.fee
        p.exit_reason = reason
        p.closed_at_ms = now or now_ms()
        self.store.update_position(p)
        pnl = p.net_pnl()
        self.store.log_event(
            "close", f"Fechou ({EXIT_REASON_LABELS.get(reason, reason)}) @ {fill.price:.6g}: {pnl:+.2f} USDT "
            f"({p.r_multiple():+.2f}R)", level="info" if pnl >= 0 else "warning", bot_id=bot.id, market=p.market,
            symbol=p.symbol, data={"position_id": p.id, "pnl": pnl})
        return True

    def _log_error(self, key: str, message: str, now: int, bot_id: int | None = None) -> None:
        """Sem internet o mesmo erro se repetiria a cada ciclo — registra 1x a cada 5 min."""
        self.last_error = message
        last_msg, last_at = self._last_logged_error.get(key, (None, 0))
        if message != last_msg or now - last_at > 5 * 60_000:
            self.store.log_event("error", message, level="error", bot_id=bot_id)
            self._last_logged_error[key] = (message, now)

    def _set_protection(self, bot: Bot, market: str, reason: str | None) -> None:
        if reason and reason != bot.protection_status.get(market):
            self.store.log_event("protection", reason, level="warning", bot_id=bot.id, market=market)
        bot.protection_status[market] = reason

    def _symbols(self, bot: Bot, market: str, now: int) -> list[str]:
        if bot.config.symbols:
            return bot.config.symbols
        cached = bot.universe.get(market)
        if cached and now - cached[0] < UNIVERSE_REFRESH_MS:
            return cached[1]
        symbols = self.data[market].top_symbols(bot.config.top_symbols)
        bot.universe[market] = (now, symbols)
        return symbols

    def _update_equity_marks(self, bot: Bot, market: str, now: int) -> None:
        equity = bot.equity(market)
        peak_key = bot.key(market, "peak")
        peak = self.store.get_json(peak_key)
        if peak is None or equity > peak:
            self.store.set_json(peak_key, equity)
        day_key = bot.key(market, "day_start")
        day = risk.utc_day_start_ms(now)
        current = self.store.get_json(day_key)
        if not current or current.get("day") != day:
            self.store.set_json(day_key, {"day": day, "equity": equity})
        # instante alinhado entre robôs/mercados → a soma por robô no gráfico casa os pontos
        slot = now - now % EQUITY_SNAPSHOT_MS
        if bot.last_equity_snapshot.get(market) != slot:
            self.store.record_equity(self.account, bot.id, market, equity, slot)
            bot.last_equity_snapshot[market] = slot
