import type {
  AiFormationAnalysis,
  AiFormationInput,
  Alert,
  Candle,
  DensitySignal,
  MarketSymbol,
  ScreenerFilters,
  ScreenerSettings,
  ScreenerRow,
  Workspace,
  WatchlistEntry
} from "@/lib/types";

function resolveBaseUrl() {
  const configured = typeof window === "undefined" && typeof process !== "undefined" ? process.env.NEXT_PUBLIC_API_BASE_URL : undefined;
  if (configured) return configured;
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    if ((host === "localhost" || host === "127.0.0.1") && window.location.port !== "8787") {
      return "http://127.0.0.1:8000";
    }
  }
  return "";
}

const browserScreenerCache = new Map<string, { expiresAt: number; value: { rows: ScreenerRow[]; generatedAt: string } }>();
const browserCandleCache = new Map<string, { expiresAt: number; value: { candles: Candle[] } }>();
const MAX_ACTIVE_CANDLE_REQUESTS = 6;
const CANDLE_REQUEST_STAGGER_MS = 60;
let activeCandleRequests = 0;
const pendingCandleRequests: Array<() => void> = [];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${resolveBaseUrl()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    },
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function isUsdtSymbol(symbol: string) {
  return /^[A-Z0-9]+USDT$/.test(symbol);
}

function fromExchangeSymbol(symbol: string) {
  return symbol.endsWith("USDT") ? `${symbol.slice(0, -4)}/USDT` : symbol;
}

function windowSizeForRange(range?: string) {
  const map: Record<string, string> = { "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "2h": "2h", "6h": "6h", "12h": "12h" };
  return range ? map[range] || null : null;
}

function changePatch(range: string | undefined, value: number) {
  return {
    priceChange1m: range === "1m" ? value : 0,
    priceChange3m: range === "3m" ? value : 0,
    priceChange5m: range === "5m" ? value : 0,
    priceChange15m: range === "15m" ? value : 0,
    priceChange30m: range === "30m" ? value : 0,
    priceChange1h: range === "1h" ? value : 0,
    priceChange2h: range === "2h" ? value : 0,
    priceChange6h: range === "6h" ? value : 0,
    priceChange12h: range === "12h" ? value : 0
  };
}

async function fetchJsonWithFallback<T>(urls: string[], timeoutMs = 8_000) {
  let lastError: unknown = null;
  for (const url of urls) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { cache: "no-store", headers: { accept: "application/json" }, signal: controller.signal });
      if (!response.ok) {
        lastError = new Error(`Binance failed: ${response.status}`);
        continue;
      }
      return (await response.json()) as T;
    } catch (error) {
      lastError = error;
    } finally {
      window.clearTimeout(timeout);
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Binance request failed");
}

function enqueueCandleRequest<T>(load: () => Promise<T>) {
  return new Promise<T>((resolve, reject) => {
    const run = () => {
      window.setTimeout(() => {
        load()
          .then(resolve, reject)
          .finally(() => {
            activeCandleRequests -= 1;
            pumpCandleQueue();
          });
      }, CANDLE_REQUEST_STAGGER_MS);
    };
    pendingCandleRequests.push(run);
    pumpCandleQueue();
  });
}

function pumpCandleQueue() {
  while (activeCandleRequests < MAX_ACTIVE_CANDLE_REQUESTS && pendingCandleRequests.length) {
    const next = pendingCandleRequests.shift();
    if (!next) return;
    activeCandleRequests += 1;
    next();
  }
}

