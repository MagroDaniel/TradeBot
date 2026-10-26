# -*- mode: python ; coding: utf-8 -*-
# Receita do PyInstaller: `pyinstaller TradeBot.spec` gera dist/TradeBot.exe (um arquivo só, sem
# janela de terminal). Templates, CSS/JS e o ícone vão dentro do executável.
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("uvicorn") + ["pystray._win32"]

a = Analysis(
    ["app.py"],
    pathex=[],
    datas=[
        ("tradebot/web/templates", "tradebot/web/templates"),
        ("tradebot/web/static", "tradebot/web/static"),
        ("assets", "assets"),
    ],
    hiddenimports=hidden,
    excludes=["pytest", "httpx", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TradeBot",
    console=False,
    icon="assets/icon.ico",
    upx=False,
)
