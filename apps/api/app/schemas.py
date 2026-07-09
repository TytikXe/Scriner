from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MarketKind(str, Enum):
    BINANCE_SPOT = "BINANCE_SPOT"
    BINANCE_FUTURES = "BINANCE_FUTURES"
    BYBIT_SPOT = "BYBIT_SPOT"
    BYBIT_FUTURES = "BYBIT_FUTURES"
    BITGET_SPOT = "BITGET_SPOT"
    BITGET_FUTURES = "BITGET_FUTURES"
    GATE_SPOT = "GATE_SPOT"
    GATE_FUTURES = "GATE_FUTURES"
    MEXC_SPOT = "MEXC_SPOT"
    MEXC_FUTURES = "MEXC_FUTURES"
    OKX_SPOT = "OKX_SPOT"
    OKX_FUTURES = "OKX_FUTURES"


class FormationType(str, Enum):
    None_ = "None"
    ActiveCoins = "ActiveCoins"
    CoinsWithDensity = "CoinsWithDensity"
    HorizontalLevels = "HorizontalLevels"
    TrendLevels = "TrendLevels"
    HorizontalLevelWithLimitOrder = "HorizontalLevelWithLimitOrder"


class ScreenerSort(str, Enum):
    top_gainers = "top_gainers"
    top_losers = "top_losers"
    volume = "volume"
    trades = "trades"
    volatility = "volatility"
    natr = "natr"
    btc_correlation = "btc_correlation"
    alerts_first = "alerts_first"
    watchlist_first = "watchlist_first"
    formations_first = "formations_first"


class Candle(BaseModel):
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int | None = None


class MarketSymbol(BaseModel):
    symbol: str
    market: str
    exchange: str
    active: bool = True
    base: str | None = None
    quote: str | None = None


class Ticker(BaseModel):
    symbol: str
    market: str
    exchange: str
    last: float
    bid: float | None = None
    ask: float | None = None
    quoteVolume: float | None = None
    baseVolume: float | None = None
    priceChangePercent: float | None = None
    trades: int | None = None
    ts: datetime | None = None


class OrderBookLevel(BaseModel):
    price: float
    size: float
    size_usd: float | None = None


class OrderBookSnapshot(BaseModel):
    symbol: str
    market: str
    exchange: str
    ts: datetime
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]


class DensitySignal(BaseModel):
    symbol: str
    market: str
    exchange: str
    price: float
    levelPrice: float
    side: str
    sizeUsd: float
    distancePct: float
    lifeMinutes: float
    corrosionMinutes: float
    score: float
    detectedAt: datetime


class Level(BaseModel):
    symbol: str
    market: str
    exchange: str
    type: str
    price: float
    timeframe: str
    touches: int
    score: float
    direction: str
    detectedAt: datetime


class FormationSignal(BaseModel):
    type: FormationType
    symbol: str
    market: str
    timeframe: str
    direction: str
    score: float
    distancePct: float
    price: float
    levelPrice: float | None = None
    densityPrice: float | None = None
    densitySizeUsd: float | None = None
    reason: str
    detectedAt: datetime


class ScreenerRow(BaseModel):
    symbol: str
    market: str
    exchange: str
    price: float
    priceChange1m: float
    priceChange3m: float
    priceChange5m: float
    priceChange15m: float
    priceChange30m: float
    priceChange1h: float
    priceChange2h: float
    priceChange6h: float
    priceChange12h: float
    priceChange24h: float
    volumeSum1m: float
    volumeSum5m: float
    volumeSum1h: float
    volumeSum24h: float
    tradesSum1m: float
    tradesSum5m: float
    tradesSum1h: float
    tradesSum24h: float
    natr5_14: float
    volatility: float
    btcCorrelation: float
    fundingRate: float | None = None
    openInterest: float | None = None
    hasAlert: bool = False
    inWatchlist: bool = False
    active: bool = True
    formation: FormationSignal | None = None


class ScreenerFilters(BaseModel):
    volumeFrom: float | None = None
    volumeTo: float | None = None
    priceChangeFrom: float | None = None
    priceChangeTo: float | None = None
    tradesFrom: float | None = None
    tradesTo: float | None = None
    natrFrom: float | None = None
    natrTo: float | None = None
    btcCorrelationFrom: float | None = None
    btcCorrelationTo: float | None = None
    onlyActive: bool = False
    onlyWatchlist: bool = False
    onlyAlerts: bool = False
    onlyFormations: bool = False
    blacklist: list[str] = Field(default_factory=list)
    excludedMarkets: list[str] = Field(default_factory=list)


class ChartSettings(BaseModel):
    timeframe: str = "5m"
    showVolume: bool = True
    showOrderBook: bool = True
    showLevels: bool = True
    showDensities: bool = True


