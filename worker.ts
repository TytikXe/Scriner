type Json = Record<string, unknown>;

type Candle = {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  trades: number;
};

type FormationType =
  | "None"
  | "ActiveCoins"
  | "CoinsWithDensity"
  | "HorizontalLevels"
  | "TrendLevels"
  | "HorizontalLevelWithLimitOrder";

type FormationSignal = {
  type: FormationType;
  symbol: string;
  market: string;
  timeframe: string;
  direction: "up" | "down" | "neutral";
  score: number;
  distancePct: number;
  price: number;
  levelPrice?: number;
  densityPrice?: number;
  densitySizeUsd?: number;
  reason: string;
  detectedAt: string;
};

type ScreenerRow = {
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
};

type Workspace = {
  id: string;
  title: string;
  market: string;
  sortingType: string;
  sortingTypeRange: string;
  sortingTime: "manual" | "auto";
  pinAlerts?: boolean;
  gridLayout: { rows: number; columns: number };
  filters: {
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
  };
  chartSettings: { timeframe: string; candleLimit?: number; rightOffset?: number; showVolume: boolean; showOrderBook: boolean; showLevels: boolean; showDensities: boolean };
  formationSettings: {
    formation: FormationType;
    showOnlyFormations: boolean;
    sortByFormations: boolean;
    sortByLevelFormations: boolean;
    formationLimitOrderLevelLocation: "up" | "down" | "same" | "none";
    formationLimitOrderLevelDistance: number;
  };
  densitySettings: {
    showLimitOrders: boolean;
    showDensitiesWidget: boolean;
    limitOrderFilter: number;
    limitOrderDistance: number;
    limitOrderLife: number;
    limitOrderCorrosionTime: number;
    roundDensity: boolean;
  };
  horizontalLevelSettings: {
    showHorizontalLevels: boolean;
    showDailyHighAndLow: boolean;
    horizontalLevelsPeriod: number;
    horizontalLevelsTouches: number;
    horizontalLevelsTouchesThreshold: number;
    horizontalLevelsLivingTime: number;
    horizontalLevelsTimeframes: string[];
  };
  trendLevelSettings: { showTrendLevels: boolean; trendlinesSource: "high/low" | "close"; trendlinesPeriod: number };
  selectedColumns: string[];
  blacklist: string[];
  excludedMarkets: string[];
};

type Alert = {
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
};

type AppState = {
  workspaces: Workspace[];
  currentSettings: Workspace | null;
  watchlist: { symbol: string; market: string; exchange: string }[];
  alerts: Alert[];
  aiCache: Record<string, { expiresAt: string; value: unknown }>;
};

type Env = {
  SCREENER_STATE: KVNamespace;
  ASSETS: Fetcher;
};

const markets = [
  "BINANCE_SPOT",
  "BINANCE_FUTURES",
  "BYBIT_SPOT",
  "BYBIT_FUTURES",
  "BITGET_SPOT",
  "BITGET_FUTURES",
  "GATE_SPOT",
  "GATE_FUTURES",
  "MEXC_SPOT",
  "MEXC_FUTURES",
  "OKX_SPOT",
  "OKX_FUTURES"
] as const;

const symbols = [
  ["BTC/USDT", 65000, "BINANCE_SPOT"],
  ["ETH/USDT", 3500, "BINANCE_SPOT"],
  ["SOL/USDT", 160, "BYBIT_SPOT"],
  ["XRP/USDT", 0.52, "GATE_SPOT"],
  ["DOGE/USDT", 0.14, "MEXC_SPOT"],
  ["LINK/USDT", 14, "BYBIT_SPOT"],
  ["AVAX/USDT", 32, "BINANCE_FUTURES"],
  ["ADA/USDT", 0.43, "BITGET_SPOT"]
] as const;

const liveMarkets = ["BINANCE_SPOT", "BINANCE_FUTURES"] as const;
const exchangeCache = new Map<string, { expiresAt: number; value: unknown }>();

function nowIso() {
  return new Date().toISOString();
}

