import hashlib

import pytest
from fastapi.testclient import TestClient

from tests.helpers import FakeMarketData
from tradebot.engine import Engine
from tradebot.store import Store
from tradebot.updater import Release, UpdateManager, latest_release, parse_version, updater_script
from tradebot.web.server import create_app

EXE = b"MZ-novo-executavel" * 1000


class FakeResponse:
    def __init__(self, status=200, json_data=None, content=b""):
        self.status_code = status
        self._json = json_data
        self.content = content
        self.text = content.decode(errors="ignore")

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i:i + size]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSession:
    def __init__(self, tag="v0.2.0", sha=None, exe=EXE, status=200):
        self.tag, self.exe, self.status = tag, exe, status
        self.sha = sha or hashlib.sha256(EXE).hexdigest()

    def get(self, url, **kw):
        if "api.github.com" in url:
            if self.status != 200:
                return FakeResponse(self.status)
            return FakeResponse(json_data={
                "tag_name": self.tag, "body": "- novidade", "html_url": "https://github.com/x/releases/v0.2.0",
                "assets": [{"name": "TradeBot.exe", "browser_download_url": "https://dl/TradeBot.exe"},
                           {"name": "TradeBot.exe.sha256", "browser_download_url": "https://dl/TradeBot.exe.sha256"}]})
        if url.endswith(".sha256"):
            return FakeResponse(content=f"{self.sha}  TradeBot.exe\n".encode())
        return FakeResponse(content=self.exe)


def _manager(tmp_path, session, frozen=True, version="0.1.0"):
    calls = {"launched": [], "shutdown": 0}
    m = UpdateManager(tmp_path, shutdown=lambda: calls.__setitem__("shutdown", calls["shutdown"] + 1),
                      session=session, current_version=version, frozen=frozen, executable=tmp_path / "TradeBot.exe")
    m._launch = lambda script: calls["launched"].append(script)
    return m, calls


def test_parse_version():
    assert parse_version("v1.2.10") == (1, 2, 10)
    assert parse_version("0.1.0") == (0, 1, 0)
    assert parse_version("v1.2") is None and parse_version("") is None
    assert parse_version("v0.10.0") > parse_version("v0.9.9")


def test_latest_release_and_missing_release():
    r = latest_release(FakeSession())
    assert r.version == "0.2.0" and r.exe_url.endswith("TradeBot.exe") and r.sha_url.endswith(".sha256")
    assert latest_release(FakeSession(status=404)) is None


def test_available_only_when_newer(tmp_path):
    m, _ = _manager(tmp_path, FakeSession(tag="v0.1.0"))
    m.check(force=True)
    assert not m.available
    m, _ = _manager(tmp_path, FakeSession(tag="v0.2.0"))
    m.check(force=True)
    assert m.available and m.can_install


def test_install_downloads_verifies_and_launches_swap(tmp_path, monkeypatch):
    import threading
    monkeypatch.setattr(threading, "Timer", lambda delay, fn: type("T", (), {"start": lambda self: fn()})())
    m, calls = _manager(tmp_path, FakeSession())
    m.check(force=True)
    m.install()
    new_exe = tmp_path / "update" / "TradeBot-0.2.0.exe"
    assert new_exe.read_bytes() == EXE
    [script] = calls["launched"]
    text = script.read_text()
    assert str(new_exe) in text and "--after-update" in text
    assert calls["shutdown"] == 1


def test_install_rejects_hash_mismatch(tmp_path):
    m, calls = _manager(tmp_path, FakeSession(sha="0" * 64))
    m.check(force=True)
    with pytest.raises(ValueError, match="SHA-256"):
        m.install()
    assert calls["launched"] == [] and calls["shutdown"] == 0
    assert not (tmp_path / "update" / "TradeBot-0.2.0.exe").exists()
    assert not m.installing  # pode tentar de novo


def test_install_refused_when_running_from_source(tmp_path):
    m, _ = _manager(tmp_path, FakeSession(), frozen=False)
    m.check(force=True)
    assert m.available and not m.can_install
    with pytest.raises(ValueError):
        m.install()


def test_check_failure_is_reported_not_raised(tmp_path):
    class Boom:
        def get(self, *a, **k):
            raise ConnectionError("sem internet")
    m, _ = _manager(tmp_path, Boom())
    assert m.check(force=True) is None
    assert "sem internet" in m.error


def test_script_waits_for_pid_and_restarts(tmp_path):
    text = updater_script(4242, tmp_path / "new.exe", tmp_path / "TradeBot.exe")
    assert 'PID eq 4242' in text and "move /Y" in text and 'start ""' in text


def test_panel_banner_and_install(tmp_path, monkeypatch):
    import threading
    monkeypatch.setattr(threading, "Timer", lambda delay, fn: type("T", (), {"start": lambda self: fn()})())
    engine = Engine(Store(":memory:"), tmp_path, market_data={"spot": FakeMarketData("spot"), "futures": FakeMarketData("futures")})
    m, calls = _manager(tmp_path, FakeSession())
    client = TestClient(create_app(engine, "t", m))
    client.get("/?token=t")
    client.cookies.set("tradebot_token", "t")
    banner = client.get("/partials/update").text
    assert "Nova versão 0.2.0" in banner and "Atualizar" in banner and "novidade" in banner
    assert "v0.1.0" in client.get("/").text  # versão do app aparece no topo
    r = client.post("/api/update/install")
    assert r.status_code == 200 and "reabrir" in r.text
    assert calls["shutdown"] == 1


def test_panel_without_updates(tmp_path):
    engine = Engine(Store(":memory:"), tmp_path, market_data={"spot": FakeMarketData("spot"), "futures": FakeMarketData("futures")})
    m, _ = _manager(tmp_path, FakeSession(tag="v0.1.0"))
    client = TestClient(create_app(engine, "t", m))
    client.get("/?token=t")
    client.cookies.set("tradebot_token", "t")
    assert client.get("/partials/update").text.strip() == ""
    assert "mais recente" in client.get("/partials/update?force=1").text
