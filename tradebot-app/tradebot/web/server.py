"""Painel web local (FastAPI + Jinja + htmx). Só escuta em 127.0.0.1.

Abas: "Visão geral" compara todos os robôs (patrimônio, retorno, acerto, R médio e curva de
retorno lado a lado); cada robô tem a sua aba com status, posições, histórico, log e
configurações próprias.

Segurança (ideias do shell desktop do Vibe-Trading): o launcher gera um token aleatório por
execução e abre o navegador com `?token=...`; o servidor troca isso por um cookie HttpOnly
SameSite=Strict e recusa qualquer requisição sem ele. Outro site aberto no navegador não
consegue mandar comandos pro bot (o cookie Strict não vai em requisição de outra origem), e
outro usuário/programa da máquina não opera sem o token.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from tradebot import risk
from tradebot.engine import Bot, Engine
from tradebot.models import MARKETS
from tradebot.risk import utc_day_start_ms
from tradebot.settings import AppSettings, BotConfig
from tradebot.store import now_ms
from tradebot.strategies import STRATEGIES

HERE = Path(__file__).parent
COOKIE = "tradebot_token"

MARKET_LABELS = {"spot": "Spot", "futures": "Futuros"}
STATE_LABELS = {"running": "Ligado", "paused": "Só gerenciando posições", "stopped": "Desligado"}
EXIT_LABELS = {
    "stop_loss": "Stop", "trailing_stop": "Trailing", "take_profit": "Alvo", "time_limit": "Tempo",
    "strategy_exit": "Estratégia", "manual": "Manual", "emergency": "Emergência",
}
# Estratégias aprovadas na pesquisa (R líquido > 0 em todas as fatias, p < 0,10). Vazio desde a
# pesquisa de 2026-10-26 (12 meses, custos reais): nenhuma passou, nem a ema_cross — ver PLANO.md.
VALIDATED_STRATEGIES: set[str] = set()


def _fmt_time(ms: int | None) -> str:
    if not ms:
        return "—"
    # horário de Brasília (UTC-3 fixo, mesma convenção do resto do repositório)
    return datetime.fromtimestamp(ms / 1000 - 3 * 3600, tz=timezone.utc).strftime("%d/%m %H:%M:%S")


def _fmt_price(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f}" if value >= 100 else f"{value:.6g}"


def create_app(engine: Engine, token: str | None = None) -> FastAPI:
    token = token or secrets.token_urlsafe(32)
    app = FastAPI(title="TradeBot", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine = engine
    app.state.token = token
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters.update(time=_fmt_time, price=_fmt_price)
    templates.env.globals.update(
        MARKET_LABELS=MARKET_LABELS, STATE_LABELS=STATE_LABELS, EXIT_LABELS=EXIT_LABELS, STRATEGIES=STRATEGIES,
        VALIDATED=VALIDATED_STRATEGIES,
        nav_bots=lambda: [{"id": b.id, "name": b.name, "state": b.state} for b in engine.bots.values()],
    )
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    @app.middleware("http")
    async def auth(request: Request, call_next):
        if request.url.path in ("/health",) or request.url.path.startswith("/static/"):
            return await call_next(request)
        given = request.query_params.get("token")
        if given and secrets.compare_digest(given, token):
            response = RedirectResponse(request.url.path or "/", status_code=303)
            response.set_cookie(COOKIE, token, httponly=True, samesite="strict")
            return response
        cookie = request.cookies.get(COOKIE, "")
        if not (cookie and secrets.compare_digest(cookie, token)):
            return HTMLResponse("<h3>Acesso negado.</h3><p>Abra o painel pelo atalho do TradeBot.</p>", 401)
        return await call_next(request)

    def render(request: Request, name: str, **ctx):
        return templates.TemplateResponse(request, name, ctx)

    def refreshed(message: str = "") -> Response:
        response = Response(status_code=204)
        response.headers["HX-Trigger"] = json.dumps({"refresh": True, "toast": message} if message else {"refresh": True})
        return response

    def bot_or_404(bot_id: int) -> Bot:
        bot = engine.bots.get(bot_id)
        if bot is None:
            raise HTTPException(404, "Robô não encontrado")
        return bot

    # --- visão geral ---
    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request):
        return render(request, "overview.html", page="overview")

    @app.get("/partials/overview", response_class=HTMLResponse)
    def overview_partial(request: Request):
        rows = [_bot_summary(engine, b) for b in engine.bots.values()]
        return render(request, "partials/overview.html", rows=rows, **_global_status(engine))

    @app.get("/api/equity/overview")
    def equity_overview():
        out = []
        for bot in engine.bots.values():
            initial = sum((engine.store.get_wallet(engine.account, bot.id, m) or {}).get("initial", 0)
                          for m in bot.enabled_markets())
            points = engine.store.equity_history(engine.account, bot.id)
            if initial:
                out.append({"id": bot.id, "name": bot.name,
                            "points": [{"time": t // 1000, "value": round((v / initial - 1) * 100, 3)} for t, v in points]})
        return out

    @app.get("/settings", response_class=HTMLResponse)
    def app_settings_page(request: Request, saved: int = 0, error: str = ""):
        return render(request, "app_settings.html", page="app_settings", s=engine.app_settings, saved=saved, error=error)

    @app.post("/settings")
    async def save_app_settings(request: Request):
        form = await request.form()
        try:
            engine.update_app_settings(AppSettings.from_dict({**engine.app_settings.to_dict(),
                                                              "poll_seconds": form.get("poll_seconds", 10)}))
        except (ValueError, TypeError) as exc:
            return RedirectResponse(f"/settings?{urlencode({'error': str(exc)})}", status_code=303)
        return RedirectResponse("/settings?saved=1", status_code=303)

    # --- criar / apagar robô ---
    @app.get("/bots/new", response_class=HTMLResponse)
    def new_bot_page(request: Request, error: str = ""):
        return render(request, "new_bot.html", page="new", error=error)

    @app.post("/bots")
    async def create_bot(request: Request):
        form = await request.form()
        try:
            source = form.get("copy_from", "")
            base = engine.get_bot(int(source)).config.to_dict() if source else BotConfig().to_dict()
            strategy = form.get("strategy", "")
            if strategy != base["strategy"]:
                base["strategy_params"] = {}  # parâmetros de outra estratégia não servem
            base.update(name=form.get("name", "").strip() or STRATEGIES[strategy].label, strategy=strategy)
            bot_id = engine.create_bot(BotConfig.from_dict(base))
        except (ValueError, KeyError, TypeError) as exc:
            return RedirectResponse(f"/bots/new?{urlencode({'error': str(exc)})}", status_code=303)
        return RedirectResponse(f"/bots/{bot_id}/settings?created=1", status_code=303)

    @app.post("/bots/{bot_id}/delete")
    def delete_bot(bot_id: int):
        bot_or_404(bot_id)
        try:
            engine.delete_bot(bot_id)
        except ValueError as exc:
            return RedirectResponse(f"/bots/{bot_id}/settings?{urlencode({'error': str(exc)})}", status_code=303)
        return RedirectResponse("/", status_code=303)

    # --- aba de um robô ---
    @app.get("/bots/{bot_id}", response_class=HTMLResponse)
    def bot_page(request: Request, bot_id: int):
        return render(request, "bot.html", page=f"bot{bot_id}", bot=bot_or_404(bot_id))

    @app.get("/bots/{bot_id}/partials/status", response_class=HTMLResponse)
    def bot_status_partial(request: Request, bot_id: int):
        bot = bot_or_404(bot_id)
        return render(request, "partials/status.html", bot=bot, **_bot_status(engine, bot), **_global_status(engine))

    @app.get("/bots/{bot_id}/partials/positions", response_class=HTMLResponse)
    def positions_partial(request: Request, bot_id: int):
        return render(request, "partials/positions.html", positions=_open_positions(engine, bot_or_404(bot_id)))

    @app.get("/bots/{bot_id}/partials/trades", response_class=HTMLResponse)
    def trades_partial(request: Request, bot_id: int):
        bot = bot_or_404(bot_id)
        return render(request, "partials/trades.html", trades=engine.store.closed_positions(engine.account, bot.id, limit=50))

    @app.get("/bots/{bot_id}/partials/events", response_class=HTMLResponse)
    def events_partial(request: Request, bot_id: int):
        bot = bot_or_404(bot_id)
        return render(request, "partials/events.html", events=engine.store.recent_events(80, bot_id=bot.id))

    @app.get("/api/bots/{bot_id}/equity")
    def bot_equity(bot_id: int):
        bot = bot_or_404(bot_id)
        return {m: [{"time": t // 1000, "value": round(v, 2)} for t, v in engine.store.equity_history(engine.account, bot.id, m)]
                for m in MARKETS}

    @app.get("/bots/{bot_id}/settings", response_class=HTMLResponse)
    def bot_settings_page(request: Request, bot_id: int, saved: int = 0, created: int = 0, error: str = ""):
        bot = bot_or_404(bot_id)
        return render(request, "settings.html", page=f"bot{bot_id}", bot=bot, s=bot.config, params=bot.config.params(),
                      strategy=STRATEGIES[bot.config.strategy], saved=saved, created=created, error=error)

    @app.post("/bots/{bot_id}/settings")
    async def save_bot_settings(request: Request, bot_id: int):
        bot = bot_or_404(bot_id)
        form = await request.form()
        try:
            engine.update_bot(bot.id, _config_from_form(form, bot.config))
        except (ValueError, TypeError) as exc:
            return RedirectResponse(f"/bots/{bot_id}/settings?{urlencode({'error': str(exc)})}", status_code=303)
        return RedirectResponse(f"/bots/{bot_id}/settings?saved=1", status_code=303)

    # --- gráfico de uma posição ---
    @app.get("/chart/{position_id}", response_class=HTMLResponse)
    def chart_page(request: Request, position_id: int):
        p = engine.store.get_position(position_id)
        owner = engine.store.position_owner(position_id)
        if p is None or owner is None or owner[0] != engine.account:
            raise HTTPException(404)
        return render(request, "chart.html", page=f"bot{owner[1]}", p=p, bot_id=owner[1])

    @app.get("/api/candles/{position_id}")
    def candles_data(position_id: int):
        p = engine.store.get_position(position_id)
        owner = engine.store.position_owner(position_id)
        if p is None or owner is None:
            raise HTTPException(404)
        strategy = STRATEGIES.get(p.strategy)
        bot = engine.bots.get(owner[1])
        params = bot.config.params() if bot and bot.config.strategy == p.strategy else (strategy.resolve(None) if strategy else {})
        interval = strategy.timeframe(params) if strategy else "15m"
        candles = engine.data[p.market].klines(p.symbol, interval, limit=300)
        return {
            "interval": interval,
            "candles": [{"time": c.open_time_ms // 1000, "open": c.open, "high": c.high, "low": c.low,
                         "close": c.close} for c in candles],
            "entry": p.entry_price, "stop": p.stop_loss, "initial_stop": p.initial_stop,
            "target": p.take_profit, "exit": p.exit_price, "direction": p.direction,
            "opened": p.opened_at_ms // 1000, "closed": (p.closed_at_ms or 0) // 1000,
        }

    # --- comandos ---
    @app.post("/api/bots/{bot_id}/start")
    def start(bot_id: int):
        engine.start(bot_or_404(bot_id).id)
        return refreshed("Robô ligado")

    @app.post("/api/bots/{bot_id}/pause")
    def pause(bot_id: int):
        engine.pause_entries(bot_or_404(bot_id).id)
        return refreshed("Novas entradas pausadas")

    @app.post("/api/bots/{bot_id}/stop")
    def stop(bot_id: int):
        engine.stop(bot_or_404(bot_id).id)
        return refreshed("Robô desligado")

    @app.post("/api/emergency")
    def emergency():
        n = engine.emergency_close_all()
        return refreshed(f"PARAR TUDO: {n} posições fechadas")

    @app.post("/api/release-halt")
    def release_halt():
        engine.release_halt()
        return refreshed("Kill switch liberado")

    @app.post("/api/positions/{position_id}/close")
    def close_position(position_id: int):
        if not engine.close_position(position_id):
            raise HTTPException(409, "Posição já fechada ou inexistente")
        return refreshed("Posição fechada")

    @app.post("/api/bots/{bot_id}/wallet/{market}/reset")
    def reset_wallet(bot_id: int, market: str):
        bot = bot_or_404(bot_id)
        if market not in MARKETS:
            raise HTTPException(404)
        try:
            engine.reset_wallet(bot.id, market)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, 409, headers={"HX-Trigger": json.dumps({"toast": str(exc)})})
        return refreshed("Carteira demo resetada")

    @app.post("/api/bots/{bot_id}/protection/{market}/release")
    def release_drawdown(bot_id: int, market: str):
        bot = bot_or_404(bot_id)
        if market not in MARKETS:
            raise HTTPException(404)
        engine.release_drawdown(bot.id, market)
        return refreshed("Proteção de drawdown liberada")

    return app


def _open_positions(engine: Engine, bot: Bot) -> list[dict]:
    rows = []
    for p in engine.store.open_positions(engine.account, bot.id):
        price = engine.last_prices.get(p.market, {}).get(p.symbol)
        pnl = p.gross_pnl(price) - p.entry_fee if price else None
        rows.append({"p": p, "price": price, "pnl": pnl,
                     "r": pnl / p.initial_risk if pnl is not None and p.initial_risk else None})
    return rows


def _bot_status(engine: Engine, bot: Bot) -> dict:
    day = utc_day_start_ms(now_ms())
    markets = []
    for market in MARKETS:
        ms = bot.config.markets[market]
        wallet = engine.store.get_wallet(engine.account, bot.id, market) or {"cash": 0, "initial": ms.initial_balance}
        equity = bot.equity(market)
        closed = engine.store.closed_positions(engine.account, bot.id, market)
        today = [p for p in closed if p.closed_at_ms >= day]
        wins = sum(1 for p in closed if p.net_pnl() > 0)
        markets.append({
            "market": market, "enabled": ms.enabled, "cash": wallet["cash"], "equity": equity,
            "initial": wallet["initial"], "return_pct": (equity / wallet["initial"] - 1) * 100 if wallet["initial"] else 0,
            "today_pnl": sum(p.net_pnl() for p in today), "trades": len(closed),
            "win_rate": wins / len(closed) * 100 if closed else None,
            "avg_r": sum(p.r_multiple() for p in closed) / len(closed) if closed else None,
            "protection": bot.protection_status.get(market),
            "open": len(engine.store.open_positions(engine.account, bot.id, market)),
        })
    return {"state": bot.state, "markets": markets, "has_open": any(m["open"] for m in markets),
            "strategy_label": STRATEGIES[bot.config.strategy].label}


def _bot_summary(engine: Engine, bot: Bot) -> dict:
    """Uma linha da comparação: soma dos mercados habilitados do robô."""
    status = _bot_status(engine, bot)
    enabled = [m for m in status["markets"] if m["enabled"]]
    closed = engine.store.closed_positions(engine.account, bot.id)
    equity = sum(m["equity"] for m in enabled)
    initial = sum(m["initial"] for m in enabled)
    wins = sum(1 for p in closed if p.net_pnl() > 0)
    return {
        "bot": bot, "state": status["state"], "strategy": bot.config.strategy,
        "markets": ", ".join(MARKET_LABELS[m["market"]] for m in enabled),
        "equity": equity, "return_pct": (equity / initial - 1) * 100 if initial else 0.0,
        "trades": len(closed), "win_rate": wins / len(closed) * 100 if closed else None,
        "avg_r": sum(p.r_multiple() for p in closed) / len(closed) if closed else None,
        "pnl": sum(p.net_pnl() for p in closed),
        "open": sum(m["open"] for m in enabled),
        "protection": next((m["protection"] for m in enabled if m["protection"]), None),
    }


def _global_status(engine: Engine) -> dict:
    now = now_ms()
    any_active = any(b.state != "stopped" for b in engine.bots.values())
    stale = engine.last_tick_ms is None or now - engine.last_tick_ms > max(60_000, engine.app_settings.poll_seconds * 4000)
    return {"halted": risk.is_halted(engine.data_dir), "stale": stale and any_active,
            "last_error": engine.last_error, "last_tick": engine.last_tick_ms, "account": engine.account}


def _config_from_form(form, current: BotConfig) -> BotConfig:
    data = current.to_dict()
    data["name"] = form.get("name", current.name)
    for market in MARKETS:
        data["markets"][market]["enabled"] = form.get(f"{market}_enabled") == "on"
        data["markets"][market]["initial_balance"] = form.get(f"{market}_initial_balance", 1000)
        data["markets"][market]["fee_rate"] = float(form.get(f"{market}_fee_pct", 0.1)) / 100
    data["top_symbols"] = form.get("top_symbols", 25)
    data["symbols"] = [s for s in str(form.get("symbols", "")).replace(",", " ").split() if s]
    for key in data["risk"]:
        if key in form:
            data["risk"][key] = form[key]
    for key in data["protections"]:
        if key in form:
            data["protections"][key] = form[key]
    strategy = STRATEGIES[current.strategy]
    params = {}
    for key, spec in strategy.params.items():
        field = f"param_{key}"
        if spec.kind == "bool":
            params[key] = form.get(field) == "on"
        elif field in form:
            params[key] = form[field]
    strategy.resolve(params)  # valida antes de salvar
    data["strategy_params"] = params
    return BotConfig.from_dict(data)
