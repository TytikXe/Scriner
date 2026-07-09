from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .adapters import build_adapter
from .config import settings
from .domain import (
    apply_filters,
    build_screener_row,
    detect_density_signals,
    detect_horizontal_levels,
    detect_trend_levels,
    scan_formation,
    sort_rows,
)
from .schemas import (
    Alert,
    AlertsResponse,
    AiFormationInput,
    Candle,
    DensitiesResponse,
    DensitySettings,
    FormationListResponse,
    FormationSettings,
    FormationSignal,
    HorizontalLevelSettings,
    MarketKind,
    MarketsResponse,
    OrderBookSnapshot,
    ScreenerDataResponse,
    ScreenerFilters,
    ScreenerRow,
    ScreenerSettings,
    TrendLevelSettings,
    WatchlistEntry,
    Workspace,
)
from .storage import store


DEFAULT_BASE_TIMEFRAME = "5m"


def _seed_candles(price: float = 100.0, count: int = 288, step: float = 0.25) -> list[Candle]:
    now = datetime.now(timezone.utc)
    candles: list[Candle] = []
    current = price
    for idx in range(count):
        drift = ((idx % 9) - 4) * step
        open_ = current
        close = max(0.0001, current + drift * 0.35)
        high = max(open_, close) + abs(drift) * 0.5 + 0.1
        low = max(0.0001, min(open_, close) - abs(drift) * 0.5 - 0.1)
        volume = 1000 + idx * 5
        candles.append(Candle(ts=now, open=open_, high=high, low=low, close=close, volume=volume, trades=int(volume / 10)))
        current = close
    return candles


def _sample_snapshot(symbol: str, market: str, exchange: str, price: float) -> OrderBookSnapshot:
    from .schemas import OrderBookLevel, OrderBookSnapshot

    bids = [
        OrderBookLevel(price=price * 0.999, size=1200, size_usd=price * 0.999 * 1200),
        OrderBookLevel(price=price * 0.995, size=2500, size_usd=price * 0.995 * 2500),
    ]
    asks = [
        OrderBookLevel(price=price * 1.001, size=1100, size_usd=price * 1.001 * 1100),
        OrderBookLevel(price=price * 1.006, size=2200, size_usd=price * 1.006 * 2200),
    ]
    return OrderBookSnapshot(symbol=symbol, market=market, exchange=exchange, ts=datetime.now(timezone.utc), bids=bids, asks=asks)