class FormationSettings(BaseModel):
    formation: FormationType = FormationType.None_
    showOnlyFormations: bool = False
    sortByFormations: bool = False
    sortByLevelFormations: bool = False
    formationLimitOrderLevelLocation: str = "none"
    formationLimitOrderLevelDistance: float = 0.5


class DensitySettings(BaseModel):
    showLimitOrders: bool = True
    showDensitiesWidget: bool = True
    limitOrderFilter: float = 50000
    limitOrderDistance: float = 1.5
    limitOrderLife: float = 5
    limitOrderCorrosionTime: float = 15
    roundDensity: bool = True


class HorizontalLevelSettings(BaseModel):
    showHorizontalLevels: bool = True
    showDailyHighAndLow: bool = True
    horizontalLevelsPeriod: int = 200
    horizontalLevelsTouches: int = 3
    horizontalLevelsTouchesThreshold: float = 0.25
    horizontalLevelsLivingTime: int = 60
    horizontalLevelsTimeframes: list[str] = Field(default_factory=lambda: ["5m", "15m", "1h"])


class TrendLevelSettings(BaseModel):
    showTrendLevels: bool = True
    trendlinesSource: str = "high/low"
    trendlinesPeriod: int = 120


class Workspace(BaseModel):
    id: str
    title: str
    market: str
    sortingType: str
    sortingTypeRange: str
    sortingTime: str = "manual"
    gridLayout: dict[str, int] = Field(default_factory=lambda: {"rows": 3, "columns": 4})
    filters: ScreenerFilters = Field(default_factory=ScreenerFilters)
    chartSettings: ChartSettings = Field(default_factory=ChartSettings)
    formationSettings: FormationSettings = Field(default_factory=FormationSettings)
    densitySettings: DensitySettings = Field(default_factory=DensitySettings)
    horizontalLevelSettings: HorizontalLevelSettings = Field(default_factory=HorizontalLevelSettings)
    trendLevelSettings: TrendLevelSettings = Field(default_factory=TrendLevelSettings)
    selectedColumns: list[str] = Field(default_factory=list)
    blacklist: list[str] = Field(default_factory=list)
    excludedMarkets: list[str] = Field(default_factory=list)


class WatchlistEntry(BaseModel):
    symbol: str
    market: str
    exchange: str


class Alert(BaseModel):
    id: str
    userId: str
    active: bool
    type: str
    symbols: list[str]
    market: str
    direction: str | None = None
    interval: str | None = None
    threshold: float | None = None
    distance: float | None = None
    lifetime: float | None = None
    corrosionTime: float | None = None
    watchlistOnly: bool = False
    sound: str = "default"
    telegramNotification: bool = False


class AiFormationInput(BaseModel):
    symbol: str
    market: str
    timeframe: str
    currentPrice: float
    formation: FormationSignal
    candles: list[Candle]
    horizontalLevels: list[Level]
    trendLevels: list[Level]
    densities: list[DensitySignal]
    metrics: ScreenerRow


class AiFormationAnalysis(BaseModel):
    summary: str
    whyDetected: list[str]
    bullishScenario: str
    bearishScenario: str
    riskFactors: list[str]
    invalidation: str
    watchPoints: list[str]
    confidenceAdjustment: float


class ScreenerSettings(BaseModel):
    workspaceId: str | None = None
    market: str | None = None
    sortingType: str = ScreenerSort.top_gainers.value
    sortingTypeRange: str = "24h"
    filters: ScreenerFilters = Field(default_factory=ScreenerFilters)
    chartSettings: ChartSettings = Field(default_factory=ChartSettings)
    formationSettings: FormationSettings = Field(default_factory=FormationSettings)
    densitySettings: DensitySettings = Field(default_factory=DensitySettings)
    horizontalLevelSettings: HorizontalLevelSettings = Field(default_factory=HorizontalLevelSettings)
    trendLevelSettings: TrendLevelSettings = Field(default_factory=TrendLevelSettings)
    selectedColumns: list[str] = Field(default_factory=list)
    blacklist: list[str] = Field(default_factory=list)
    excludedMarkets: list[str] = Field(default_factory=list)


class MarketsResponse(BaseModel):
    markets: list[MarketSymbol]


class ScreenerDataResponse(BaseModel):
    rows: list[ScreenerRow]
    generatedAt: datetime


class WorkspaceListResponse(BaseModel):
    workspaces: list[Workspace]


class CandleResponse(BaseModel):
    symbol: str
    market: str
    exchange: str
    timeframe: str
    candles: list[Candle]


class DensitiesResponse(BaseModel):
    symbol: str
    market: str
    exchange: str
    densities: list[DensitySignal]


class FormationListResponse(BaseModel):
    formations: list[FormationSignal]


class WatchlistResponse(BaseModel):
    items: list[WatchlistEntry]


class AlertsResponse(BaseModel):
    items: list[Alert]


class EventMessage(BaseModel):
    topic: str
    payload: dict[str, Any]
    ts: datetime = Field(default_factory=datetime.utcnow)
