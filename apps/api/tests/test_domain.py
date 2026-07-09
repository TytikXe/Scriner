from datetime import datetime, timedelta, timezone

from app.domain import (
    ai_local_analysis,
    btc_correlation,
    detect_density_signals,
    detect_horizontal_levels,
    detect_trend_levels,
    natr,
    price_change,
    scan_formation,
    trades_sum,
    volume_sum,
)
from app.schemas import AiFormationInput, Candle, DensitySignal, FormationSignal, FormationType, Level, OrderBookLevel, OrderBookSnapshot, ScreenerRow


def make_candles(base: float = 100.0, count: int = 30):
    now = datetime.now(timezone.utc)
    candles = []
    price = base
    for i in range(count):
        close = price + 1
        candles.append(Candle(ts=now + timedelta(minutes=i * 5), open=price, high=close + 1, low=price - 1, close=close, volume=100 + i, trades=10 + i))
        price = close
    return candles


def test_price_and_volume_metrics():
    candles = make_candles()
    assert price_change(candles, 15) > 0
    assert volume_sum(candles, 15) > 0
    assert trades_sum(candles, 15) > 0


def test_natr_and_correlation():
    candles = make_candles()
    btc = make_candles(50000)
    assert natr(candles) >= 0
    assert btc_correlation(candles, btc) <= 1


def test_natr_uses_full_atr_band_width():
    candles = [
        Candle(
            ts=datetime.now(timezone.utc),
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1000,
            trades=100,
        )
        for _ in range(15)
    ]

    assert natr(candles, smooth_period=1) == 4.0


def test_density_and_levels():
    snapshot = OrderBookSnapshot(
        symbol="ETH/USDT",
        market="BINANCE_SPOT",
        exchange="BINANCE",
        ts=datetime.now(timezone.utc),
        bids=[OrderBookLevel(price=99, size=1000, size_usd=99000)],
        asks=[OrderBookLevel(price=101, size=1000, size_usd=101000)],
    )
    densities = detect_density_signals(snapshot, 100, 50000, 5, 5, 5)
    assert densities
    candles = make_candles()
    horizontal = detect_horizontal_levels(candles, "ETH/USDT", "BINANCE_SPOT", "BINANCE", "5m", 20, 2, 0.5)
    trend = detect_trend_levels(candles, "ETH/USDT", "BINANCE_SPOT", "BINANCE", "5m", 20)
    assert isinstance(horizontal, list)
    assert isinstance(trend, list)


def test_formation_scanner_and_ai_local():
    candles = make_candles()
    density = DensitySignal(
        symbol="ETH/USDT",
        market="BINANCE_SPOT",
        exchange="BINANCE",
        price=100,
        levelPrice=101,
        side="ask",
        sizeUsd=100000,
        distancePct=1,
        lifeMinutes=10,
        corrosionMinutes=1,
        score=90,
        detectedAt=datetime.now(timezone.utc),
    )
    formation = scan_formation(
        "ETH/USDT",
        "BINANCE_SPOT",
        "BINANCE",
        "5m",
        100,
        candles,
        [density],
        [Level(symbol="ETH/USDT", market="BINANCE_SPOT", exchange="BINANCE", type="horizontal", price=100.5, timeframe="5m", touches=4, score=80, direction="neutral", detectedAt=datetime.now(timezone.utc))],
        [Level(symbol="ETH/USDT", market="BINANCE_SPOT", exchange="BINANCE", type="trend", price=100.4, timeframe="5m", touches=4, score=75, direction="up", detectedAt=datetime.now(timezone.utc))],
        FormationType.HorizontalLevelWithLimitOrder,
    )
    assert formation is not None
    result = ai_local_analysis(
        AiFormationInput(
            symbol="ETH/USDT",
            market="BINANCE_SPOT",
            timeframe="5m",
            currentPrice=100,
            formation=formation,
            candles=candles,
            horizontalLevels=[],
            trendLevels=[],
            densities=[density],
            metrics=ScreenerRow(
                symbol="ETH/USDT",
                market="BINANCE_SPOT",
                exchange="BINANCE",
                price=100,
                priceChange1m=1,
                priceChange3m=1,
                priceChange5m=1,
                priceChange15m=1,
                priceChange30m=1,
                priceChange1h=1,
                priceChange2h=1,
                priceChange6h=1,
                priceChange12h=1,
                priceChange24h=1,
                volumeSum1m=1,
                volumeSum5m=1,
                volumeSum1h=1,
                volumeSum24h=1,
                tradesSum1m=1,
                tradesSum5m=1,
                tradesSum1h=1,
                tradesSum24h=1,
                natr5_14=1,
                volatility=1,
                btcCorrelation=0,
                hasAlert=False,
                inWatchlist=False,
                active=True,
            ),
        )
    )
    assert result.summary
