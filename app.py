"""Abre o TradeBot: sobe o motor + painel em 127.0.0.1, abre o navegador e (no Windows) põe um
ícone na bandeja, perto do relógio.

    python app.py              # uso normal
    python app.py --no-browser # não abre o navegador (o link com o token vai pro log/terminal)
    python app.py --no-tray    # sem ícone na bandeja (Ctrl+C no terminal encerra)
    TradeBot.exe --self-test   # sobe, confere o painel e sai (usado no build da release)

Uma instância por vez: se já houver uma rodando, só abre o navegador nela e sai — duas
instâncias operando as mesmas carteiras seriam duas ordens pro mesmo sinal.

Fechar a aba do navegador NÃO para o bot (de propósito: posições abertas continuam com stop
e alvo monitorados). Pra encerrar: "Sair" no ícone da bandeja (ou Ctrl+C no terminal). O
estado de cada robô é salvo e restaurado na próxima abertura.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import socket
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

import requests
import uvicorn

from tradebot import __version__
from tradebot.engine import Engine
from tradebot.paths import data_dir
from tradebot.store import Store
from tradebot.updater import UpdateManager, is_frozen
from tradebot.web.server import create_app

INSTANCE_FILE = "instance.json"
NO_PROXY = {"http": None, "https": None}
logger = logging.getLogger("tradebot")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _existing_instance(path: Path) -> dict | None:
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        r = requests.get(f"http://127.0.0.1:{info['port']}/health", timeout=2, proxies=NO_PROXY)
        return info if r.ok else None
    except Exception:
        return None


def _wait_healthy(port: int, seconds: float = 20) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if requests.get(f"http://127.0.0.1:{port}/health", timeout=1, proxies=NO_PROXY).ok:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _setup_logging(folder: Path) -> None:
    handlers: list[logging.Handler] = [logging.FileHandler(folder / "tradebot.log", encoding="utf-8")]
    if sys.stdout is not None:  # o .exe sem console não tem stdout
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers, force=True)


def _assets_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / "assets"


def _run_tray(url: str, quit_app, holder: dict) -> bool:
    """Ícone na bandeja (bloqueia até "Sair"). False se não der pra criar (sem interface
    gráfica, pystray ausente) — aí o app segue no modo terminal."""
    try:
        import pystray
        from PIL import Image
    except Exception as exc:  # pystray importa um backend gráfico na hora; no Linux sem tela falha
        logger.info("Sem ícone na bandeja (%s); use Ctrl+C para encerrar", exc)
        return False

    def on_quit(icon, _item):
        icon.stop()
        quit_app()

    image = Image.open(_assets_dir() / "icon.png")
    menu = pystray.Menu(
        pystray.MenuItem("Abrir painel", lambda icon, item: webbrowser.open(url), default=True),
        pystray.MenuItem(f"TradeBot v{__version__}", None, enabled=False),
        pystray.MenuItem("Sair (encerra os robôs)", on_quit),
    )
    icon = pystray.Icon("TradeBot", image, f"TradeBot v{__version__}", menu)
    holder["icon"] = icon  # o atualizador precisa fechar o ícone pra o processo terminar
    icon.run()
    return True


def self_test() -> int:
    """Sobe o app numa pasta temporária, confere /health e a página principal (templates e
    arquivos estáticos dentro do .exe) e sai. Sem rede externa: o motor fica desligado.

    Nunca deixa exceção escapar: no .exe sem console, uma exceção não tratada abre uma janela
    de erro esperando clique — no build da release isso travaria o workflow."""
    try:
        ok, detail = _self_test()
    except BaseException as exc:  # noqa: BLE001
        ok, detail = False, repr(exc)
    message = f"self-test {'OK' if ok else 'FALHOU'} (v{__version__}){': ' + detail if detail else ''}"
    if sys.stdout is not None:  # o .exe sem console não tem stdout
        print(message)
    log = os.getenv("TRADEBOT_SELFTEST_LOG")  # o workflow da release lê daqui
    if log:
        Path(log).write_text(message, encoding="utf-8")
    return 0 if ok else 1


def _self_test() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        folder = Path(tmp)
        store = Store(folder / "t.db")
        engine = Engine(store, folder)
        token = secrets.token_urlsafe(16)
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(create_app(engine, token), host="127.0.0.1", port=port,
                                               log_config=None, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        ok, detail = _wait_healthy(port), ""
        if not ok:
            detail = "o servidor não respondeu em /health"
        else:
            s = requests.Session()
            s.trust_env = False
            page = s.get(f"http://127.0.0.1:{port}/?token={token}", timeout=10)
            css = s.get(f"http://127.0.0.1:{port}/static/vendor/htmx-1.9.12.min.js", timeout=10)
            ok = page.ok and "TradeBot" in page.text and css.ok
            if not ok:
                detail = f"painel HTTP {page.status_code}, js HTTP {css.status_code}"
        server.should_exit = True
        thread.join(timeout=10)
        store.close()  # no Windows, arquivo aberto impede apagar a pasta temporária
        return ok, detail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-tray", action="store_true")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--after-update", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    folder = data_dir()
    _setup_logging(folder)
    instance_path = folder / INSTANCE_FILE
    existing = _existing_instance(instance_path)
    if existing:
        url = f"http://127.0.0.1:{existing['port']}/?token={existing['token']}"
        logger.info("O TradeBot já está aberto: %s", url)
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    port = args.port or _free_port()
    token = secrets.token_urlsafe(32)
    instance_path.write_text(json.dumps({"port": port, "token": token, "pid": os.getpid()}), encoding="utf-8")
    url = f"http://127.0.0.1:{port}/?token={token}"

    engine = Engine(Store(folder / "tradebot.db"), folder)
    engine.start_loop()
    stopping = threading.Event()
    server: uvicorn.Server | None = None
    tray: dict = {}

    def quit_app():
        if stopping.is_set():
            return
        stopping.set()
        logger.info("Encerrando o TradeBot")
        if server:
            server.should_exit = True
        if tray.get("icon"):
            tray["icon"].stop()

    updater = UpdateManager(folder, shutdown=quit_app)
    app = create_app(engine, token, updater)
    # sem console (.exe), o formatador colorido padrão do uvicorn quebra: usa o logging do app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                           log_config=None if sys.stdout is None else uvicorn.config.LOGGING_CONFIG))
    server_thread = threading.Thread(target=server.run, name="tradebot-web", daemon=True)
    server_thread.start()

    if not _wait_healthy(port):
        logger.error("O painel não subiu; veja %s", folder / "tradebot.log")
    logger.info("TradeBot v%s · painel: %s · dados em: %s", __version__, url, folder)
    if not args.no_browser and not args.after_update:
        webbrowser.open(url)

    try:
        use_tray = not args.no_tray and (sys.platform == "win32" or is_frozen())
        if not (use_tray and _run_tray(url, quit_app, tray)):
            while server_thread.is_alive() and not stopping.is_set():
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        quit_app()
        server_thread.join(timeout=15)
        engine.shutdown()
        instance_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
