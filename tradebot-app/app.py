"""Abre o TradeBot: sobe o motor + painel em 127.0.0.1 e abre o navegador.

    python app.py              # uso normal
    python app.py --no-browser # só o servidor (o link com o token aparece no terminal)

Uma instância por vez: se já houver uma rodando, só abre o navegador nela e sai — duas
instâncias operando a mesma carteira seriam duas ordens pro mesmo sinal.

Fechar a aba do navegador NÃO para o bot (de propósito: posições abertas continuam com stop
e alvo monitorados). Pra encerrar, use Ctrl+C nesta janela — o estado (ligado/pausado) é
salvo e restaurado na próxima abertura.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser

import requests
import uvicorn

from tradebot.engine import Engine
from tradebot.paths import data_dir
from tradebot.store import Store
from tradebot.web.server import create_app

INSTANCE_FILE = "instance.json"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _existing_instance(path) -> dict | None:
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        r = requests.get(f"http://127.0.0.1:{info['port']}/health", timeout=2, proxies={"http": None, "https": None})
        return info if r.ok else None
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()

    folder = data_dir()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(folder / "tradebot.log", encoding="utf-8")],
    )
    instance_path = folder / INSTANCE_FILE
    existing = _existing_instance(instance_path)
    if existing:
        url = f"http://127.0.0.1:{existing['port']}/?token={existing['token']}"
        print(f"O TradeBot já está aberto: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return

    port = args.port or _free_port()
    token = secrets.token_urlsafe(32)
    instance_path.write_text(json.dumps({"port": port, "token": token, "pid": os.getpid()}), encoding="utf-8")

    store = Store(folder / "tradebot.db")
    engine = Engine(store, folder)
    engine.start_loop()
    app = create_app(engine, token)
    url = f"http://127.0.0.1:{port}/?token={token}"

    def open_browser():
        for _ in range(50):
            try:
                if requests.get(f"http://127.0.0.1:{port}/health", timeout=1,
                                proxies={"http": None, "https": None}).ok:
                    break
            except Exception:
                time.sleep(0.2)
        print(f"\nPainel: {url}\nDados em: {folder}\nCtrl+C para encerrar.\n")
        if not args.no_browser:
            webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        engine.shutdown()
        instance_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