class ScreenerService:
    def __init__(self) -> None:
        self.store = store

    async def get_markets(self) -> MarketsResponse:
        markets = []
        for item in [
            MarketKind.BINANCE_SPOT,
            MarketKind.BINANCE_FUTURES,
            MarketKind.BYBIT_SPOT,
            MarketKind.BYBIT_FUTURES,
            MarketKind.BITGET_SPOT,
            MarketKind.BITGET_FUTURES,
            MarketKind.GATE_SPOT,
            MarketKind.GATE_FUTURES,
            MarketKind.MEXC_SPOT,
            MarketKind.MEXC_FUTURES,
            MarketKind.OKX_SPOT,
            MarketKind.OKX_FUTURES,
        ]:
            markets.append(
                {
                    "symbol": item.value,
                    "market": item.value,
                    "exchange": item.value.split("_")[0],
                    "active": True,
                }
            )
        return MarketsResponse(markets=markets)

    def get_workspaces(self) -> list[Workspace]:
        return self.store.get_workspaces()

    def update_workspace(self, workspace: Workspace) -> Workspace:
        return self.store.upsert_workspace(workspace)

    def delete_workspace(self, workspace_id: str) -> bool:
        return self.store.delete_workspace(workspace_id)

    def get_settings(self) -> ScreenerSettings:
        return self.store.get_settings()

    def update_settings(self, settings_payload: ScreenerSettings) -> ScreenerSettings:
        return self.store.update_settings(settings_payload)

    def get_watchlist(self) -> list[WatchlistEntry]:
        return self.store.get_watchlist()

    def update_watchlist(self, items: list[WatchlistEntry]) -> list[WatchlistEntry]:
        return self.store.set_watchlist(items)

    def get_alerts(self) -> list[Alert]:
        return self.store.get_alerts()

    def upsert_alert(self, alert: Alert) -> Alert:
        return self.store.upsert_alert(alert)

    def delete_alert(self, alert_id: str) -> bool:
        return self.store.delete_alert(alert_id)

    def evaluate_alerts(self, rows: list[ScreenerRow]) -> list[dict]:
        watchlist = {(item.symbol, item.market) for item in self.get_watchlist()}
        matches: list[dict] = []
        for alert in self.get_alerts():
            if not alert.active:
                continue
            for row in rows:
                if alert.market and row.market != alert.market:
                    continue
                if alert.symbols and row.symbol not in alert.symbols:
                    continue
                if alert.watchlistOnly and (row.symbol, row.market) not in watchlist:
                    continue
                matched = False
                if alert.type == "formationDetected" and row.formation:
                    matched = True
                elif alert.type == "priceChange" and alert.threshold is not None:
                    matched = abs(row.priceChange24h) >= alert.threshold
                elif alert.type == "volumeSplash" and alert.threshold is not None:
                    matched = row.volumeSum24h >= alert.threshold
                elif alert.type == "volatility" and alert.threshold is not None:
                    matched = row.volatility >= alert.threshold
                elif alert.type == "btcCorrelation" and alert.threshold is not None:
                    matched = abs(row.btcCorrelation) >= alert.threshold
                elif alert.type == "openInterest" and alert.threshold is not None:
                    matched = (row.openInterest or 0) >= alert.threshold
                elif alert.type == "funding" and alert.threshold is not None:
                    matched = abs(row.fundingRate or 0) >= alert.threshold
                elif alert.type == "trendLevels" and row.formation and row.formation.type == "TrendLevels":
                    matched = True
                elif alert.type == "limitOrder" and row.formation and row.formation.type in {"CoinsWithDensity", "HorizontalLevelWithLimitOrder"}:
                    matched = True
                if matched:
                    matches.append(
                        {
                            "alertId": alert.id,
                            "symbol": row.symbol,
                            "market": row.market,
                            "type": alert.type,
                            "price": row.price,
                            "formation": row.formation.model_dump(mode="json") if row.formation else None,
                        }
                    )
        return matches

    async def get_candles(self, symbol: str, market: str, timeframe: str, limit: int) -> list[Candle]:
        try:
            adapter = build_adapter(market)
            return await adapter.get_candles(symbol, timeframe, limit)
        except Exception:
            return _seed_candles(count=max(limit, 50))

    async def get_order_book(self, symbol: str, market: str, depth: int) -> OrderBookSnapshot:
        try:
            adapter = build_adapter(market)
            return await adapter.get_order_book(symbol, depth)
        except Exception:
            return _sample_snapshot(symbol, market, market.split("_")[0], 100.0)

    async def build_rows(self, settings_payload: ScreenerSettings | None = None) -> list[ScreenerRow]:
        settings_payload = settings_payload or self.get_settings()
        rows: list[ScreenerRow] = []
        btc_candles = _seed_candles(price=65000, count=600, step=6)
        symbols = [
            ("BTC/USDT", 65000, "BINANCE_SPOT"),
            ("ETH/USDT", 3500, "BINANCE_SPOT"),
            ("SOL/USDT", 160, "BYBIT_SPOT"),
            ("XRP/USDT", 0.52, "GATE_SPOT"),
            ("DOGE/USDT", 0.14, "MEXC_SPOT"),
        ]
        watchlist = {(item.symbol, item.market) for item in self.get_watchlist()}
        alert_symbols = {symbol for alert in self.get_alerts() for symbol in alert.symbols}
        for symbol, price, market in symbols:
            candles = _seed_candles(price=price, count=600, step=max(price * 0.002, 0.01))
            density_snapshot = _sample_snapshot(symbol, market, market.split("_")[0], candles[-1].close)
            densities = detect_density_signals(
                density_snapshot,
                candles[-1].close,
                settings_payload.densitySettings.limitOrderFilter,
                settings_payload.densitySettings.limitOrderDistance,
                settings_payload.densitySettings.limitOrderLife,
                settings_payload.densitySettings.limitOrderCorrosionTime,
                settings_payload.densitySettings.roundDensity,
            )
            horizontal_levels = detect_horizontal_levels(
                candles,
                symbol,
                market,
                market.split("_")[0],
                settings_payload.chartSettings.timeframe,
                settings_payload.horizontalLevelSettings.horizontalLevelsPeriod,
                settings_payload.horizontalLevelSettings.horizontalLevelsTouches,
                settings_payload.horizontalLevelSettings.horizontalLevelsTouchesThreshold,
            )
            trend_levels = detect_trend_levels(
                candles,
                symbol,
                market,
                market.split("_")[0],
                settings_payload.chartSettings.timeframe,
                settings_payload.trendLevelSettings.trendlinesPeriod,
                settings_payload.trendLevelSettings.trendlinesSource,
            )
            formation_type = settings_payload.formationSettings.formation
            formation = scan_formation(
                symbol,
                market,
                market.split("_")[0],
                settings_payload.chartSettings.timeframe,
                candles[-1].close,
                candles,
                densities,
                horizontal_levels,
                trend_levels,
                formation_type,
                density_distance_limit=settings_payload.densitySettings.limitOrderDistance,
                limit_order_level_distance=settings_payload.formationSettings.formationLimitOrderLevelDistance,
            )
            row = build_screener_row(
                symbol=symbol,
                market=market,
                exchange=market.split("_")[0],
                candles=candles,
                btc_candles=btc_candles,
                formation=formation,
                has_alert=symbol in alert_symbols,
                in_watchlist=(symbol, market) in watchlist,
                active=True,
            )
            rows.append(row)
        rows = apply_filters(rows, settings_payload.filters)
        rows = sort_rows(rows, settings_payload.sortingType)
        return rows

    async def get_screener_data(self) -> ScreenerDataResponse:
        rows = await self.build_rows()
        return ScreenerDataResponse(rows=rows, generatedAt=datetime.now(timezone.utc))

    async def get_densities(self, symbol: str, market: str) -> DensitiesResponse:
        candles = _seed_candles(price=100, count=120)
        snapshot = _sample_snapshot(symbol, market, market.split("_")[0], candles[-1].close)
        densities = detect_density_signals(snapshot, candles[-1].close, 1000, 5, 5, 5)
        return DensitiesResponse(symbol=symbol, market=market, exchange=market.split("_")[0], densities=densities)

    async def get_formations(self) -> FormationListResponse:
        rows = await self.build_rows()
        formations = [row.formation for row in rows if row.formation]
        return FormationListResponse(formations=formations)

    async def rescan_formations(self) -> FormationListResponse:
        return await self.get_formations()


service = ScreenerService()
