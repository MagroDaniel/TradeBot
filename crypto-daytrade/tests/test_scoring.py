from analysis.scoring import assess


def test_detects_seed_tag_as_high_risk():
    result = assess("Binance Will List MarsCoin (MARSCOIN) with Seed Tag Applied", None)

    assert result.is_high_risk
    assert "Seed Tag" in result.risk_tags


def test_no_risk_tag_in_title_is_not_high_risk():
    result = assess("Binance Will Add MarsCoin (MARSCOIN) on Earn, Buy Crypto, Convert", None)

    assert not result.is_high_risk
    assert result.risk_tags == []


def test_detects_innovation_zone_case_insensitive():
    result = assess("Binance Will List FooCoin (FOO) in the innovation zone", None)

    assert result.is_high_risk
    assert "Innovation Zone" in result.risk_tags


def test_no_ticker_data_means_no_momentum_yet():
    result = assess("Binance Will List FooCoin (FOO)", None)

    assert result.price_change_percent is None
    assert result.quote_volume is None
    assert "ainda sem dado de mercado" in result.summary()


def test_ticker_data_populates_momentum():
    ticker = {"priceChangePercent": "42.5", "quoteVolume": "1234567.89"}

    result = assess("Binance Will List FooCoin (FOO)", ticker)

    assert result.price_change_percent == 42.5
    assert result.quote_volume == 1234567.89
    assert "+42.5%" in result.summary()


def test_negative_price_change_has_no_plus_sign():
    ticker = {"priceChangePercent": "-15.0", "quoteVolume": "1000"}

    result = assess("Binance Will List FooCoin (FOO)", ticker)

    assert "-15.0%" in result.summary()
    assert "+-15.0%" not in result.summary()
