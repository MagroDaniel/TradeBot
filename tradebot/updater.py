"""Atualização do executável pelas Releases do GitHub.

Fluxo (só no `.exe`; rodando pelo código-fonte o painel só avisa e sugere `git pull`):
1. `check()` consulta `api.github.com/repos/<repo>/releases/latest` (sem token — limite de 60
   consultas/hora por IP, por isso o resultado fica em cache por 6 h).
2. `install()` baixa `TradeBot.exe` e `TradeBot.exe.sha256` da release, confere o SHA-256 (um
   download corrompido ou trocado no caminho é recusado), e grava um script `.bat` que espera
   este processo terminar, troca o `.exe` e abre a versão nova.
3. O app encerra normalmente (motor salva o estado de cada robô) e o `.bat` faz o resto.

Os dados (robôs, carteiras, histórico) ficam em %APPDATA%\\TradeBot, fora do `.exe` — a troca
de versão não mexe neles.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from tradebot import GITHUB_REPO, __version__

logger = logging.getLogger(__name__)

EXE_ASSET = "TradeBot.exe"
SHA_ASSET = "TradeBot.exe.sha256"
CHECK_INTERVAL_S = 6 * 3600


def parse_version(tag: str) -> tuple[int, ...] | None:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (tag or "").strip())
    return tuple(int(x) for x in match.groups()) if match else None


def is_frozen() -> bool:
    """True rodando como `.exe` do PyInstaller."""
    return bool(getattr(sys, "frozen", False))


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    url: str  # página da release
    exe_url: str | None
    sha_url: str | None


def latest_release(session: requests.Session | None = None, repo: str = GITHUB_REPO) -> Release | None:
    http = session or requests.Session()
    response = http.get(f"https://api.github.com/repos/{repo}/releases/latest",
                        headers={"Accept": "application/vnd.github+json"}, timeout=15)
    if response.status_code == 404:
        return None  # ainda não existe release
    response.raise_for_status()
    data = response.json()
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets") or []}
    return Release(
        version=str(data.get("tag_name", "")).lstrip("v"),
        notes=(data.get("body") or "").strip(),
        url=data.get("html_url", ""),
        exe_url=assets.get(EXE_ASSET),
        sha_url=assets.get(SHA_ASSET),
    )


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def updater_script(pid: int, new_exe: Path, current_exe: Path) -> str:
    """`.bat` que espera o app fechar, troca o executável (com algumas tentativas — o Windows
    pode segurar o arquivo por alguns segundos) e abre a versão nova. Se não conseguir trocar,
    abre a versão antiga de novo, pra o bot não ficar desligado."""
    return f"""@echo off
setlocal
:wait
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto wait
)
set tries=0
:move
move /Y "{new_exe}" "{current_exe}" >nul 2>&1
if errorlevel 1 (
  set /a tries+=1
  if %tries% lss 15 (
    timeout /t 2 /nobreak >nul
    goto move
  )
)
start "" "{current_exe}" --after-update
del "%~f0"
"""


class UpdateManager:
    """Estado da atualização pro painel. `shutdown` é chamado depois que o script de troca foi
    disparado (o launcher encerra servidor, motor e ícone da bandeja)."""

    def __init__(self, data_dir: Path, shutdown=None, session: requests.Session | None = None,
                 current_version: str = __version__, frozen: bool | None = None,
                 executable: Path | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.shutdown = shutdown
        self.http = session or requests.Session()
        self.current_version = current_version
        self.frozen = is_frozen() if frozen is None else frozen
        self.executable = Path(executable or sys.executable)
        self.release: Release | None = None
        self.checked_at = 0.0
        self.error: str | None = None
        self.installing = False
        self._lock = threading.Lock()

    def check(self, force: bool = False) -> Release | None:
        with self._lock:
            if not force and time.time() - self.checked_at < CHECK_INTERVAL_S:
                return self.release
            try:
                self.release = latest_release(self.http)
                self.error = None
            except Exception as exc:
                self.error = f"Não consegui verificar atualizações: {exc}"
                logger.warning(self.error)
            self.checked_at = time.time()
            return self.release

    @property
    def available(self) -> bool:
        current, latest = parse_version(self.current_version), parse_version(self.release.version if self.release else "")
        return bool(current and latest and latest > current)

    @property
    def can_install(self) -> bool:
        return self.available and self.frozen and bool(self.release.exe_url and self.release.sha_url)

    def install(self) -> None:
        """Baixa, confere e dispara a troca. Levanta ValueError com mensagem pro painel."""
        if not self.can_install:
            raise ValueError("Atualização automática só funciona no .exe e com uma release válida")
        with self._lock:
            if self.installing:
                raise ValueError("Atualização já em andamento")
            self.installing = True
        try:
            folder = self.data_dir / "update"
            folder.mkdir(parents=True, exist_ok=True)
            new_exe = folder / f"TradeBot-{self.release.version}.exe"
            expected = self.http.get(self.release.sha_url, timeout=30).text.split()[0].strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise ValueError("Arquivo de verificação (SHA-256) da release inválido")
            with self.http.get(self.release.exe_url, stream=True, timeout=120) as response:
                response.raise_for_status()
                with new_exe.open("wb") as f:
                    for chunk in response.iter_content(1 << 20):
                        f.write(chunk)
            if sha256_of(new_exe) != expected:
                new_exe.unlink(missing_ok=True)
                raise ValueError("Download não confere com o SHA-256 da release — atualização cancelada")
            script = folder / "atualizar.bat"
            script.write_text(updater_script(os.getpid(), new_exe, self.executable), encoding="utf-8")
            self._launch(script)
        except Exception:
            with self._lock:
                self.installing = False
            raise
        logger.info("Atualização para %s pronta; encerrando para trocar o executável", self.release.version)
        if self.shutdown:
            threading.Timer(1.0, self.shutdown).start()  # deixa a resposta HTTP sair antes

    def _launch(self, script: Path) -> None:
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        subprocess.Popen(["cmd", "/c", str(script)], creationflags=flags, close_fds=True)
