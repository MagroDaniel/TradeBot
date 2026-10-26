"""Painel web local (FastAPI + Jinja + htmx). Só escuta em 127.0.0.1.

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

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from tradebot import risk
from tradebot.engine import Engine
from tradebot.models import MARKETS
from tradebot.risk import utc_day_start_ms
from tradebot.settings import Settings
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
    templates.env.globals.update(MARKET_LABELS=MARKET_LABELS, STATE_LABELS=STATE_LABELS, EXIT_LABELS=EXIT_LABELS)
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

    # --- páginas ---
    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        return render(request, "dashboard.html", page="dashboard")

    @app.get("/partials/status", response_class=HTMLResponse)
    def status_partial(request: Request):
        return render(request, "partials/status.html", **_status(engine))

    @app.get("/partials/positions", response_class=HTMLResponse)
    def positions_partial(request: Request):
        return render(request, "partials/positions.html", positions=_open_positions(engine))

    @app.get("/partials/trades", response_class=HTMLResponse)
    def trades_partial(request: Request):
        trades = engine.store.closed_positions(engine.account, limit=50)
        return render(request, "partials/trades.html", trades=trades)

    @app.get("/partials/events", response_class=HTMLResponse)
    def events_partial(request: Request):
        return render(request, "partials/events.html", events=engine.store.recent_events(80))

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, saved: int = 0, error: str = ""):
        s = engine.settings
        return render(request, "settings.html", page="settings", s=s, strategies=STRATEGIES,
                      params={name: s.params_for(name) for name in STRATEGIES}, saved=saved, error=error)

    @app.post("/settings")
    async def save_settings(request: Request):
        form = await request.form()
        try:
            engine.update_settings(_settings_from_form(form, engine.settings))
        except (ValueError, TypeError) as exc:
            return RedirectResponse(f"/settings?{urlencode({'error': str(exc)})}", status_code=303)
        return RedirectResponse("/settings?saved=1", status_code=303)

    @app.get("/chart/{position_id}", response_class=HTMLResponse)
    def chart_page(request: Request, position_id: int):
        p = engine.store.get_position(position_id)
        if p is None or engine.store.position_account(position_id) != engine.account:
            raise HTTPException(404)
        return render(request, "chart.html", page="chart", p=p)

    # --- dados pros gráficos ---
    @app.get("/api/equity")
    def equity_data():
        series = {}
        for market in MARKETS:
            points = engine.store.equity_history(engine.account, market)
            series[market] = [{"time": t // 1000, "value": round(v, 2)} for t, v in points]
        return series

    @app.get("/api/candles/{position_id}")
    def candles_data(position_id: int):
        p = engine.store.get_position(position_id)
        if p is None:
            raise HTTPException(404)
        strategy = STRATEGIES.get(p.strategy)
        interval = strategy.timeframe(engine.settings.params_for(p.strategy)) if strategy else "15m"
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
    @app.post("/api/start")
    def start():
        engine.start()
        return refreshed("Bot ligado")

    @app.post("/api/pause")
    def pause():
        engine.pause_entries()
        return refreshed("Novas entradas pausadas")

    @app.post("/api/stop")
    def stop():
        engine.stop()
        return refreshed("Bot desligado")

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

    @app.post("/api/wallet/{market}/reset")
    def reset_wallet(market: str):
        if market not in MARKETS:
            raise HTTPException(404)
        try:
            engine.reset_wallet(market)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, 409, headers={"HX-Trigger": json.dumps({"toast": str(exc)})})
        return refreshed("Carteira demo resetada")

    @app.post("/api/protection/{market}/release")
    def release_drawdown(market: str):
        if market not in MARKETS:
            raise HTTPException(404)
        engine.release_drawdown(market)
        return refreshed("Proteção de drawdown liberada")

    return app


def _open_positions(engine: Engine) -> list[dict]:
    rows = []
    for market in MARKETS:
        prices = engine.last_prices.get(market, {})
        for p in engine.store.open_positions(engine.account, market):
            price = prices.get(p.symbol)
            pnl = p.gross_pnl(price) - p.entry_fee if price else None
            rows.append({"p": p, "price": price, "pnl": pnl,
                         "r": pnl / p.initial_risk if pnl is not None and p.initial_risk else None})
    return rows


def _status(engine: Engine) -> dict:
    now = now_ms()
    day = utc_day_start_ms(now)
    markets = []
    for market in MARKETS:
        ms = engine.settings.markets[market]
        wallet = engine.store.get_wallet(engine.account, market) or {"cash": 0, "initial": ms.initial_balance}
        equity = engine.equity(market) if market in engine.brokers else wallet["cash"]
        closed = engine.store.closed_positions_market(engine.account, market, 0)
        today = [p for p in closed if p.closed_at_ms >= day]
        wins = sum(1 for p in closed if p.net_pnl() > 0)
        markets.append({
            "market": market, "enabled": ms.enabled, "cash": wallet["cash"], "equity": equity,
            "initial": wallet["initial"], "return_pct": (equity / wallet["initial"] - 1) * 100 if wallet["initial"] else 0,
            "today_pnl": sum(p.net_pnl() for p in today), "trades": len(closed),
            "win_rate": wins / len(closed) * 100 if closed else None,
            "avg_r": sum(p.r_multiple() for p in closed) / len(closed) if closed else None,
            "protection": engine.protection_status.get(market),
            "open": len(engine.store.open_positions(engine.account, market)),
        })
    stale = engine.last_tick_ms is None or now - engine.last_tick_ms > max(60_000, engine.settings.poll_seconds * 4000)
    return {
        "state": engine.state, "halted": risk.is_halted(engine.data_dir), "markets": markets,
        "last_tick": engine.last_tick_ms, "stale": stale and engine.state != "stopped",
        "last_error": engine.last_error, "strategy": STRATEGIES[engine.settings.strategy].label,
        "account": engine.account,
        "has_open": any(m["open"] for m in markets),
    }


def _settings_from_form(form, current: Settings) -> Settings:
    data = current.to_dict()
    for market in MARKETS:
        data["markets"][market]["enabled"] = form.get(f"{market}_enabled") == "on"
        data["markets"][market]["initial_balance"] = form.get(f"{market}_initial_balance", 1000)
        data["markets"][market]["fee_rate"] = float(form.get(f"{market}_fee_pct", 0.1)) / 100
    data["top_symbols"] = form.get("top_symbols", 25)
    data["symbols"] = [s for s in str(form.get("symbols", "")).replace(",", " ").split() if s]
    data["poll_seconds"] = form.get("poll_seconds", 10)
    for key in data["risk"]:
        if key in form:
            data["risk"][key] = form[key]
    for key in data["protections"]:
        if key in form:
            data["protections"][key] = form[key]
    strategy = form.get("strategy", current.strategy)
    data["strategy"] = strategy
    if strategy in STRATEGIES:
        params = {}
        for key, spec in STRATEGIES[strategy].params.items():
            field = f"param_{strategy}_{key}"
            if spec.kind == "bool":
                params[key] = form.get(field) == "on"
            elif field in form:
                params[key] = form[field]
        STRATEGIES[strategy].resolve(params)  # valida antes de salvar
        data["strategy_params"][strategy] = params
    return Settings.from_dict(data)