function seed(n: string) {
  let h = 2166136261;
  for (let i = 0; i < n.length; i++) {
    h ^= n.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return () => {
    h += h << 13;
    h ^= h >>> 7;
    h += h << 3;
    h ^= h >>> 17;
    h += h << 5;
    return (h >>> 0) / 4294967295;
  };
}

function defaultWorkspaces(): Workspace[] {
  const baseFilters = {
    onlyActive: false,
    onlyWatchlist: false,
    onlyAlerts: false,
    onlyFormations: false,
    blacklist: [],
    excludedMarkets: []
  };
  const baseChart = { timeframe: "5m", showVolume: true, showOrderBook: true, showLevels: true, showDensities: true };
  const baseFormation = {
    formation: "None" as FormationType,
    showOnlyFormations: false,
    sortByFormations: false,
    sortByLevelFormations: false,
    formationLimitOrderLevelLocation: "none" as const,
    formationLimitOrderLevelDistance: 0.5
  };
  const baseDensity = {
    showLimitOrders: true,
    showDensitiesWidget: true,
    limitOrderFilter: 50000,
    limitOrderDistance: 1.5,
    limitOrderLife: 5,
    limitOrderCorrosionTime: 15,
    roundDensity: true
  };
  const baseHorizontal = {
    showHorizontalLevels: true,
    showDailyHighAndLow: true,
    horizontalLevelsPeriod: 200,
    horizontalLevelsTouches: 3,
    horizontalLevelsTouchesThreshold: 0.25,
    horizontalLevelsLivingTime: 60,
    horizontalLevelsTimeframes: ["5m", "15m", "1h"]
  };
  const baseTrend = { showTrendLevels: true, trendlinesSource: "high/low" as const, trendlinesPeriod: 120 };
  const cols = ["symbol", "market", "exchange", "price", "priceChange24h", "volumeSum24h", "tradesSum24h", "natr5_14", "volatility", "formation", "hasAlert", "inWatchlist"];
  return [
    { id: "futures", title: "Futures", market: "BINANCE_FUTURES", sortingType: "top_gainers", sortingTypeRange: "24h", sortingTime: "manual", pinAlerts: false, gridLayout: { rows: 3, columns: 3 }, filters: structuredClone(baseFilters), chartSettings: { ...structuredClone(baseChart), candleLimit: 400, rightOffset: 0 }, formationSettings: structuredClone(baseFormation), densitySettings: structuredClone(baseDensity), horizontalLevelSettings: structuredClone(baseHorizontal), trendLevelSettings: structuredClone(baseTrend), selectedColumns: cols, blacklist: [], excludedMarkets: [] },
    { id: "trades", title: "Сделки", market: "BINANCE_FUTURES", sortingType: "trades", sortingTypeRange: "1h", sortingTime: "manual", gridLayout: { rows: 3, columns: 3 }, filters: structuredClone(baseFilters), chartSettings: structuredClone(baseChart), formationSettings: structuredClone(baseFormation), densitySettings: structuredClone(baseDensity), horizontalLevelSettings: structuredClone(baseHorizontal), trendLevelSettings: structuredClone(baseTrend), selectedColumns: cols, blacklist: [], excludedMarkets: [] },
    { id: "densities", title: "Плотности", market: "BINANCE_FUTURES", sortingType: "volume", sortingTypeRange: "1h", sortingTime: "manual", gridLayout: { rows: 3, columns: 3 }, filters: structuredClone(baseFilters), chartSettings: structuredClone(baseChart), formationSettings: structuredClone(baseFormation), densitySettings: structuredClone(baseDensity), horizontalLevelSettings: structuredClone(baseHorizontal), trendLevelSettings: structuredClone(baseTrend), selectedColumns: cols, blacklist: [], excludedMarkets: [] },
    { id: "levels", title: "Уровни", market: "BINANCE_SPOT", sortingType: "formations_first", sortingTypeRange: "1h", sortingTime: "manual", gridLayout: { rows: 3, columns: 3 }, filters: structuredClone(baseFilters), chartSettings: structuredClone(baseChart), formationSettings: structuredClone(baseFormation), densitySettings: structuredClone(baseDensity), horizontalLevelSettings: structuredClone(baseHorizontal), trendLevelSettings: structuredClone(baseTrend), selectedColumns: cols, blacklist: [], excludedMarkets: [] },
    { id: "watchlist", title: "Watchlist", market: "BINANCE_SPOT", sortingType: "watchlist_first", sortingTypeRange: "24h", sortingTime: "manual", gridLayout: { rows: 3, columns: 3 }, filters: structuredClone(baseFilters), chartSettings: structuredClone(baseChart), formationSettings: structuredClone(baseFormation), densitySettings: structuredClone(baseDensity), horizontalLevelSettings: structuredClone(baseHorizontal), trendLevelSettings: structuredClone(baseTrend), selectedColumns: cols, blacklist: [], excludedMarkets: [] }
  ];
}

function defaultState(): AppState {
  return {
    workspaces: defaultWorkspaces(),
    currentSettings: defaultWorkspaces()[0],
    watchlist: [],
    alerts: [],
    aiCache: {}
  };
}

async function loadState(env: Env): Promise<AppState> {
  const raw = await env.SCREENER_STATE.get("state");
  if (!raw) return defaultState();
  try {
    const state = JSON.parse(raw) as AppState;
    const sanitizeWorkspace = (workspace: Workspace) => {
      workspace.selectedColumns = (workspace.selectedColumns || []).filter((column) => column !== "btcCorrelation");
      if (workspace.sortingType === "btc_correlation") workspace.sortingType = "top_gainers";
      delete (workspace.filters as Record<string, unknown>).btcCorrelationFrom;
      delete (workspace.filters as Record<string, unknown>).btcCorrelationTo;
      if (workspace.id === "top-gainers" && workspace.title === "Топ роста") {
        workspace.title = "Futures";
        workspace.market = "BINANCE_FUTURES";
      }
    };
    state.workspaces.forEach(sanitizeWorkspace);
    sanitizeWorkspace(state.currentSettings);
    state.alerts = state.alerts.filter((alert) => alert.type !== "btcCorrelation");
    return state;
  } catch {
    return defaultState();
  }
}

async function saveState(env: Env, state: AppState): Promise<void> {
  await env.SCREENER_STATE.put("state", JSON.stringify(state));
}

function json(data: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(data), {
    ...init,
    headers: { "content-type": "application/json; charset=utf-8", ...(init?.headers || {}) }
  });
}

