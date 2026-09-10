from datetime import datetime, timedelta, timezone

import news_watch
from analysis.news_signals import STRATEGY_VERSION
from data.forexfactory_client import EconomicEvent
from data.twelvedata_client import Candle
from storage.signals_store import SignalRecord, SignalsStore

_RELEASE_DT = datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc)
_AFTER_WAIT = _RELEASE_DT + timedelta(minutes=15)


class _FakeNotifier:
    def __init__(self) -> None:
        self.alerts: list[SignalRecord] = []
        self.results: list[SignalRecord] = []
        self.weekly_calls: list[tuple] = []
        self.monthly_calls: list[tuple] = []

    def send_experimental_signal_alert(self, signal: SignalRecord) -> None:
        self.alerts.append(signal)

    def send_experimental_result(self, signal: SignalRecord) -> None:
        self.results.append(signal)

    def send_weekly_report(self, period_start, period_end, summary, records) -> None:
        self.weekly_calls.append((period_start, period_end, summary, records))

    def send_monthly_report(self, month_label, summary, records) -> None:
        self.monthly_calls.append((month_label, summary, records))


class _FakeForexFactoryClient:
    def __init__(self, events: list[EconomicEvent]) -> None:
        self._events = events

    def get_relevant_high_impact_events(self) -> list[EconomicEvent]:
        return self._events


class _FakePriceClient:
    def __init__(self, candles: list[Candle], current_price: float | None = None) -> None:
        self._candles = candles
        self._current_price = current_price

    def get_candles(self, symbol, interval, outputsize=100):
        return self._candles

    def get_current_price(self, symbol):
        return self._current_price


def _event(**overrides) -> EconomicEvent:
    base = dict(
        title="Non-Farm Payrolls",
        country="USD",
        date=_RELEASE_DT.isoformat(),
        impact="High",
        forecast="180K",
        previous="150K",
        actual="220K",
    )
    base.update(overrides)
    return EconomicEvent(**base)


def _candles(n=30, base=1.1000, step=0.0001) -> list[Candle]:
    return [
        Candle(
            open_time_ms=i, open=base + i * step, high=base + i * step + 0.0005,
            low=base + i * step - 0.0005, close=base + i * step, volume=0.0,
        )
        for i in range(n)
    ]


def test_scan_sends_alert_and_persists_signal(tmp_path, monkeypatch):
    monkeypatch.setattr(news_watch.config, "FOREX_SYMBOLS", ("EUR/USD",))
    store = SignalsStore(tmp_path / "news_signals.json")
    notifier = _FakeNotifier()
    ff_client = _FakeForexFactoryClient([_event()])
    price_client = _FakePriceClient(_candles(), current_price=1.1050)

    news_watch.scan_for_news_signals(ff_client, price_client, store, notifier, now=_AFTER_WAIT)

    assert len(notifier.alerts) == 1
    assert len(store.all_signals()) == 1
    assert store.all_signals()[0].strategy_version == STRATEGY_VERSION


def test_scan_does_not_resend_same_event_symbol_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(news_watch.config, "FOREX_SYMBOLS", ("EUR/USD",))
    store = SignalsStore(tmp_path / "news_signals.json")
    notifier = _FakeNotifier()
    ff_client = _FakeForexFactoryClient([_event()])
    price_client = _FakePriceClient(_candles(), current_price=1.1050)

    news_watch.scan_for_news_signals(ff_client, price_client, store, notifier, now=_AFTER_WAIT)
    news_watch.scan_for_news_signals(ff_client, price_client, store, notifier, now=_AFTER_WAIT)

    assert len(notifier.alerts) == 1
    assert len(store.all_signals()) == 1


def test_scan_does_not_mark_seen_when_wait_window_not_closed(tmp_path, monkeypatch):
    # actual foi divulgado mas ainda não passaram os 15min de espera -> generate_signal
    # devolve None; não deve marcar como "visto" (senão nunca mais tentaria de novo).
    monkeypatch.setattr(news_watch.config, "FOREX_SYMBOLS", ("EUR/USD",))
    recent_event = _event(date=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    store = SignalsStore(tmp_path / "news_signals.json")
    notifier = _FakeNotifier()
    ff_client = _FakeForexFactoryClient([recent_event])
    price_client = _FakePriceClient(_candles())

    news_watch.scan_for_news_signals(ff_client, price_client, store, notifier)

    assert notifier.alerts == []
    key = news_watch._event_symbol_key(recent_event, "EUR/USD")
    assert not store.has_seen_news_event(key)


def test_scan_skips_events_without_surprise_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(news_watch.config, "FOREX_SYMBOLS", ("EUR/USD",))
    store = SignalsStore(tmp_path / "news_signals.json")
    notifier = _FakeNotifier()
    ff_client = _FakeForexFactoryClient([_event(actual=None)])
    price_client = _FakePriceClient(_candles())

    news_watch.scan_for_news_signals(ff_client, price_client, store, notifier)

    assert notifier.alerts == []
    assert store.all_signals() == []


def _signal_record(**overrides) -> SignalRecord:
    base = dict(
        symbol="EUR/USD",
        direction="long",
        entry=1.1000,
        stop_loss=1.0950,
        target=1.1100,
        rsi_value=0.0,
        reason="teste",
        opened_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        strategy_version=STRATEGY_VERSION,
        market_mode="forex_experimental",
    )
    base.update(overrides)
    return SignalRecord(**base)


def test_resolve_sends_result_and_updates_status(tmp_path):
    store = SignalsStore(tmp_path / "news_signals.json")
    opened_at = datetime.now(timezone.utc) - timedelta(hours=1)
    store.add(_signal_record(opened_at=opened_at.isoformat()))
    notifier = _FakeNotifier()
    # candle que bate o alvo (1.1100), com open_time_ms depois de opened_at
    after_open_ms = int(opened_at.timestamp() * 1000) + 60_000
    hit_candles = [
        Candle(
            open_time_ms=after_open_ms, open=1.1000, high=1.1150, low=1.0990, close=1.1100,
            volume=0.0,
        )
    ]
    price_client = _FakePriceClient(hit_candles)

    news_watch.resolve_open_news_signals(price_client, store, notifier)

    assert len(notifier.results) == 1
    assert store.all_signals()[0].status == "target_hit"


def test_resolve_does_nothing_when_no_open_signals(tmp_path):
    store = SignalsStore(tmp_path / "news_signals.json")
    notifier = _FakeNotifier()
    price_client = _FakePriceClient([])

    news_watch.resolve_open_news_signals(price_client, store, notifier)

    assert notifier.results == []