async function getBrowserBinanceTickers(market: string) {
  if (market === "BINANCE_FUTURES") {
    return fetchJsonWithFallback<any[]>(["https://fapi.binance.com/fapi/v1/ticker/24hr"]);
  }

  try {
    const products = await fetchJsonWithFallback<{ data?: any[] }>([
      "https://www.binance.com/bapi/asset/v2/public/asset-service/product/get-products?includeEtf=true",
      "https://www.binance.com/bapi/asset/v1/public/asset-service/product/get-products?includeEtf=true"
    ]);
    return (products.data || []).map((item) => {
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
  } catch {
    return fetchJsonWithFallback<any[]>([
      "https://api.binance.com/api/v3/ticker/24hr",
      "https://data-api.binance.vision/api/v3/ticker/24hr"
    ]);
  }
}

async function getBrowserBinanceRollingTickers(symbols: string[], range?: string) {
  const windowSize = windowSizeForRange(range);
  if (!windowSize || !symbols.length) return new Map<string, any>();
  const chunks: string[][] = [];
  for (let i = 0; i < symbols.length; i += 100) chunks.push(symbols.slice(i, i + 100));
  const results = await Promise.all(
    chunks.map((chunk) => {
      const params = new URLSearchParams({ windowSize, symbols: JSON.stringify(chunk) });
      return fetchJsonWithFallback<any[]>([
        `https://data-api.binance.vision/api/v3/ticker?${params.toString()}`,
        `https://api.binance.com/api/v3/ticker?${params.toString()}`
      ]).catch(() => []);
    })
  );
  return new Map(results.flat().map((ticker) => [String(ticker.symbol), ticker]));
}

async function getBrowserFuturesListingChanges(tickers: any[]) {
  const candidates = tickers
    .filter((ticker) => Number(ticker.firstId) <= 1 && Number(ticker.lastPrice) > 0 && Math.abs(Number(ticker.priceChangePercent || 0)) >= 50)
    .sort((a, b) => Math.abs(Number(b.priceChangePercent || 0)) - Math.abs(Number(a.priceChangePercent || 0)))
    .slice(0, 24);
  if (!candidates.length) return new Map<string, number>();

  const entries = await Promise.all(
    candidates.map(async (ticker) => {
      const symbol = String(ticker.symbol || "");
      const params = new URLSearchParams({ symbol, interval: "5m", limit: "288" });
      const candles = await fetchJsonWithFallback<unknown[][]>([`https://fapi.binance.com/fapi/v1/klines?${params.toString()}`], 10_000).catch(() => []);
      if (candles.length < 12) return null;
      const baseCandle = candles[Math.min(9, candles.length - 2)];
      const base = Number(baseCandle?.[1] || 0);
      const last = Number(ticker.lastPrice || 0);
      if (!base || !last) return null;
      return [symbol, ((last - base) / base) * 100] as const;
    })
  );

  return new Map(entries.filter((entry): entry is readonly [string, number] => Boolean(entry)));
}

async function getBrowserScreenerData(market: string, range?: string) {
  const cacheKey = `${market}:${range || "24h"}`;
  const cached = browserScreenerCache.get(cacheKey);
  if (cached && cached.expiresAt > Date.now()) return cached.value;

  const tickers = (await getBrowserBinanceTickers(market))
    .filter((item) => isUsdtSymbol(String(item.symbol || "")))
    .sort((a, b) => Number(b.quoteVolume || 0) - Number(a.quoteVolume || 0));
  const rollingBySymbol = market === "BINANCE_SPOT" && range !== "24h" ? await getBrowserBinanceRollingTickers(tickers.map((ticker) => String(ticker.symbol)), range) : new Map<string, any>();
  const listingChangeBySymbol = market === "BINANCE_FUTURES" ? await getBrowserFuturesListingChanges(tickers) : new Map<string, number>();
  const rows: ScreenerRow[] = tickers.map((ticker) => {
    const exchangeSymbol = String(ticker.symbol);
    const rollingTicker = rollingBySymbol.get(exchangeSymbol);
    const priceChange24h = listingChangeBySymbol.get(exchangeSymbol) ?? Number(ticker.priceChangePercent || 0);
    const rangePriceChange = Number(rollingTicker?.priceChangePercent || 0);
    const quoteVolume24h = Number(ticker.quoteVolume || 0);
    const baseVolume24h = Number(ticker.volume || 0);
    return {
      symbol: fromExchangeSymbol(exchangeSymbol),
      market,
      exchange: "BINANCE",
      price: Number(ticker.lastPrice || 0),
      ...changePatch(range, rangePriceChange),
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
      tradesSum24h: Number(ticker.count || 0) || baseVolume24h,
      natr5_14: 0,
      volatility: Math.abs(priceChange24h),
      fundingRate: null,
      openInterest: null,
      hasAlert: false,
      inWatchlist: false,
      active: true,
      formation: null
    };
  });
  const value = { rows, generatedAt: new Date().toISOString() };
  browserScreenerCache.set(cacheKey, { expiresAt: Date.now() + (range && range !== "24h" ? 30_000 : 15_000), value });
  return value;
}

export async function getMarkets() {
  return request<{ markets: MarketSymbol[] }>("/api/markets");
}

export async function getScreenerData(market?: string, range?: string) {
  if (typeof window !== "undefined" && market?.startsWith("BINANCE_")) {
    return getBrowserScreenerData(market, range);
  }
  const params = new URLSearchParams();
  if (market) params.set("market", market);
  if (range) params.set("range", range);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<{ rows: ScreenerRow[]; generatedAt: string }>(`/api/screener/data${suffix}`);
}

export async function getScreenerSettings() {
  return request<ScreenerSettings>("/api/screener/settings");
}

export async function getWorkspaces() {
  return request<{ workspaces: Workspace[] }>("/api/workspaces");
}

export async function putWorkspace(workspace: Workspace) {
  return request<Workspace>(`/api/workspaces/${workspace.id}`, {
    method: "PUT",
    body: JSON.stringify(workspace)
  });
}

export async function postWorkspace(workspace: Workspace) {
  return request<Workspace>("/api/workspaces", {
    method: "POST",
    body: JSON.stringify(workspace)
  });
}

export async function deleteWorkspace(id: string) {
  return request<{ ok: boolean }>(`/api/workspaces/${id}`, {
    method: "DELETE"
  });
}

export async function getChartCandles(symbol: string, market: string, timeframe: string, limit = 120) {
  if (typeof window !== "undefined" && market.startsWith("BINANCE_")) {
    const cacheKey = `${market}:${symbol}:${timeframe}:${limit}`;
    const cached = browserCandleCache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now()) return cached.value;

    const exchangeSymbol = symbol.replace("/", "").toUpperCase();
    const intervalMap: Record<string, string> = {
      "1m": "1m",
      "3m": "3m",
      "5m": "5m",
      "15m": "15m",
      "30m": "30m",
      "1h": "1h",
      "2h": "2h",
      "4h": "4h",
      "6h": "6h",
      "12h": "12h",
      "1d": "1d",
      "24h": "1d"
    };
    const params = new URLSearchParams({
      symbol: exchangeSymbol,
      interval: intervalMap[timeframe] || "5m",
      limit: String(Math.max(1, Math.min(1000, limit)))
    });
    const path = params.toString();
    const candleTimeoutMs = market === "BINANCE_FUTURES" ? 10_000 : 4_000;
    const urls =
      market === "BINANCE_FUTURES"
        ? [`https://www.binance.com/fapi/v1/klines?${path}`, `https://fapi.binance.com/fapi/v1/klines?${path}`]
        : [
            `https://www.binance.com/api/v3/uiKlines?${path}`,
            `https://www.binance.com/api/v3/klines?${path}`,
            `https://data-api.binance.vision/api/v3/uiKlines?${path}`,
            `https://data-api.binance.vision/api/v3/klines?${path}`
          ];

    const items = await enqueueCandleRequest(() => fetchJsonWithFallback<unknown[][]>(urls, candleTimeoutMs)).catch(async () => {
      if (market === "BINANCE_SPOT") {
        const futuresUrls = [`https://www.binance.com/fapi/v1/klines?${path}`, `https://fapi.binance.com/fapi/v1/klines?${path}`];
        const futuresItems = await enqueueCandleRequest(() => fetchJsonWithFallback<unknown[][]>(futuresUrls, 10_000)).catch(() => null);
        if (futuresItems?.length) return futuresItems;
      }
      const fallback = await request<{ candles: Candle[] }>(`/api/chart/candles?${new URLSearchParams({ symbol, market, timeframe, limit: String(limit) }).toString()}`);
      return fallback.candles.map((candle) => [new Date(candle.ts).getTime(), candle.open, candle.high, candle.low, candle.close, candle.volume, 0, 0, candle.trades || 0]);
    });
    const value = {
      candles: items.map((item) => ({
        ts: new Date(Number(item[0])).toISOString(),
        open: Number(item[1]),
        high: Number(item[2]),
        low: Number(item[3]),
        close: Number(item[4]),
        volume: Number(item[5]),
        trades: Number(item[8] || 0)
      }))
    };
    browserCandleCache.set(cacheKey, { expiresAt: Date.now() + 60_000, value });
    return value;
  }

  const params = new URLSearchParams({ symbol, market, timeframe, limit: String(limit) });
  return request<{ candles: Candle[] }>(`/api/chart/candles?${params.toString()}`);
}

export async function getOrderbookDensities(symbol: string, market: string) {
  const params = new URLSearchParams({ symbol, market });
  return request<{ densities: DensitySignal[] }>(`/api/orderbook/densities?${params.toString()}`);
}

export async function getWatchlist() {
  return request<{ items: WatchlistEntry[] }>("/api/watchlist");
}

export async function putWatchlist(items: WatchlistEntry[]) {
  return request<{ items: WatchlistEntry[] }>("/api/watchlist", {
    method: "PUT",
    body: JSON.stringify(items)
  });
}

export async function getAlerts() {
  return request<{ items: Alert[] }>("/api/alerts");
}

export async function postAlert(alert: Alert) {
  return request<Alert>("/api/alerts", {
    method: "POST",
    body: JSON.stringify(alert)
  });
}

export async function putAlert(alert: Alert) {
  return request<Alert>(`/api/alerts/${alert.id}`, {
    method: "PUT",
    body: JSON.stringify(alert)
  });
}

export async function deleteAlert(id: string) {
  return request<{ ok: boolean }>(`/api/alerts/${id}`, {
    method: "DELETE"
  });
}

export async function putScreenerSettings(payload: {
  workspaceId?: string | null;
  market?: string | null;
  sortingType: string;
  sortingTypeRange: string;
  filters: ScreenerFilters;
  chartSettings: unknown;
  formationSettings: unknown;
  densitySettings: unknown;
  horizontalLevelSettings: unknown;
  trendLevelSettings: unknown;
  selectedColumns: string[];
  blacklist: string[];
  excludedMarkets: string[];
}) {
  return request("/api/screener/settings", {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function rescanFormations() {
  return request("/api/formations/rescan", {
    method: "POST"
  });
}

export async function postFormationAiAnalysis(formationId: string, payload: AiFormationInput, mode: "quick" | "deep" = "quick") {
  const params = new URLSearchParams({ mode });
  return request<AiFormationAnalysis>(`/api/formations/${encodeURIComponent(formationId)}/ai-analysis?${params.toString()}`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}