function timeframeMinutes(timeframe: string) {
  const map: Record<string, number> = { "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720, "24h": 1440 };
  return map[timeframe] || 5;
}

function basePrice(symbol: string) {
  return symbol === "BTC/USDT" ? 65000 : symbol === "ETH/USDT" ? 3500 : symbol === "SOL/USDT" ? 160 : symbol === "XRP/USDT" ? 0.52 : symbol === "DOGE/USDT" ? 0.14 : symbol === "LINK/USDT" ? 14 : symbol === "AVAX/USDT" ? 32 : 0.43;
}

function pricePoint(symbol: string, market: string, atMs: number, live = false) {
  const base = basePrice(symbol);
  const marketBias = 0.96 + seed(`${symbol}:${market}:market-bias`)() * 0.12;
  const days = (atMs - Date.UTC(2026, 0, 1)) / 86_400_000;
  const trendPerDay = (seed(`${symbol}:${market}:trend`)() - 0.5) * 0.004;
  const phaseA = seed(`${symbol}:${market}:phase-a`)() * Math.PI * 2;
  const phaseB = seed(`${symbol}:${market}:phase-b`)() * Math.PI * 2;
  const wave = Math.sin(days * 2.2 + phaseA) * 0.025 + Math.sin(days * 8.5 + phaseB) * 0.009;
  const minuteBucket = Math.floor(atMs / 60_000);
  const noise = (seed(`${symbol}:${market}:noise:${minuteBucket}`)() - 0.5) * 0.004;
  const liveNoise = live ? (seed(`${symbol}:${market}:live:${Math.floor(Date.now() / 5_000)}`)() - 0.5) * 0.0025 : 0;
  return Math.max(0.000001, base * marketBias * Math.exp(trendPerDay * days + wave + noise + liveNoise));
}

function generateCandles(symbol: string, market: string, limit = 180, timeframe = "5m"): Candle[] {
  const interval = timeframeMinutes(timeframe) * 60_000;
  const now = Date.now();
  const candles: Candle[] = [];
  const alignedNow = Math.floor(now / interval) * interval;
  for (let i = limit - 1; i >= 0; i--) {
    const start = alignedNow - i * interval;
    const isCurrent = i === 0;
    const elapsed = isCurrent ? Math.max(0.08, Math.min(1, (now - start) / interval)) : 1;
    const closeTime = isCurrent ? now : start + interval;
    const wickRand = seed(`${symbol}:${market}:${timeframe}:wick:${start}`);
    const open = pricePoint(symbol, market, start);
    const close = pricePoint(symbol, market, closeTime, isCurrent);
    const spread = Math.max(Math.abs(close - open), basePrice(symbol) * (0.0008 + wickRand() * 0.0018));
    const high = Math.max(open, close) + spread * (0.18 + wickRand() * 0.65);
    const low = Math.max(0.000001, Math.min(open, close) - spread * (0.18 + wickRand() * 0.65));
    const fullVolume = 900 + wickRand() * 5000;
    const volume = fullVolume * elapsed;
    candles.push({
      ts: new Date(start).toISOString(),
      open,
      high,
      low,
      close,
      volume,
      trades: Math.round(volume / (8 + wickRand() * 20))
    });
  }
  return candles;
}

function windowCandles(candles: Candle[], minutes: number, timeframe: string) {
  const per = Math.max(timeframeMinutes(timeframe), 1);
  const count = Math.max(1, Math.floor(minutes / per));
  return candles.slice(-count);
}

function priceChange(candles: Candle[], minutes: number, timeframe = "5m") {
  const per = Math.max(timeframeMinutes(timeframe), 1);
  const w = candles.slice(-Math.max(2, Math.floor(minutes / per) + 1));
  if (w.length < 2) return 0;
  const start = w[0].close;
  const end = w[w.length - 1].close;
  return start ? ((end - start) / start) * 100 : 0;
}

function volumeSum(candles: Candle[], minutes: number, timeframe = "5m") {
  return windowCandles(candles, minutes, timeframe).reduce((sum, c) => sum + c.volume, 0);
}

function tradesSum(candles: Candle[], minutes: number, timeframe = "5m") {
  return windowCandles(candles, minutes, timeframe).reduce((sum, c) => sum + c.trades, 0);
}

function natr(candles: Candle[]) {
  if (candles.length < 15) return 0;
  const trs: number[] = [];
  for (let i = 1; i < candles.length; i++) {
    const prev = candles[i - 1];
    const cur = candles[i];
    trs.push(Math.max(cur.high - cur.low, Math.abs(cur.high - prev.close), Math.abs(cur.low - prev.close)));
  }
  const atr = trs.slice(-14).reduce((s, v) => s + v, 0) / 14;
  const close = candles[candles.length - 1].close;
  return close ? (atr / close) * 200 : 0;
}

function volatility(candles: Candle[]) {
  const candlesPerPeriod = 12; // 1 hour on the 5m metric series
  const hourlyBars = new Map<number, Candle[]>();
  for (const candle of candles) {
    const timestamp = new Date(candle.ts).getTime();
    if (!Number.isFinite(timestamp)) continue;
    const hour = Math.floor(timestamp / 3_600_000);
    const bucket = hourlyBars.get(hour) || [];
    bucket.push(candle);
    hourlyBars.set(hour, bucket);
  }
  const completedHours = [...hourlyBars.entries()]
    .sort(([left], [right]) => left - right)
    .filter(([, bucket]) => bucket.length >= candlesPerPeriod)
    .slice(0, -1);
  const closes = completedHours.map(([, bucket]) => bucket[bucket.length - 1]?.close || 0).filter((close) => close > 0);
  const returns = closes.slice(1).map((close, index) => (close - closes[index]) / closes[index]);
  if (returns.length < 2) return 0;
  const mean = returns.reduce((sum, value) => sum + value, 0) / returns.length;
  const variance = returns.reduce((sum, value) => sum + (value - mean) ** 2, 0) / returns.length;
  return Math.sqrt(variance) * 100;
}

function findHorizontalLevels(candles: Candle[], symbol: string, market: string, exchange: string, timeframe: string) {
  const levels: { price: number; touches: number; score: number; direction: "up" | "down" | "neutral" }[] = [];
  const buckets = new Map<number, number>();
  for (const candle of candles.slice(-200)) {
    for (const price of [candle.high, candle.low, candle.close]) {
      const rounded = Math.round(price / 0.25) * 0.25;
      buckets.set(rounded, (buckets.get(rounded) || 0) + 1);
    }
  }
  for (const [price, touches] of buckets.entries()) {
    if (touches >= 3) levels.push({ price, touches, score: Math.min(100, 50 + touches * 6), direction: "neutral" });
  }
  return levels.sort((a, b) => b.score - a.score).slice(0, 5).map((level) => ({ ...level, symbol, market, exchange, timeframe }));
}

function findTrendLevels(candles: Candle[], symbol: string, market: string, exchange: string, timeframe: string) {
  const window = candles.slice(-120);
  if (window.length < 10) return [];
  const xs = window.map((_, i) => i);
  const ys = window.map((c) => (c.high + c.low) / 2);
  const xm = xs.reduce((s, v) => s + v, 0) / xs.length;
  const ym = ys.reduce((s, v) => s + v, 0) / ys.length;
  let num = 0;
  let den = 0;
  for (let i = 0; i < xs.length; i++) {
    num += (xs[i] - xm) * (ys[i] - ym);
    den += (xs[i] - xm) ** 2;
  }
  if (!den) return [];
  const slope = num / den;
  const intercept = ym - slope * xm;
  const fitted = slope * (xs.length - 1) + intercept;
  const direction = slope > 0 ? "up" : slope < 0 ? "down" : "neutral";
  return [
    {
      symbol,
      market,
      exchange,
      type: "trend",
      price: fitted,
      timeframe,
      touches: Math.max(2, Math.floor(window.length / 20)),
      score: Math.min(100, 65 + Math.abs(slope) * 1000),
      direction,
      detectedAt: nowIso()
    }
  ];
}

function detectDensities(price: number, symbol: string, market: string, exchange: string) {
  return [
    {
      symbol,
      market,
      exchange,
      price,
      levelPrice: price * 0.999,
      side: "bid",
      sizeUsd: 125000,
      distancePct: 0.1,
      lifeMinutes: 12,
      corrosionMinutes: 3,
      score: 88,
      detectedAt: nowIso()
    },
    {
      symbol,
      market,
      exchange,
      price,
      levelPrice: price * 1.001,
      side: "ask",
      sizeUsd: 95000,
      distancePct: 0.1,
      lifeMinutes: 10,
      corrosionMinutes: 2,
      score: 82,
      detectedAt: nowIso()
    }
  ];
}

function scanFormation(row: Omit<ScreenerRow, "formation">, density: ReturnType<typeof detectDensities>, horizontal: ReturnType<typeof findHorizontalLevels>, trend: ReturnType<typeof findTrendLevels>, formation: FormationType): FormationSignal | null {
  const price = row.price;
  if (formation === "None") return null;
  if (formation === "ActiveCoins") {
    if (row.volumeSum15m >= 50000 || row.tradesSum15m >= 250) {
      return { type: formation, symbol: row.symbol, market: row.market, timeframe: "5m", direction: "neutral", score: 78, distancePct: 0, price, reason: "Activity threshold passed.", detectedAt: nowIso() };
    }
  }
  if (formation === "CoinsWithDensity") {
    const near = density[0];
    if (near && near.distancePct <= 1.5) {
      return { type: formation, symbol: row.symbol, market: row.market, timeframe: "5m", direction: near.side === "ask" ? "down" : "up", score: 84, distancePct: near.distancePct, price, densityPrice: near.levelPrice, densitySizeUsd: near.sizeUsd, reason: "Density near price.", detectedAt: nowIso() };
    }
  }
  if (formation === "HorizontalLevels") {
    const level = horizontal[0];
    if (level && Math.abs(level.price - price) / price * 100 <= 0.5) {
      return { type: formation, symbol: row.symbol, market: row.market, timeframe: "5m", direction: level.direction, score: 80, distancePct: Math.abs(level.price - price) / price * 100, price, levelPrice: level.price, reason: "Price near horizontal level.", detectedAt: nowIso() };
    }
  }
  if (formation === "TrendLevels") {
    const level = trend[0];
    if (level && Math.abs(level.price - price) / price * 100 <= 1.0) {
      return { type: formation, symbol: row.symbol, market: row.market, timeframe: "5m", direction: level.direction, score: 76, distancePct: Math.abs(level.price - price) / price * 100, price, levelPrice: level.price, reason: "Price near trend level.", detectedAt: nowIso() };
    }
  }
  if (formation === "HorizontalLevelWithLimitOrder") {
    const level = horizontal[0];
    const near = density[0];
    if (level && near && Math.abs(level.price - near.levelPrice) / price * 100 <= 0.5) {
      return { type: formation, symbol: row.symbol, market: row.market, timeframe: "5m", direction: level.direction, score: 88, distancePct: Math.abs(level.price - near.levelPrice) / price * 100, price, levelPrice: level.price, densityPrice: near.levelPrice, densitySizeUsd: near.sizeUsd, reason: "Level overlaps density.", detectedAt: nowIso() };
    }
  }
  return null;
}

function baseRows(state: AppState, marketFilter?: string | null): ScreenerRow[] {
  const watch = new Set(state.watchlist.map((w) => `${w.symbol}:${w.market}`));
  const alerts = new Set(state.alerts.flatMap((a) => a.symbols.map((s) => `${s}:${a.market}`)));
  const chartTimeframe = state.currentSettings?.chartSettings?.timeframe || "5m";
  const metricsTimeframe = "5m";
  const metricsLimit = Math.ceil(1440 / timeframeMinutes(metricsTimeframe)) + 1;
  const shortLimit = 121;
  const activeMarkets = marketFilter && markets.includes(marketFilter as (typeof markets)[number]) ? [marketFilter] : markets;
  return symbols.flatMap(([symbol]) =>
    activeMarkets.map((market) => {
      const exchange = String(market).split("_")[0];
      const candles = generateCandles(symbol, String(market), metricsLimit, metricsTimeframe);
      const shortCandles = generateCandles(symbol, String(market), shortLimit, "1m");
      const rowBase = {
        symbol,
        market: String(market),
        exchange,
        price: candles[candles.length - 1].close,
        priceChange1m: priceChange(shortCandles, 1, "1m"),
        priceChange3m: priceChange(shortCandles, 3, "1m"),
        priceChange5m: priceChange(shortCandles, 5, "1m"),
        priceChange15m: priceChange(shortCandles, 15, "1m"),
        priceChange30m: priceChange(shortCandles, 30, "1m"),
        priceChange1h: priceChange(shortCandles, 60, "1m"),
        priceChange2h: priceChange(shortCandles, 120, "1m"),
        priceChange6h: priceChange(candles, 360, metricsTimeframe),
        priceChange12h: priceChange(candles, 720, metricsTimeframe),
        priceChange24h: priceChange(candles, 1440, metricsTimeframe),
        volumeSum1m: volumeSum(shortCandles, 1, "1m"),
        volumeSum5m: volumeSum(shortCandles, 5, "1m"),
        volumeSum1h: volumeSum(shortCandles, 60, "1m"),
        volumeSum24h: volumeSum(candles, 1440, metricsTimeframe),
        tradesSum1m: tradesSum(shortCandles, 1, "1m"),
        tradesSum5m: tradesSum(shortCandles, 5, "1m"),
        tradesSum1h: tradesSum(shortCandles, 60, "1m"),
        tradesSum24h: tradesSum(candles, 1440, metricsTimeframe),
        natr5_14: natr(candles),
        volatility: volatility(candles),
        fundingRate: String(market).includes("FUTURES") ? ((seed(`${symbol}:${market}:funding`)() - 0.5) * 0.01) : null,
        openInterest: String(market).includes("FUTURES") ? 1_000_000 + seed(`${symbol}:${market}:oi`)() * 10_000_000 : null,
        hasAlert: alerts.has(`${symbol}:${market}`),
        inWatchlist: watch.has(`${symbol}:${market}`),
        active: true
      };
      const densities = detectDensities(rowBase.price, symbol, String(market), exchange);
      const horizontal = findHorizontalLevels(candles, symbol, String(market), exchange, chartTimeframe);
      const trend = findTrendLevels(candles, symbol, String(market), exchange, chartTimeframe);
      const formation = scanFormation({ ...rowBase, volumeSum15m: volumeSum(shortCandles, 15, "1m"), tradesSum15m: tradesSum(shortCandles, 15, "1m") } as ScreenerRow & { volumeSum15m: number; tradesSum15m: number }, densities, horizontal, trend, state.currentSettings?.formationSettings?.formation || "None");
      return { ...rowBase, formation };
    })
  );
}

function changeForRange(row: ScreenerRow, range: string) {
  if (range === "1m") return row.priceChange1m;
  if (range === "3m") return row.priceChange3m;
  if (range === "5m") return row.priceChange5m;
  if (range === "15m") return row.priceChange15m;
  if (range === "30m") return row.priceChange30m;
  if (range === "1h") return row.priceChange1h;
  if (range === "2h") return row.priceChange2h;
  if (range === "6h") return row.priceChange6h;
  if (range === "12h") return row.priceChange12h;
  return row.priceChange24h;
}

function sortRows(rows: ScreenerRow[], sortType: string, range = "24h") {
  const copy = [...rows];
  const sortRange = range === "24h" || copy.some((row) => changeForRange(row, range) !== 0) ? range : "24h";
  switch (sortType) {
    case "top_losers":
      return copy.sort((a, b) => changeForRange(a, sortRange) - changeForRange(b, sortRange) || b.volumeSum24h - a.volumeSum24h);
    case "volume":
      return copy.sort((a, b) => b.volumeSum24h - a.volumeSum24h);
    case "trades":
      return copy.sort((a, b) => b.tradesSum24h - a.tradesSum24h);
    case "volatility":
      return copy.sort((a, b) => b.volatility - a.volatility);
    case "natr":
      return copy.sort((a, b) => b.natr5_14 - a.natr5_14);
    case "alerts_first":
      return copy.sort((a, b) => Number(b.hasAlert) - Number(a.hasAlert) || b.volumeSum24h - a.volumeSum24h);
    case "watchlist_first":
      return copy.sort((a, b) => Number(b.inWatchlist) - Number(a.inWatchlist) || b.volumeSum24h - a.volumeSum24h);
    case "formations_first":
      return copy.sort((a, b) => Number(Boolean(b.formation)) - Number(Boolean(a.formation)) || (b.formation?.score || 0) - (a.formation?.score || 0));
    default:
      return copy.sort((a, b) => changeForRange(b, sortRange) - changeForRange(a, sortRange) || b.volumeSum24h - a.volumeSum24h);
  }
}

function applyFilters(rows: ScreenerRow[], filters: Workspace["filters"]) {
  return rows.filter((row) => {
    if (filters.onlyActive && !row.active) return false;
    if (filters.onlyWatchlist && !row.inWatchlist) return false;
    if (filters.onlyAlerts && !row.hasAlert) return false;
    if (filters.onlyFormations && !row.formation) return false;
    if (filters.blacklist.includes(row.symbol)) return false;
    if (filters.excludedMarkets.includes(row.market)) return false;
    const within = (v: number, low?: number | null, high?: number | null) => (low != null && v < low ? false : high != null && v > high ? false : true);
    if (!within(row.volumeSum24h, filters.volumeFrom, filters.volumeTo)) return false;
    if (!within(row.priceChange24h, filters.priceChangeFrom, filters.priceChangeTo)) return false;
    if (!within(row.tradesSum24h, filters.tradesFrom, filters.tradesTo)) return false;
    if (!within(row.natr5_14, filters.natrFrom, filters.natrTo)) return false;
    return true;
  });
}

function aiLocal(input: any) {
  const formation = input.formation;
  return {
    summary: `Formation ${formation.type} on ${input.symbol} is being analyzed from the provided data.`,
    whyDetected: [formation.reason, formation.levelPrice ? `Level near ${formation.levelPrice}` : "", formation.densityPrice ? `Density near ${formation.densityPrice}` : ""].filter(Boolean),
    bullishScenario: "If price holds above the nearest level and volume expands, the setup stays constructive.",
    bearishScenario: "If price loses the nearest level or density disappears, the setup weakens.",
    riskFactors: ["Local volatility can invalidate the setup.", "Density can disappear quickly.", "This is probabilistic, not guaranteed."],
    invalidation: "The scenario weakens when price moves away from the nearest level or density.",
    watchPoints: [String(input.currentPrice), `score=${formation.score}`, `distance=${formation.distancePct}%`],
    confidenceAdjustment: Math.max(-1, Math.min(1, (formation.score - 50) / 50))
  };
}

async function parseBody<T>(request: Request): Promise<T> {
  return (await request.json()) as T;
}

function withCors(response: Response) {
  const headers = new Headers(response.headers);
  headers.set("access-control-allow-origin", "*");
  headers.set("access-control-allow-headers", "*");
  headers.set("access-control-allow-methods", "GET,POST,PUT,DELETE,OPTIONS");
  return new Response(response.body, { status: response.status, headers });
}

function binanceBaseUrls(market: string) {
  if (market === "BINANCE_SPOT") {
    return [
      "https://api.binance.com",
      "https://www.binance.com",
      "https://data-api.binance.vision",
      "https://api1.binance.com",
      "https://api2.binance.com",
      "https://api3.binance.com"
    ];
  }
  if (market === "BINANCE_FUTURES") return ["https://www.binance.com", "https://fapi.binance.com"];
  return [];
}

function binanceCandleBaseUrls(market: string) {
  if (market === "BINANCE_SPOT") {
    return [
      "https://data-api.binance.vision",
      "https://api1.binance.com",
      "https://api2.binance.com",
      "https://api3.binance.com",
      "https://api.binance.com",
      "https://www.binance.com"
    ];
  }
  if (market === "BINANCE_FUTURES") return ["https://fapi.binance.com", "https://www.binance.com"];
  return [];
}

function toExchangeSymbol(symbol: string) {
  return symbol.replace("/", "").toUpperCase();
}

function fromExchangeSymbol(symbol: string) {
  return symbol.endsWith("USDT") ? `${symbol.slice(0, -4)}/USDT` : symbol;
}

function isUsdtTickerSymbol(symbol: string) {
  return /^[A-Z0-9]+USDT$/.test(symbol);
}

function binanceInterval(timeframe: string) {
  const map: Record<string, string> = { "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "12h": "12h", "1d": "1d", "24h": "1d" };
  return map[timeframe] || "5";
}

function binanceWindowSize(range: string) {
  const map: Record<string, string> = { "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "2h": "2h", "6h": "6h", "12h": "12h" };
  return map[range] || null;
}

async function cached<T>(key: string, ttlMs: number, load: () => Promise<T>): Promise<T> {
  const hit = exchangeCache.get(key);
  if (hit && hit.expiresAt > Date.now()) return hit.value as T;
  const value = await load();
  exchangeCache.set(key, { expiresAt: Date.now() + ttlMs, value });
  return value;
}

async function fetchBinance<T>(baseUrls: string[], path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) query.set(key, String(value));
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  let lastError: unknown = null;
  for (const baseUrl of baseUrls) {
    try {
      const response = await fetch(`${baseUrl}${path}${suffix}`, {
        headers: { accept: "application/json", "user-agent": "crypto-screener/1.0" }
      });
      if (!response.ok) {
        lastError = new Error(`Binance HTTP ${response.status}`);
        continue;
      }
      return (await response.json()) as T;
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Binance request failed");
}

async function getBinanceTickers(market: string) {
  const baseUrls = binanceBaseUrls(market);
  if (!baseUrls.length) return null;
  const path = market === "BINANCE_FUTURES" ? "/fapi/v1/ticker/24hr" : "/api/v3/ticker/24hr";
  try {
    return await cached(`binance:tickers:${market}`, 5_000, () => fetchBinance<any[]>(baseUrls, path));
  } catch {
    const pricePath = market === "BINANCE_FUTURES" ? "/fapi/v1/ticker/price" : "/api/v3/ticker/price";
    return cached(`binance:prices:${market}`, 5_000, async () => {
      const prices = await fetchBinance<any[]>(baseUrls, pricePath);
      return prices.map((item) => ({
        symbol: item.symbol,
        lastPrice: item.price,
        quoteVolume: 0,
        volume: 0,
        count: 0,
        priceChangePercent: 0
      }));
    }).catch(() => null);
  }
}

async function getBinanceExchangeSymbols(market: string) {
  const baseUrls = binanceBaseUrls(market);
  if (!baseUrls.length) return null;
  if (market === "BINANCE_SPOT") {
    const products = await cached(`binance:products:${market}`, 60_000, async () => {
      const payload = await fetchBinance<{ data?: any[] }>(["https://www.binance.com"], "/bapi/asset/v2/public/asset-service/product/get-products", { includeEtf: "true" });
      return (payload.data || [])
        .filter((item) => isUsdtTickerSymbol(String(item.s || "")))
        .filter((item) => !item.st || item.st === "TRADING")
        .map((item) => {
          const lastPrice = Number(item.c || 0);
          const openPrice = Number(item.o || 0);
          return {
            symbol: item.s,
            lastPrice,
            quoteVolume: Number(item.qv || 0),
            volume: Number(item.v || 0),
            count: 0,
            priceChangePercent: openPrice ? ((lastPrice - openPrice) / openPrice) * 100 : 0
          };
        });
    }).catch(() => null);
    if (products?.length) return products;
  }
  const path = market === "BINANCE_FUTURES" ? "/fapi/v1/exchangeInfo" : "/api/v3/exchangeInfo";
  return cached(`binance:exchange-info:${market}`, 60_000, async () => {
    const info = await fetchBinance<{ symbols?: any[] }>(baseUrls, path);
    return (info.symbols || [])
      .filter((item) => isUsdtTickerSymbol(String(item.symbol || "")))
      .filter((item) => !item.status || item.status === "TRADING")
      .map((item) => ({
        symbol: item.symbol,
        lastPrice: 0,
        quoteVolume: 0,
        volume: 0,
        count: 0,
        priceChangePercent: 0
      }));
  }).catch(() => null);
}

async function getBinanceRollingTickers(market: string, symbols: string[], range: string) {
  const windowSize = binanceWindowSize(range);
  if (market !== "BINANCE_SPOT" || !windowSize || !symbols.length) return null;
  const baseUrls = ["https://data-api.binance.vision", "https://api.binance.com"];
  const chunks: string[][] = [];
  for (let i = 0; i < symbols.length; i += 100) {
    chunks.push(symbols.slice(i, i + 100));
  }

  const results = await Promise.all(
    chunks.map((chunk) =>
      cached(`binance:rolling:${market}:${windowSize}:${chunk.join(",")}:${Math.floor(Date.now() / 5_000)}`, 4_500, () =>
        fetchBinance<any[]>(baseUrls, "/api/v3/ticker", { windowSize, symbols: JSON.stringify(chunk) })
      ).catch(() => null)
    )
  );
  const tickers = results.flatMap((items) => items || []);
  return tickers.length ? tickers : null;
}

async function getBinanceCandles(symbol: string, market: string, timeframe: string, limit = 180): Promise<Candle[] | null> {
  const baseUrls = binanceCandleBaseUrls(market);
  if (!baseUrls.length) return null;
  const exchangeSymbol = toExchangeSymbol(symbol);
  const interval = binanceInterval(timeframe);
  const safeLimit = Math.max(1, Math.min(1000, limit));
  const path = market === "BINANCE_FUTURES" ? "/fapi/v1/klines" : "/api/v3/klines";
  const result = await cached(`binance:kline:${market}:${exchangeSymbol}:${interval}:${safeLimit}:${Math.floor(Date.now() / 5_000)}`, 4_500, () =>
    fetchBinance<any[][]>(baseUrls, path, { symbol: exchangeSymbol, interval, limit: safeLimit })
  ).catch(() => null);
  if (!result) return null;
  return result
    .map((item) => ({
      ts: new Date(Number(item[0])).toISOString(),
      open: Number(item[1]),
      high: Number(item[2]),
      low: Number(item[3]),
      close: Number(item[4]),
      volume: Number(item[5]),
      trades: 0
    }))
    .sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
}

async function binanceRows(state: AppState, market: string, range = "24h"): Promise<ScreenerRow[] | null> {
  const tickers = (await getBinanceTickers(market)) || (await getBinanceExchangeSymbols(market));
  if (!tickers) return null;
  const watch = new Set(state.watchlist.map((w) => `${w.symbol}:${w.market}`));
  const alerts = new Set(state.alerts.flatMap((a) => a.symbols.map((s) => `${s}:${a.market}`)));
  const rankedTickers = tickers
    .filter((item) => isUsdtTickerSymbol(String(item.symbol || "")))
    .sort((a, b) => Number(b.quoteVolume || 0) - Number(a.quoteVolume || 0));
  const rollingTickers = await getBinanceRollingTickers(market, rankedTickers.map((ticker) => String(ticker.symbol)), range);
  const rollingBySymbol = new Map((rollingTickers || []).map((ticker) => [String(ticker.symbol), ticker]));
  const rows = rankedTickers.map((ticker) => {
      const exchangeSymbol = String(ticker.symbol);
      const rollingTicker = rollingBySymbol.get(exchangeSymbol);
      const symbol = fromExchangeSymbol(exchangeSymbol);
      const price = Number(ticker.lastPrice || 0);
      const quoteVolume24h = Number(ticker.quoteVolume || 0);
      const baseVolume24h = Number(ticker.volume || 0);
      const trades24h = Number(ticker.count || 0);
      const priceChange24h = Number(ticker.priceChangePercent || 0);
      const rangePriceChange = Number(rollingTicker?.priceChangePercent || 0);
      const rowBase = {
        symbol,
        market,
        exchange: "BINANCE",
        price,
        priceChange1m: range === "1m" ? rangePriceChange : 0,
        priceChange3m: range === "3m" ? rangePriceChange : 0,
        priceChange5m: range === "5m" ? rangePriceChange : 0,
        priceChange15m: range === "15m" ? rangePriceChange : 0,
        priceChange30m: range === "30m" ? rangePriceChange : 0,
        priceChange1h: range === "1h" ? rangePriceChange : 0,
        priceChange2h: range === "2h" ? rangePriceChange : 0,
        priceChange6h: range === "6h" ? rangePriceChange : priceChange24h,
        priceChange12h: range === "12h" ? rangePriceChange : priceChange24h,
        priceChange24h,
        volumeSum1m: quoteVolume24h / 1440,
        volumeSum5m: quoteVolume24h / 288,
        volumeSum1h: quoteVolume24h / 24,
        volumeSum24h: quoteVolume24h,
        tradesSum1m: 0,
        tradesSum5m: 0,
        tradesSum1h: 0,
        tradesSum24h: trades24h || baseVolume24h,
        natr5_14: 0,
        volatility: Math.abs(priceChange24h),
        fundingRate: null,
        openInterest: null,
        hasAlert: alerts.has(`${symbol}:${market}`),
        inWatchlist: watch.has(`${symbol}:${market}`),
        active: true
      };
      return { ...rowBase, formation: null };
    });
  return rows.filter((row): row is ScreenerRow => Boolean(row));
}

async function routeApi(request: Request, url: URL, env: Env, state: AppState) {
  const method = request.method;
  const path = url.pathname;

  if (method === "GET" && path === "/api/markets") {
    return json({ markets: liveMarkets.map((market) => ({ symbol: market, market, exchange: "BINANCE", active: true, base: null, quote: null })) });
  }

  if (method === "GET" && path === "/api/screener/settings") {
    return json(state.currentSettings || defaultWorkspaces()[0]);
  }

  if (method === "PUT" && path === "/api/screener/settings") {
    return parseBody<any>(request).then(async (payload) => {
      state.currentSettings = payload;
      await saveState(env, state);
      return json(payload);
    });
  }

  if (method === "GET" && path === "/api/workspaces") {
    return json({ workspaces: state.workspaces });
  }

  if (method === "POST" && path === "/api/workspaces") {
    return parseBody<Workspace>(request).then(async (workspace) => {
      const idx = state.workspaces.findIndex((item) => item.id === workspace.id);
      if (idx >= 0) state.workspaces[idx] = workspace;
      else state.workspaces.push(workspace);
      await saveState(env, state);
      return json(workspace);
    });
  }

  if (method === "PUT" && path.startsWith("/api/workspaces/")) {
    return parseBody<Workspace>(request).then(async (workspace) => {
      const id = decodeURIComponent(path.split("/").pop() || "");
      const idx = state.workspaces.findIndex((item) => item.id === id);
      if (idx >= 0) state.workspaces[idx] = workspace;
      else state.workspaces.push(workspace);
      await saveState(env, state);
      return json(workspace);
    });
  }

  if (method === "DELETE" && path.startsWith("/api/workspaces/")) {
    const id = decodeURIComponent(path.split("/").pop() || "");
    state.workspaces = state.workspaces.filter((item) => item.id !== id);
    return saveState(env, state).then(() => json({ ok: true }));
  }

  if (method === "GET" && path === "/api/watchlist") {
    return json({ items: state.watchlist });
  }

  if (method === "PUT" && path === "/api/watchlist") {
    return parseBody<any[]>(request).then(async (items) => {
      state.watchlist = items;
      await saveState(env, state);
      return json({ items });
    });
  }

  if (method === "GET" && path === "/api/alerts") {
    return json({ items: state.alerts });
  }

  if (method === "POST" && path === "/api/alerts") {
    return parseBody<Alert>(request).then(async (alert) => {
      const idx = state.alerts.findIndex((item) => item.id === alert.id);
      if (idx >= 0) state.alerts[idx] = alert;
      else state.alerts.push(alert);
      await saveState(env, state);
      return json(alert);
    });
  }

  if (method === "PUT" && path.startsWith("/api/alerts/")) {
    return parseBody<Alert>(request).then(async (alert) => {
      const id = decodeURIComponent(path.split("/").pop() || "");
      const idx = state.alerts.findIndex((item) => item.id === id);
      if (idx >= 0) state.alerts[idx] = alert;
      else state.alerts.push(alert);
      await saveState(env, state);
      return json(alert);
    });
  }

  if (method === "DELETE" && path.startsWith("/api/alerts/")) {
    const id = decodeURIComponent(path.split("/").pop() || "");
    state.alerts = state.alerts.filter((item) => item.id !== id);
    return saveState(env, state).then(() => json({ ok: true }));
  }

  if (method === "GET" && path === "/api/chart/candles") {
    const symbol = url.searchParams.get("symbol") || "BTC/USDT";
    const market = url.searchParams.get("market") || "BINANCE_SPOT";
    const timeframe = url.searchParams.get("timeframe") || "5m";
    const limit = Number(url.searchParams.get("limit") || "180");
    const binanceCandles = await getBinanceCandles(symbol, market, timeframe, limit);
    if (binanceCandles) {
      return json({ symbol, market, exchange: "BINANCE", timeframe, candles: binanceCandles });
    }
    if (liveMarkets.includes(market as (typeof liveMarkets)[number])) {
      return json({ symbol, market, exchange: "BINANCE", timeframe, candles: [], error: "Binance candles unavailable" });
    }
    return json({ symbol, market, exchange: market.split("_")[0], timeframe, candles: generateCandles(symbol, market, limit, timeframe) });
  }

  if (method === "GET" && path === "/api/orderbook/densities") {
    const symbol = url.searchParams.get("symbol") || "BTC/USDT";
    const market = url.searchParams.get("market") || "BINANCE_SPOT";
    const candles = await getBinanceCandles(symbol, market, "5m", 60);
    if (!candles?.length && liveMarkets.includes(market as (typeof liveMarkets)[number])) {
      return json({ symbol, market, exchange: "BINANCE", densities: [] });
    }
    const sourceCandles = candles || generateCandles(symbol, market, 60, "5m");
    const price = sourceCandles[sourceCandles.length - 1].close;
    return json({ symbol, market, exchange: "BINANCE", densities: detectDensities(price, symbol, market, "BINANCE") });
  }

  if (method === "GET" && path === "/api/screener/data") {
    const requestedMarket = url.searchParams.get("market") || state.currentSettings?.market || "BINANCE_SPOT";
    const requestedRange = url.searchParams.get("range") || state.currentSettings?.sortingTypeRange || "24h";
    const selectedMarket = liveMarkets.includes(requestedMarket as (typeof liveMarkets)[number]) ? requestedMarket : "BINANCE_SPOT";
    const liveRows = await binanceRows(state, selectedMarket, requestedRange);
    const sourceRows = liveRows || baseRows(state, selectedMarket);
    const rows = sortRows(applyFilters(sourceRows, state.currentSettings?.filters || defaultWorkspaces()[0].filters), state.currentSettings?.sortingType || "top_gainers", requestedRange);
    return json({ rows, generatedAt: nowIso() });
  }

  if (method === "GET" && path === "/api/formations") {
    const rows = baseRows(state).filter((row) => row.formation);
    return json({ formations: rows.map((row) => row.formation) });
  }

  if (method === "POST" && path === "/api/formations/rescan") {
    const rows = baseRows(state).filter((row) => row.formation);
    return json({ formations: rows.map((row) => row.formation) });
  }

  if (method === "POST" && path.startsWith("/api/formations/") && path.endsWith("/ai-analysis")) {
    return parseBody<any>(request).then((payload) => {
      const key = `${url.searchParams.get("mode") || "quick"}:${JSON.stringify(payload)}`;
      const cached = state.aiCache[key];
      if (cached && new Date(cached.expiresAt).getTime() > Date.now()) {
        return json(cached.value);
      }
      const result = aiLocal(payload);
      state.aiCache[key] = { value: result, expiresAt: new Date(Date.now() + 15 * 60 * 1000).toISOString() };
      return saveState(env, state).then(() => json(result));
    });
  }

  if (method === "POST" && path === "/api/formations/batch-ai-analysis") {
    return parseBody<any[]>(request).then(async (payloads) => json(payloads.map((payload) => aiLocal(payload))));
  }

  return null;
}

export default {
  async fetch(request: Request, env: Env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return withCors(new Response(null, { status: 204 }));
    }

    if (url.pathname === "/ws") {
      if (request.headers.get("upgrade") !== "websocket") {
        return new Response("Upgrade required", { status: 426 });
      }
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      server.accept();
      server.send(JSON.stringify({ topic: "screener.update", payload: { ok: true }, ts: nowIso() }));
      return new Response(null, { status: 101, webSocket: client });
    }

    if (url.pathname.startsWith("/api/")) {
      const state = await loadState(env);
      const response = await routeApi(request, url, env, state);
      return withCors(response || new Response("Not found", { status: 404 }));
    }

    const assetResponse = await env.ASSETS.fetch(request);
    if (assetResponse.status !== 404) {
      return assetResponse;
    }
    const fallback = new URL("/index.html", url);
    return env.ASSETS.fetch(new Request(fallback, request));
  }
};
