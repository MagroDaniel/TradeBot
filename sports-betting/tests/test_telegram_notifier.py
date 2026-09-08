from alerts.telegram_notifier import TelegramNotifier
from analysis.multiple import Multiple, MultipleLeg
from storage.picks_store import Pick


def _capture_sent_text(monkeypatch):
    """Substitui requests.post por um stub que só guarda o texto enviado, sem rede."""
    sent = {}

    class _FakeResponse:
        ok = True
        text = ""

        def raise_for_status(self):
            pass

    def _fake_post(url, data, timeout):
        sent["text"] = data["text"]
        return _FakeResponse()

    monkeypatch.setattr("alerts.telegram_notifier.requests.post", _fake_post)
    return sent


def _pick(**overrides) -> Pick:
    base = dict(
        event_id="e1",
        match="Flamengo x Corinthians",
        home_team="Flamengo",
        away_team="Corinthians",
        commence_time="2026-09-12T23:30:00Z",
        market="soccer_brazil_campeonato:1x2/totals",
        selection="Empate",
        odds=4.49,
        model_probability=0.264,
        ev=0.185,
        suggested_stake_fraction=0.013,
    )
    base.update(overrides)
    return Pick(**base)


def test_send_daily_picks_groups_multiple_selections_under_one_match(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    picks = [
        _pick(selection="Empate"),
        _pick(selection="Corinthians vence", odds=9.4, ev=1.29),
    ]

    TelegramNotifier("token", "chat").send_daily_picks("2026-09-08", picks)

    text = sent["text"]
    # o confronto aparece uma vez só, não repetido por seleção
    assert text.count("Flamengo x Corinthians") == 1
    assert "Empate" in text
    assert "Corinthians vence" in text
    assert "20h30" in text  # commence_time convertido pra BRT
    assert "08/09" in text  # data em formato br


def test_send_daily_picks_shows_news_note_when_present(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    picks = [_pick(selection="Empate")]

    TelegramNotifier("token", "chat").send_daily_picks(
        "2026-09-08", picks, news_notes={"Flamengo x Corinthians": "Fulano é dúvida pro jogo."}
    )

    assert "⚠️" in sent["text"]
    assert "Fulano é dúvida pro jogo." in sent["text"]


def test_send_daily_picks_no_news_note_omits_warning_line(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    picks = [_pick(selection="Empate")]

    TelegramNotifier("token", "chat").send_daily_picks("2026-09-08", picks)

    assert "⚠️" not in sent["text"]


def test_send_daily_picks_shows_bookmaker_next_to_odds(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    picks = [_pick(selection="Empate", bookmaker="Bet365")]

    TelegramNotifier("token", "chat").send_daily_picks("2026-09-08", picks)

    assert "odd 4.49 (Bet365)" in sent["text"]


def test_send_daily_picks_omits_bookmaker_when_absent(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    picks = [_pick(selection="Empate", bookmaker=None)]

    TelegramNotifier("token", "chat").send_daily_picks("2026-09-08", picks)

    assert "odd 4.49" in sent["text"]
    assert "(" not in sent["text"].split("odd 4.49")[1].split("\n")[0]


def _multiple(**overrides) -> Multiple:
    base = dict(
        legs=[
            MultipleLeg(
                match="Real Madrid x Getafe",
                selection="Real Madrid vence",
                odds=1.25,
                bookmaker="Bet365",
                model_probability=0.82,
            ),
            MultipleLeg(
                match="Bayern x Union Berlin",
                selection="Bayern vence",
                odds=1.20,
                bookmaker="Pinnacle",
                model_probability=0.85,
            ),
        ],
        combined_odds=1.5,
        combined_probability=0.697,
        combined_ev=0.0455,
    )
    base.update(overrides)
    return Multiple(**base)


def test_send_daily_picks_includes_multiple_section(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    picks = [_pick(selection="Empate")]

    TelegramNotifier("token", "chat").send_daily_picks(
        "2026-09-08", picks, multiple=_multiple()
    )

    text = sent["text"]
    assert "Bilhete sugerido" in text
    assert "Real Madrid x Getafe" in text
    assert "Bayern x Union Berlin" in text
    assert "Odd combinada:</b> 1.50" in text
    assert "Probabilidade estimada:</b> 70%" in text


def test_send_daily_picks_omits_multiple_section_when_none(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    picks = [_pick(selection="Empate")]

    TelegramNotifier("token", "chat").send_daily_picks("2026-09-08", picks)

    assert "Bilhete sugerido" not in sent["text"]


def test_send_daily_picks_shows_multiple_even_without_ev_picks(monkeypatch):
    sent = _capture_sent_text(monkeypatch)

    TelegramNotifier("token", "chat").send_daily_picks(
        "2026-09-08", [], games_today=6, multiple=_multiple()
    )

    text = sent["text"]
    assert "nenhuma aposta de valor" in text
    assert "Bilhete sugerido" in text


def test_send_daily_picks_no_games_today(monkeypatch):
    sent = _capture_sent_text(monkeypatch)

    TelegramNotifier("token", "chat").send_daily_picks("2026-09-08", [], games_today=0)

    assert "Sem jogos hoje" in sent["text"]


def test_send_daily_picks_games_today_but_no_value(monkeypatch):
    sent = _capture_sent_text(monkeypatch)

    TelegramNotifier("token", "chat").send_daily_picks("2026-09-08", [], games_today=6)

    assert "6 jogo(s) hoje" in sent["text"]
    assert "nenhuma aposta de valor" in sent["text"]


def test_send_results_summary_groups_by_match_and_shows_icons(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    picks = [
        _pick(selection="Empate", result="green", profit_units=0.013),
        _pick(selection="Corinthians vence", result="red", profit_units=-0.03),
    ]

    TelegramNotifier("token", "chat").send_results_summary("2026-09-07", picks)

    text = sent["text"]
    assert text.count("Flamengo x Corinthians") == 1
    assert "✅" in text
    assert "❌" in text
    assert "1/2" in text  # 1 acerto de 2 resolvidos


def test_send_results_summary_shows_bookmaker_next_to_odds(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    picks = [_pick(selection="Empate", result="green", profit_units=0.013, bookmaker="Pinnacle")]

    TelegramNotifier("token", "chat").send_results_summary("2026-09-07", picks)

    assert "odd 4.49 (Pinnacle)" in sent["text"]


def test_send_results_summary_no_resolved_picks(monkeypatch):
    sent = _capture_sent_text(monkeypatch)

    TelegramNotifier("token", "chat").send_results_summary("2026-09-07", [])

    assert "Nenhum pick resolvido" in sent["text"]
