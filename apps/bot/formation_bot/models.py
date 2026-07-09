from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Candle:
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int


@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    tick_size: float
    quote_volume: float
    price_change_percent: float | None = None
    trades_24h: int | None = None


@dataclass(frozen=True)
class LevelZone:
    side: str
    lower: float
    upper: float
    touches: int
    score: float
    first_touch_index: int
    last_touch_index: int
    pivot_points: tuple[tuple[int, float], ...] = field(default_factory=tuple)
    level_kind: str = "standard"
    confidence: str = "confirmed"
    impulse_score: float = 0.0
    avg_touch_volume: float = 0.0


@dataclass(frozen=True)
class BreakoutSignal:
    symbol: str
    timeframe: str
    side: str
    price: float
    zone_lower: float
    zone_upper: float
    touches: int
    score: float
    detected_at: datetime
    candle_close_time_ms: int
    is_breakout_type: bool = True
    natr_pct: float = 0.0
    pivot_points: tuple[tuple[int, float], ...] = field(default_factory=tuple)
    level_kind: str = "standard"
    funding_rate_pct: float | None = None
    price_change_24h_pct: float | None = None
    quote_volume_24h: float | None = None
    trades_24h: int | None = None
    btc_correlation_1h: float | None = None
    signal_type: str = ""
    confidence: str = "confirmed"

    @property
    def key(self) -> str:
        state = self.signal_type or ("breakout" if self.is_breakout_type else "test")
        zone = f"{self.zone_lower:.12g}-{self.zone_upper:.12g}"
        return f"{self.symbol}:{self.timeframe}:{self.side}:{zone}:{state}:{self.confidence}"


@dataclass(frozen=True)
class SignalAlert:
    signal: BreakoutSignal
    message: str
    chart_png: bytes | None = None
