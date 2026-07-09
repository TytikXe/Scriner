export type MarketKind =
  | "BINANCE_SPOT"
  | "BINANCE_FUTURES"
  | "BYBIT_SPOT"
  | "BYBIT_FUTURES"
  | "BITGET_SPOT"
  | "BITGET_FUTURES"
  | "GATE_SPOT"
  | "GATE_FUTURES"
  | "MEXC_SPOT"
  | "MEXC_FUTURES"
  | "OKX_SPOT"
  | "OKX_FUTURES";

export type FormationType =
  | "None"
  | "ActiveCoins"
  | "CoinsWithDensity"
  | "HorizontalLevels"
  | "TrendLevels"
  | "HorizontalLevelWithLimitOrder";

export interface Candle {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  trades?: number | null;
}

export interface MarketSymbol {
  symbol: string;
  market: MarketKind;
  exchange: string;
  active: boolean;
  base?: string | null;
  quote?: string | null;
}

export interface FormationSignal {
  type: FormationType;
  symbol: string;
  market: string;
  timeframe: string;
  direction: "up" | "down" | "neutral" | string;
  score: number;
  distancePct: number;
  price: number;
  levelPrice?: number | null;
  densityPrice?: number | null;
  densitySizeUsd?: number | null;
  reason: string;
  detectedAt: string;
}

export interface DensitySignal {
  symbol: string;
  market: string;
  exchange: string;
  price: number;
  levelPrice: number;
  side: string;
  sizeUsd: number;
  distancePct: number;
  lifeMinutes: number;
  corrosionMinutes: number;
  score: number;
  detectedAt: string;
}

export interface Level {
  symbol: string;
  market: string;
  exchange: string;
  type: string;
  price: number;
  timeframe: string;
  touches: number;
  score: number;
  direction: string;
  detectedAt: string;
}

export interface ScreenerRow {
  symbol: string;
  market: string;
  exchange: string;
  price: number;
  priceChange1m: number;
  priceChange3m: number;
  priceChange5m: number;
  priceChange15m: number;
  priceChange30m: number;
  priceChange1h: number;
  priceChange2h: number;
  priceChange6h: number;
  priceChange12h: number;
  priceChange24h: number;
  volumeSum1m: number;
  volumeSum5m: number;
  volumeSum1h: number;
  volumeSum24h: number;
  tradesSum1m: number;
  tradesSum5m: number;
  tradesSum1h: number;
  tradesSum24h: number;
  natr5_14: number;
  volatility: number;
  fundingRate?: number | null;
  openInterest?: number | null;
  hasAlert: boolean;
  inWatchlist: boolean;
  active: boolean;
  formation?: FormationSignal | null;
}

export interface AiFormationInput {
  symbol: string;
  market: string;
  timeframe: string;
  currentPrice: number;
  formation: FormationSignal;
  candles: Candle[];
  horizontalLevels: Level[];
  trendLevels: Level[];
  densities: DensitySignal[];
  metrics: ScreenerRow;
}

export interface AiFormationAnalysis {
  summary: string;
  whyDetected: string[];
  bullishScenario: string;
  bearishScenario: string;
  riskFactors: string[];
  invalidation: string;
  watchPoints: string[];
  confidenceAdjustment: number;
}

export interface ScreenerFilters {
  volumeFrom?: number | null;
  volumeTo?: number | null;
  priceChangeFrom?: number | null;
  priceChangeTo?: number | null;
  tradesFrom?: number | null;
  tradesTo?: number | null;
  natrFrom?: number | null;
  natrTo?: number | null;
  volumeRange?: string;
  priceChangeRange?: string;
  tradesRange?: string;
  onlyActive: boolean;
  onlyWatchlist: boolean;
  onlyAlerts: boolean;
  onlyFormations: boolean;
  blacklist: string[];
  excludedMarkets: string[];
}

export interface ChartSettings {
  timeframe: string;
  candleLimit?: number;
  rightOffset?: number;
  showVolume: boolean;
  showOrderBook: boolean;
  showLevels: boolean;
  showDensities: boolean;
}

export interface FormationSettings {
  formation: FormationType;
  showOnlyFormations: boolean;
  sortByFormations: boolean;
  sortByLevelFormations: boolean;
  formationLimitOrderLevelLocation: "up" | "down" | "same" | "none";
  formationLimitOrderLevelDistance: number;
}

export interface DensitySettings {
  showLimitOrders: boolean;
  showDensitiesWidget: boolean;
  limitOrderFilter: number;
  limitOrderDistance: number;
  limitOrderLife: number;
  limitOrderCorrosionTime: number;
  roundDensity: boolean;
}

export interface HorizontalLevelSettings {
  showHorizontalLevels: boolean;
  showDailyHighAndLow: boolean;
  horizontalLevelsPeriod: number;
  horizontalLevelsTouches: number;
  horizontalLevelsTouchesThreshold: number;
  horizontalLevelsLivingTime: number;
  horizontalLevelsTimeframes: string[];
}

export interface TrendLevelSettings {
  showTrendLevels: boolean;
  trendlinesSource: "high/low" | "close";
  trendlinesPeriod: number;
}

export interface Workspace {
  id: string;
  title: string;
  market: MarketKind | string;
  sortingType: string;
  sortingTypeRange: string;
  sortingTime: "manual" | "auto";
  pinAlerts?: boolean;
  gridLayout: { rows: number; columns: number };
  filters: ScreenerFilters;
  chartSettings: ChartSettings;
  formationSettings: FormationSettings;
  densitySettings: DensitySettings;
  horizontalLevelSettings: HorizontalLevelSettings;
  trendLevelSettings: TrendLevelSettings;
  selectedColumns: string[];
  blacklist: string[];
  excludedMarkets: string[];
}

export interface ScreenerSettings {
  workspaceId?: string | null;
  market?: string | null;
  sortingType: string;
  sortingTypeRange: string;
  filters: ScreenerFilters;
  chartSettings: ChartSettings;
  formationSettings: FormationSettings;
  densitySettings: DensitySettings;
  horizontalLevelSettings: HorizontalLevelSettings;
  trendLevelSettings: TrendLevelSettings;
  selectedColumns: string[];
  blacklist: string[];
  excludedMarkets: string[];
}

export interface Alert {
  id: string;
  userId: string;
  active: boolean;
  type: string;
  symbols: string[];
  market: string;
  direction?: "up" | "down" | "all";
  interval?: string;
  threshold?: number;
  distance?: number;
  lifetime?: number;
  corrosionTime?: number;
  watchlistOnly: boolean;
  sound: string;
  telegramNotification: boolean;
}

export interface WatchlistEntry {
  symbol: string;
  market: string;
  exchange: string;
}
