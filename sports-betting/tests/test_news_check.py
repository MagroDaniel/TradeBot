from data.news_check import NewsChecker


class _FakeTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeToolUseBlock:
    type = "tool_use"


class _FakeResponse:
    def __init__(self, *texts: str) -> None:
        # intercala um bloco de "uso de ferramenta" entre textos, simulando o padrão real
        # de resposta com busca na web (texto de narração + tool_use + texto final)
        self.content = [_FakeTextBlock(t) if i == 0 else _FakeTextBlock(t) for i, t in enumerate(texts)]


class _FakeMessages:
    def __init__(self, *texts: str) -> None:
        self._texts = texts

    def create(self, **kwargs):
        return _FakeResponse(*self._texts)


class _FakeClient:
    def __init__(self, *texts: str) -> None:
        self.messages = _FakeMessages(*texts)


def test_returns_note_when_relevant_news_found(monkeypatch):
    monkeypatch.setattr(
        "data.news_check.anthropic.Anthropic",
        lambda api_key: _FakeClient("Fulano está machucado e é dúvida pro jogo."),
    )

    note = NewsChecker("fake-key").check_match("Flamengo", "Corinthians", "Brasileirão")

    assert note == "Fulano está machucado e é dúvida pro jogo."


def test_returns_none_when_marker_says_no_news(monkeypatch):
    monkeypatch.setattr("data.news_check.anthropic.Anthropic", lambda api_key: _FakeClient("NADA"))

    note = NewsChecker("fake-key").check_match("Time A", "Time B", "Liga X")

    assert note is None


def test_returns_none_on_api_error(monkeypatch):
    class _BoomMessages:
        def create(self, **kwargs):
            raise RuntimeError("falha de rede simulada")

    class _BoomClient:
        def __init__(self, api_key):
            self.messages = _BoomMessages()

    monkeypatch.setattr("data.news_check.anthropic.Anthropic", _BoomClient)

    note = NewsChecker("fake-key").check_match("Time A", "Time B", "Liga X")

    assert note is None


def test_uses_only_last_text_block_ignoring_process_narration(monkeypatch):
    # resposta real com busca na web costuma vir com um texto de narração antes ("vou
    # pesquisar...") e o texto final depois — só o último deve virar o aviso.
    monkeypatch.setattr(
        "data.news_check.anthropic.Anthropic",
        lambda api_key: _FakeClient("I'll search for recent news.", "Zico está machucado."),
    )

    note = NewsChecker("fake-key").check_match("Time A", "Time B", "Liga X")

    assert note == "Zico está machucado."
    assert "search" not in note


def test_returns_none_on_empty_response(monkeypatch):
    monkeypatch.setattr("data.news_check.anthropic.Anthropic", lambda api_key: _FakeClient(""))

    note = NewsChecker("fake-key").check_match("Time A", "Time B", "Liga X")

    assert note is None
