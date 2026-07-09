"use client";

import {
  AiFormationAnalysis,
  AiFormationInput,
  Alert,
  Candle,
  FormationSettings,
  FormationSignal,
  FormationType,
  Level,
  ScreenerRow,
  ScreenerSettings,
  WatchlistEntry,
  Workspace
} from "@/lib/types";
import {
  deleteAlert,
  deleteWorkspace,
  getAlerts,
  getChartCandles,
  getOrderbookDensities,
  getScreenerData,
  getScreenerSettings,
  getWatchlist,
  getWorkspaces,
  postAlert,
  postFormationAiAnalysis,
  putScreenerSettings,
  putWatchlist,
  putWorkspace,
  rescanFormations
} from "@/lib/api";
import { useUiStore } from "@/lib/store";
import { MiniChart } from "@/components/MiniChart";
import { resolveWsUrl } from "@/lib/runtime";
import {
  Activity,
  ArrowUpDown,
  Bell,
  Brain,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CirclePlus,
  Columns3,
  Filter,
  Layers3,
  Menu,
  Maximize2,
  Plus,
  RefreshCw,
  Save,
  Search,
  SlidersHorizontal,
  Star,
  Trash2,
  X
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

const DEFAULT_COLUMNS = [
  "symbol",
  "market",
  "exchange",
  "price",
  "priceChange24h",
  "volumeSum24h",
  "tradesSum24h",
  "natr5_14",
  "volatility",
  "formation",
  "hasAlert",
  "inWatchlist"
] as const;

type ColumnKey = (typeof DEFAULT_COLUMNS)[number];
type ModalType = null | "workspace" | "columns" | "formations" | "levels" | "densities" | "ai" | "alert";

const columnLabels: Record<ColumnKey, string> = {
  symbol: "Монета",
  market: "Рынок",
  exchange: "Биржа",
  price: "Цена",
  priceChange24h: "24h %",
  volumeSum24h: "Объем 24h",
  tradesSum24h: "Сделки 24h",
  natr5_14: "NATR",
  volatility: "Волатильность",
  formation: "Формация",
  hasAlert: "Алерт",
  inWatchlist: "Watchlist"
};

const marketOptions = [
  "BINANCE_SPOT",
  "BINANCE_FUTURES"
];

const sortLabels: Record<string, string> = {
  top_gainers: "Топ роста",
  top_losers: "Топ падения",
  volume: "Объем",
  trades: "Сделки",
  volatility: "Волатильность",
  natr: "NATR",
  alerts_first: "Сначала алерты",
  watchlist_first: "Сначала watchlist",
  formations_first: "Сначала формации"
};

const formationLabels: Record<string, string> = {
  None: "Нет",
  ActiveCoins: "Активные монеты",
  CoinsWithDensity: "Монеты с плотностью",
  HorizontalLevels: "Горизонтальные уровни",
  TrendLevels: "Трендовые уровни",
  HorizontalLevelWithLimitOrder: "Уровень + лимитка"
};

const workspaceTitleLabels: Record<string, string> = {
  "top-gainers": "Futures",
  trades: "Сделки",
  densities: "Плотности",
  levels: "Уровни",
  watchlist: "Watchlist"
};

function workspaceTitle(workspace?: Pick<Workspace, "id" | "title"> | null) {
  if (!workspace) return "Скринер";
  return workspaceTitleLabels[workspace.id] || workspace.title;
}

function cloneWorkspace(workspace: Workspace): Workspace {
  return JSON.parse(JSON.stringify(workspace));
}

function normalizeMarket(market?: string | null) {
  return market && marketOptions.includes(market) ? market : "BINANCE_FUTURES";
}

function getDefaultWorkspace(id = "custom-workspace"): Workspace {
  return {
    id,
    title: "Новый скринер",
    market: "BINANCE_FUTURES",
    sortingType: "top_gainers",
    sortingTypeRange: "24h",
    sortingTime: "manual",
    pinAlerts: false,
    gridLayout: { rows: 3, columns: 3 },
    filters: {
      onlyActive: false,
      onlyWatchlist: false,
      onlyAlerts: false,
      onlyFormations: false,
      blacklist: [],
      excludedMarkets: []
    },
    chartSettings: {
      timeframe: "5m",
      candleLimit: 400,
      rightOffset: 0,
      showVolume: true,
      showOrderBook: true,
      showLevels: true,
      showDensities: true
    },
    formationSettings: {
      formation: "None",
      showOnlyFormations: false,
      sortByFormations: false,
      sortByLevelFormations: false,
      formationLimitOrderLevelLocation: "none",
      formationLimitOrderLevelDistance: 0.5
    },
    densitySettings: {
      showLimitOrders: true,
      showDensitiesWidget: true,
      limitOrderFilter: 50000,
      limitOrderDistance: 1.5,
      limitOrderLife: 5,
      limitOrderCorrosionTime: 15,
      roundDensity: true
    },
    horizontalLevelSettings: {
      showHorizontalLevels: true,
      showDailyHighAndLow: true,
      horizontalLevelsPeriod: 200,
      horizontalLevelsTouches: 3,
      horizontalLevelsTouchesThreshold: 0.25,
      horizontalLevelsLivingTime: 60,
      horizontalLevelsTimeframes: ["5m", "15m", "1h"]
    },
    trendLevelSettings: {
      showTrendLevels: true,
      trendlinesSource: "high/low",
      trendlinesPeriod: 120
    },
    selectedColumns: [...DEFAULT_COLUMNS],
    blacklist: [],
    excludedMarkets: []
  };
}

function workspaceToSettings(workspace: Workspace): ScreenerSettings {
  return {
    workspaceId: workspace.id,
    market: workspace.market,
    sortingType: workspace.sortingType,
    sortingTypeRange: workspace.sortingTypeRange,
    filters: workspace.filters,
    chartSettings: workspace.chartSettings,
    formationSettings: workspace.formationSettings,
    densitySettings: workspace.densitySettings,
    horizontalLevelSettings: workspace.horizontalLevelSettings,
    trendLevelSettings: workspace.trendLevelSettings,
    selectedColumns: workspace.selectedColumns,
    blacklist: workspace.blacklist,
    excludedMarkets: workspace.excludedMarkets
  };
}

function formatNumber(value: number, digits = 2) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(value);
}

function formatPct(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value, 2)}%`;
}

function formatPrice(value: number) {
  if (value >= 1000) return formatNumber(value, 2);
  if (value >= 1) return formatNumber(value, 4);
  return value.toFixed(6);
}

function formatCompact(value: number) {
  return new Intl.NumberFormat("ru-RU", {
    notation: "compact",
    maximumFractionDigits: 1
  }).format(value);
}

function optionalNumber(value: string) {
  return value.trim() === "" || !Number.isFinite(Number(value)) ? null : Number(value);
}

function getChange(row: ScreenerRow, range: string) {
  if (range === "1m") return row.priceChange1m;
  if (range === "5m") return row.priceChange5m;
  if (range === "15m") return row.priceChange15m;
  if (range === "1h") return row.priceChange1h;
  return row.priceChange24h;
}

function metricForRange(row: ScreenerRow, metric: "volume" | "trades", range = "24h") {
  const key = range === "1m" || range === "5m" || range === "1h" ? range : "24h";
  return metric === "volume"
    ? row[`volumeSum${key}` as "volumeSum1m" | "volumeSum5m" | "volumeSum1h" | "volumeSum24h"]
    : row[`tradesSum${key}` as "tradesSum1m" | "tradesSum5m" | "tradesSum1h" | "tradesSum24h"];
}

function timeframeMinutes(timeframe: string) {
  const map: Record<string, number> = { "1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440 };
  return map[timeframe] || 5;
}

function rangeMinutes(range: string) {
  const map: Record<string, number> = { "1m": 1, "5m": 5, "15m": 15, "1h": 60, "24h": 1440 };
  return map[range] || null;
}

function calcCandleChange(candles: Candle[], range: string, timeframe: string) {
  const minutes = rangeMinutes(range);
  if (!minutes) return null;
  const bars = Math.max(1, Math.ceil(minutes / timeframeMinutes(timeframe)));
  if (candles.length < bars) return null;
  const window = candles.slice(-bars);
  const first = window.find((candle) => candle.open > 0);
  const last = window[window.length - 1];
  if (!first || !last || first.open <= 0) return null;
  return ((last.close - first.open) / first.open) * 100;
}

function calcCandleVolatility(candles: Candle[], timeframe = "5m") {
  // The reference screener uses the standard deviation of hourly returns over
  // completed 24-hour bars. Grouping fixed chunks accidentally included the
  // current incomplete hour and made values jump between refreshes.
  const candlesPerPeriod = Math.max(1, Math.round(60 / timeframeMinutes(timeframe)));
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

function toColumnValue(row: ScreenerRow, key: ColumnKey) {
  switch (key) {
    case "symbol":
      return row.symbol;
    case "market":
      return row.market;
    case "exchange":
      return row.exchange;
    case "price":
      return formatPrice(row.price);
    case "priceChange24h":
      return formatPct(row.priceChange24h);
    case "volumeSum24h":
      return formatCompact(row.volumeSum24h);
    case "tradesSum24h":
      return formatCompact(row.tradesSum24h);
    case "natr5_14":
      return `${formatNumber(row.natr5_14, 2)}%`;
    case "volatility":
      return formatNumber(row.volatility, 4);
    case "formation":
      return row.formation ? formationLabels[row.formation.type] || row.formation.type : "Нет";
    case "hasAlert":
      return row.hasAlert ? "Да" : "Нет";
    case "inWatchlist":
      return row.inWatchlist ? "Да" : "Нет";
    default:
      return "";
  }
}

function rowFormationTag(row: ScreenerRow) {
  if (!row.formation) {
    return <span className="muted">Нет формации</span>;
  }
  const state = row.formation.score >= 80 ? "good" : row.formation.score >= 55 ? "warn" : "bad";
  return (
    <span className="tag" data-state={state}>
      {formationLabels[row.formation.type] || row.formation.type} · {formatNumber(row.formation.score, 0)}
    </span>
  );
}

function IconButton({ label, onClick, children, disabled = false, active = false }: { label: string; onClick: () => void; children: ReactNode; disabled?: boolean; active?: boolean }) {
  return (
    <button className="icon-button" onClick={onClick} aria-label={label} title={label} disabled={disabled} data-active={active}>
      {children}
    </button>
  );
}

function ModalShell({
  title,
  onClose,
  children,
  footer
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="dialog-backdrop" onMouseDown={onClose}>
      <div className="dialog" onMouseDown={(event) => event.stopPropagation()}>
        <div className="dialog-head">
          <strong>{title}</strong>
          <button className="icon-button" onClick={onClose} aria-label="Закрыть">
            <X size={16} />
          </button>
        </div>
        <div className="dialog-body">{children}</div>
        {footer ? <div className="dialog-footer">{footer}</div> : null}
      </div>
    </div>
  );
}

function useNearViewport<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [nearViewport, setNearViewport] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || nearViewport) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setNearViewport(true);
          observer.disconnect();
        }
      },
      { rootMargin: "900px 0px" }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [nearViewport]);

  return { ref, nearViewport };
}

function LazyChartCard({
  row,
  activeRange,
  activeTimeframe,
  candleLimit,
  rightOffset,
  compact,
  selected,
  fullscreen = false,
  onSelect,
  onTimeframeChange,
  onFullscreen
}: {
  row: ScreenerRow;
  activeRange: string;
  activeTimeframe: string;
  candleLimit: number;
  rightOffset: number;
  compact: boolean;
  selected: boolean;
  fullscreen?: boolean;
  onSelect: () => void;
  onTimeframeChange: (timeframe: string) => void;
  onFullscreen: () => void;
}) {
  const { ref, nearViewport } = useNearViewport<HTMLDivElement>();
  const candlesQuery = useQuery({
    queryKey: ["candles", row.symbol, row.market, activeTimeframe],
    queryFn: async () => getChartCandles(row.symbol, row.market, activeTimeframe, candleLimit),
    enabled: nearViewport,
    staleTime: 3_000,
    refetchInterval: nearViewport ? 5_000 : false,
    refetchIntervalInBackground: false
  });
  const candles = ((candlesQuery.data as { candles?: Candle[] } | undefined)?.candles || []) as Candle[];
  const volatilityCandlesQuery = useQuery({
    queryKey: ["volatility-candles", row.symbol, row.market],
    queryFn: async () => getChartCandles(row.symbol, row.market, "5m", 288),
    enabled: nearViewport && activeTimeframe !== "5m",
    staleTime: 3_000,
    refetchInterval: nearViewport && activeTimeframe !== "5m" ? 5_000 : false,
    refetchIntervalInBackground: false
  });
  const volatilityCandles =
    activeTimeframe === "5m"
      ? candles
      : (((volatilityCandlesQuery.data as { candles?: Candle[] } | undefined)?.candles || []) as Candle[]);
  const hasCandles = candles.length > 1;
  const candleRangeChange = hasCandles ? calcCandleChange(candles, activeRange, activeTimeframe) : null;
  const overlayMetrics = {
    volume: row.volumeSum24h,
    change: candleRangeChange ?? getChange(row, activeRange),
    volatility: volatilityCandles.length > 1 ? calcCandleVolatility(volatilityCandles) : row.volatility,
    trades: row.tradesSum24h
  };

  return (
    <div
      ref={ref}
      className="chart-card"
      data-selected={selected}
      data-compact={compact}
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
    >
      <div className="chart-card-head">
        <div>
          <strong>{row.symbol}</strong>
          <span>{row.exchange}</span>
        </div>
        <div className="chart-card-timeframes" aria-label={`\u0422\u0430\u0439\u043c\u0444\u0440\u0435\u0439\u043c ${activeTimeframe}`}>
          {["1m", "5m", "15m", "1h", "4h", "1d"].map((timeframe) => (
            <button
              key={timeframe}
              type="button"
              data-active={timeframe === activeTimeframe}
              onClick={(event) => {
                event.stopPropagation();
                onTimeframeChange(timeframe);
              }}
            >
              {timeframe}
            </button>
          ))}
        </div>
        <div className="chart-icons">
          {row.inWatchlist ? <Star size={15} fill="currentColor" /> : null}
          {row.hasAlert ? <Bell size={15} /> : null}
          <button
            className="chart-fullscreen-button"
            type="button"
            aria-label={`Развернуть ${row.symbol} на весь экран`}
            title="На весь экран"
            onClick={(event) => {
              event.stopPropagation();
              onFullscreen();
            }}
          >
            <Maximize2 size={15} />
          </button>
        </div>
      </div>
      <div className="chart-card-body">
        <div className="metric-overlay-live">
          <span title="\u041e\u0431\u044a\u0435\u043c 24h">{"\u041e\u0431 (24h): "}<b>{formatCompact(overlayMetrics.volume)}</b></span>
          <span title="\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0435 \u0437\u0430 \u0432\u044b\u0431\u0440\u0430\u043d\u043d\u044b\u0439 \u0434\u0438\u0430\u043f\u0430\u0437\u043e\u043d">{"\u0418\u0437\u043c ("}{activeRange}{"): "}<b data-state={overlayMetrics.change >= 0 ? "good" : "bad"}>{formatPct(overlayMetrics.change)}</b></span>
          <span title="\u0412\u043e\u043b\u0430\u0442\u0438\u043b\u044c\u043d\u043e\u0441\u0442\u044c 24h">{"\u0412\u043e\u043b (24h): "}<b data-state={overlayMetrics.volatility >= 0 ? "good" : "bad"}>{formatPct(overlayMetrics.volatility)}</b></span>
          <span title="\u0421\u0434\u0435\u043b\u043a\u0438 24h">{"\u0421\u0434\u043b (24h): "}<b>{formatCompact(overlayMetrics.trades)}</b></span>
        </div>
        {nearViewport ? <MiniChart candles={candles} title={`${row.symbol} ${row.market}`} timeframe={activeTimeframe} rightOffset={rightOffset} enableDrawing={fullscreen} /> : <div className="mini-chart-placeholder" aria-hidden="true" />}
      </div>
    </div>
  );
}

export function ScreenerClient() {
  const queryClient = useQueryClient();
  const { selectedSymbol, selectedMarket, setSelectedSymbol } = useUiStore();
  const [modal, setModal] = useState<ModalType>(null);
  const [workspaceTab, setWorkspaceTab] = useState<"start" | "filters" | "sorting" | "chart">("start");
  const [isScreenerViewOpen, setIsScreenerViewOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>("");
  const [draftWorkspace, setDraftWorkspace] = useState<Workspace | null>(null);
  const [aiTarget, setAiTarget] = useState<ScreenerRow | null>(null);
  const [aiResult, setAiResult] = useState<AiFormationAnalysis | null>(null);
  const [notifications, setNotifications] = useState<{ id: string; text: string; count: number }[]>([]);
  const [liveScreenerData, setLiveScreenerData] = useState<{ rows: ScreenerRow[]; generatedAt: string } | null>(null);
  const [liveScreenerError, setLiveScreenerError] = useState("");
  const [chartPage, setChartPage] = useState(0);
  const [chartOrder, setChartOrder] = useState<string[]>([]);
  const [cardTimeframes, setCardTimeframes] = useState<Record<string, string>>({});
  const [isCompactChartLayout, setIsCompactChartLayout] = useState(false);
  const [isTimeframeMenuOpen, setIsTimeframeMenuOpen] = useState(false);
  const [fullscreenChart, setFullscreenChart] = useState<ScreenerRow | null>(null);
  const [alertDraft, setAlertDraft] = useState<Alert>({
    id: `alert-${Date.now()}`,
    userId: "local-user",
    active: true,
    type: "formationDetected",
    symbols: [],
    market: "BINANCE_SPOT",
    direction: "all",
    interval: "5m",
    threshold: 0,
    distance: 0,
    lifetime: 0,
    corrosionTime: 0,
    watchlistOnly: false,
    sound: "default",
    telegramNotification: false
  });

  const workspacesQuery = useQuery({ queryKey: ["workspaces"], queryFn: getWorkspaces });
  const settingsQuery = useQuery({ queryKey: ["screener-settings"], queryFn: getScreenerSettings });
  const screenerQuery = useQuery({
    queryKey: ["screener-data"],
    queryFn: () => getScreenerData(normalizeMarket(draftWorkspace?.market || settingsQuery.data?.market), "24h"),
    enabled: false,
    refetchInterval: 1000,
    refetchIntervalInBackground: true
  });
  const watchlistQuery = useQuery({
    queryKey: ["watchlist"],
    queryFn: getWatchlist,
    refetchInterval: 4000
  });
  const alertsQuery = useQuery({
    queryKey: ["alerts"],
    queryFn: getAlerts,
    refetchInterval: 4000
  });

  const saveWorkspaceMutation = useMutation({
    mutationFn: async (workspace: Workspace) => {
      await putWorkspace(workspace);
      await putScreenerSettings(workspaceToSettings(workspace));
      return workspace;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      await queryClient.invalidateQueries({ queryKey: ["screener-settings"] });
      await queryClient.invalidateQueries({ queryKey: ["screener-data"] });
    }
  });

  const watchlistMutation = useMutation({
    mutationFn: putWatchlist,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["watchlist"] });
      await queryClient.invalidateQueries({ queryKey: ["screener-data"] });
    }
  });

  const alertMutation = useMutation({
    mutationFn: postAlert,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["alerts"] });
      await queryClient.invalidateQueries({ queryKey: ["screener-data"] });
      setModal(null);
    }
  });

  const deleteAlertMutation = useMutation({
    mutationFn: deleteAlert,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["alerts"] });
      await queryClient.invalidateQueries({ queryKey: ["screener-data"] });
    }
  });

  const rescanMutation = useMutation({
    mutationFn: rescanFormations,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["screener-data"] });
      await queryClient.invalidateQueries({ queryKey: ["screener-settings"] });
    }
  });

  const aiMutation = useMutation({
    mutationFn: async ({ row, mode }: { row: ScreenerRow; mode: "quick" | "deep" }) => {
      const candlesPayload = await getChartCandles(row.symbol, row.market, draftWorkspace?.chartSettings.timeframe || "5m", 180);
      const densitiesPayload = await getOrderbookDensities(row.symbol, row.market);
      const baseFormation: FormationSignal =
        row.formation ??
        {
          type: "ActiveCoins",
          symbol: row.symbol,
          market: row.market,
          timeframe: draftWorkspace?.chartSettings.timeframe || "5m",
          direction: "neutral",
          score: 50,
          distancePct: 0,
          price: row.price,
          reason: "Формация передана из текущего скринера.",
          detectedAt: new Date().toISOString()
        };
      const horizontalLevels: Level[] = baseFormation.levelPrice
        ? [
            {
              symbol: row.symbol,
              market: row.market,
              exchange: row.exchange,
              type: "horizontal",
              price: baseFormation.levelPrice,
              timeframe: draftWorkspace?.chartSettings.timeframe || "5m",
              touches: 3,
              score: baseFormation.score,
              direction: baseFormation.direction,
              detectedAt: new Date().toISOString()
            }
          ]
        : [];
      const trendLevels: Level[] = baseFormation.levelPrice
        ? [
            {
              symbol: row.symbol,
              market: row.market,
              exchange: row.exchange,
              type: "trend",
              price: baseFormation.levelPrice,
              timeframe: draftWorkspace?.chartSettings.timeframe || "5m",
              touches: 3,
              score: baseFormation.score * 0.8,
              direction: baseFormation.direction,
              detectedAt: new Date().toISOString()
            }
          ]
        : [];
      const input: AiFormationInput = {
        symbol: row.symbol,
        market: row.market,
        timeframe: draftWorkspace?.chartSettings.timeframe || "5m",
        currentPrice: row.price,
        formation: baseFormation,
        candles: candlesPayload.candles,
        horizontalLevels,
        trendLevels,
        densities: densitiesPayload.densities,
        metrics: row
      };
      return postFormationAiAnalysis(`${row.symbol}:${row.market}`, input, mode);
    },
    onSuccess: (result) => {
      setAiResult(result);
    }
  });

  const activeWorkspaces = workspacesQuery.data?.workspaces || [];
  const settingsWorkspaceId = settingsQuery.data?.workspaceId || null;
  const watchlistItems = watchlistQuery.data?.items || [];
  const alerts = alertsQuery.data?.items || [];
  const requestMarket = normalizeMarket(draftWorkspace?.market || settingsQuery.data?.market);
  const requestRange = "24h";

  useEffect(() => {
    let cancelled = false;
    setLiveScreenerData(null);

    const loadScreenerData = async () => {
      try {
        const payload = await getScreenerData(requestMarket, requestRange);
        if (!cancelled) {
          setLiveScreenerData(payload);
          setLiveScreenerError("");
        }
      } catch (error) {
        if (!cancelled) {
          setLiveScreenerError(error instanceof Error ? error.message : "Ошибка API");
        }
      }
    };

    loadScreenerData();
    const timer = window.setInterval(loadScreenerData, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [requestMarket, requestRange]);

  useEffect(() => {
    if (selectedWorkspaceId || activeWorkspaces.length === 0 || !settingsQuery.data) {
      return;
    }
    const initialId = settingsWorkspaceId && activeWorkspaces.some((workspace) => workspace.id === settingsWorkspaceId) ? settingsWorkspaceId : activeWorkspaces[0].id;
    setSelectedWorkspaceId(initialId);
  }, [activeWorkspaces, selectedWorkspaceId, settingsQuery.data, settingsWorkspaceId]);

  useEffect(() => {
    if (!selectedWorkspaceId) {
      return;
    }
    const found = activeWorkspaces.find((workspace) => workspace.id === selectedWorkspaceId);
    if (found) {
      const next = cloneWorkspace(found);
      next.market = normalizeMarket(next.market);
      next.selectedColumns = next.selectedColumns.filter((column) => column !== "btcCorrelation");
      if (next.sortingType === "btc_correlation") next.sortingType = "top_gainers";
      setDraftWorkspace(next);
    } else if (!draftWorkspace && settingsQuery.data) {
      const fallback = getDefaultWorkspace(selectedWorkspaceId);
      fallback.market = normalizeMarket(settingsQuery.data.market);
      fallback.sortingType = settingsQuery.data.sortingType;
      fallback.sortingTypeRange = settingsQuery.data.sortingTypeRange;
      fallback.filters = settingsQuery.data.filters;
      fallback.chartSettings = settingsQuery.data.chartSettings;
      fallback.formationSettings = settingsQuery.data.formationSettings;
      fallback.densitySettings = settingsQuery.data.densitySettings;
      fallback.horizontalLevelSettings = settingsQuery.data.horizontalLevelSettings;
      fallback.trendLevelSettings = settingsQuery.data.trendLevelSettings;
      fallback.selectedColumns = settingsQuery.data.selectedColumns.filter((column) => column !== "btcCorrelation");
      fallback.blacklist = settingsQuery.data.blacklist;
      fallback.excludedMarkets = settingsQuery.data.excludedMarkets;
      setDraftWorkspace(fallback);
    }
  }, [activeWorkspaces, selectedWorkspaceId, settingsQuery.data]);

  const draftHash = useMemo(() => (draftWorkspace ? JSON.stringify(draftWorkspace) : ""), [draftWorkspace]);
  const lastSavedHashRef = useRef("");
  const initialisedDraftRef = useRef(false);

  useEffect(() => {
    if (!draftWorkspace) {
      return;
    }
    if (!initialisedDraftRef.current) {
      initialisedDraftRef.current = true;
      lastSavedHashRef.current = draftHash;
      return;
    }
    if (draftHash === lastSavedHashRef.current) {
      return;
    }
    const timer = window.setTimeout(() => {
      lastSavedHashRef.current = draftHash;
      saveWorkspaceMutation.mutate(draftWorkspace);
    }, 450);
    return () => window.clearTimeout(timer);
  }, [draftHash, draftWorkspace, saveWorkspaceMutation]);

  useEffect(() => {
    const socket = new WebSocket(resolveWsUrl());
    socket.onmessage = (event) => {
      queryClient.invalidateQueries({ queryKey: ["screener-data"] });
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      try {
        const parsed = JSON.parse(event.data);
        if (parsed.topic === "alert.triggered" && parsed.payload?.count) {
          const item = {
            id: `${parsed.topic}-${Date.now()}`,
            text: `Сработало алертов: ${parsed.payload.count}`,
            count: Number(parsed.payload.count || 0)
          };
          setNotifications((current) => [item, ...current].slice(0, 5));
          if (typeof Notification !== "undefined" && Notification.permission === "granted") {
            new Notification("Crypto Screener", { body: item.text });
          }
        }
      } catch {
        // Ignore malformed websocket messages.
      }
    };
    socket.onopen = () => {
      socket.send("ping");
    };
    return () => socket.close();
  }, [queryClient]);

  const rawRows = liveScreenerData?.rows || screenerQuery.data?.rows || [];
  const rows = useMemo(() => {
    const watch = new Set(watchlistItems.map((item) => `${item.symbol}:${item.market}`));
    const alertSymbols = new Set(alerts.flatMap((alert) => alert.symbols.map((symbol) => `${symbol}:${alert.market}`)));
    return rawRows.map((row) => ({
      ...row,
      inWatchlist: watch.has(`${row.symbol}:${row.market}`),
      hasAlert: alertSymbols.has(`${row.symbol}:${row.market}`)
    }));
  }, [alerts, rawRows, watchlistItems]);
  const filteredRows = useMemo(() => {
    const searchLower = search.trim().toLowerCase();
    const filters = draftWorkspace?.filters;
    const selectedMarketFilter = draftWorkspace?.market || "";
    const sortingType = draftWorkspace?.sortingType || "top_gainers";
    const sortingRange = draftWorkspace?.sortingTypeRange || "24h";
    const visible = rows.filter((row) => {
      if (selectedMarketFilter && row.market !== selectedMarketFilter) return false;
      if (searchLower) {
        const haystack = `${row.symbol} ${row.market} ${row.exchange} ${row.formation?.type || ""}`.toLowerCase();
        if (!haystack.includes(searchLower)) return false;
      }
      if (filters?.onlyActive && !row.active) return false;
      if (filters?.onlyWatchlist && !row.inWatchlist) return false;
      if (filters?.onlyAlerts && !row.hasAlert) return false;
      if ((filters?.onlyFormations || draftWorkspace?.formationSettings.showOnlyFormations) && !row.formation) return false;
      if (filters?.blacklist?.includes(row.symbol)) return false;
      if (filters?.excludedMarkets?.includes(row.market)) return false;
      const within = (value: number, from?: number | null, to?: number | null) => (from != null && value < from ? false : to != null && value > to ? false : true);
      if (!within(metricForRange(row, "volume", filters?.volumeRange), filters?.volumeFrom, filters?.volumeTo)) return false;
      if (!within(getChange(row, filters?.priceChangeRange || "24h"), filters?.priceChangeFrom, filters?.priceChangeTo)) return false;
      if (!within(metricForRange(row, "trades", filters?.tradesRange), filters?.tradesFrom, filters?.tradesTo)) return false;
      return true;
    });

    const sortRange = sortingRange === "24h" || visible.some((row) => getChange(row, sortingRange) !== 0) ? sortingRange : "24h";
    return [...visible].sort((a, b) => {
      if (draftWorkspace?.pinAlerts && a.hasAlert !== b.hasAlert) return Number(b.hasAlert) - Number(a.hasAlert);
      if (sortingType === "top_losers") return getChange(a, sortRange) - getChange(b, sortRange) || b.volumeSum24h - a.volumeSum24h;
      if (sortingType === "volume") return b.volumeSum24h - a.volumeSum24h;
      if (sortingType === "trades") return b.tradesSum24h - a.tradesSum24h;
      if (sortingType === "volatility") return b.volatility - a.volatility;
      if (sortingType === "natr") return b.natr5_14 - a.natr5_14;
      if (sortingType === "alerts_first") return Number(b.hasAlert) - Number(a.hasAlert);
      if (sortingType === "watchlist_first") return Number(b.inWatchlist) - Number(a.inWatchlist);
      if (sortingType === "formations_first") return Number(Boolean(b.formation)) - Number(Boolean(a.formation));
      return getChange(b, sortRange) - getChange(a, sortRange) || b.volumeSum24h - a.volumeSum24h;
    });
  }, [draftWorkspace, rows, search]);

  const chartOrderScope = useMemo(
    () =>
      JSON.stringify({
        workspace: selectedWorkspaceId,
        market: draftWorkspace?.market,
        sort: draftWorkspace?.sortingType,
        range: draftWorkspace?.sortingTypeRange,
        filters: draftWorkspace?.filters,
        formationsOnly: draftWorkspace?.formationSettings.showOnlyFormations,
        search
      }),
    [draftWorkspace?.filters, draftWorkspace?.formationSettings.showOnlyFormations, draftWorkspace?.market, draftWorkspace?.sortingType, draftWorkspace?.sortingTypeRange, search, selectedWorkspaceId]
  );

  // Live quotes update the existing cards in place. Their order is only replaced
  // when the user changes the sorting context or explicitly presses refresh.
  useEffect(() => {
    setChartOrder(filteredRows.map((row) => `${row.symbol}:${row.market}`));
    setChartPage(0);
  }, [chartOrderScope]);

  useEffect(() => {
    if (chartOrder.length || !filteredRows.length) return;
    setChartOrder(filteredRows.map((row) => `${row.symbol}:${row.market}`));
  }, [chartOrder.length, filteredRows]);

  const chartRows = useMemo(() => {
    const rowsByKey = new Map(filteredRows.map((row) => [`${row.symbol}:${row.market}`, row]));
    const orderedKeys = new Set(chartOrder);
    const retained = chartOrder.flatMap((key) => {
      const row = rowsByKey.get(key);
      return row ? [row] : [];
    });
    // New listings remain live, but are appended until the next explicit sort.
    return [...retained, ...filteredRows.filter((row) => !orderedKeys.has(`${row.symbol}:${row.market}`))];
  }, [chartOrder, filteredRows]);

  useEffect(() => {
    if (!filteredRows.length) {
      return;
    }
    const stillVisible = filteredRows.some((row) => row.symbol === selectedSymbol && row.market === selectedMarket);
    if (!selectedSymbol || !stillVisible) {
      setSelectedSymbol(filteredRows[0].symbol, filteredRows[0].market);
    }
  }, [filteredRows, selectedMarket, selectedSymbol, setSelectedSymbol]);

  const selectedRow = useMemo(() => {
    if (!filteredRows.length) return null;
    return filteredRows.find((row) => row.symbol === selectedSymbol && row.market === selectedMarket) || filteredRows[0];
  }, [filteredRows, selectedMarket, selectedSymbol]);

  const visibleColumns = useMemo(() => {
    const columns = draftWorkspace?.selectedColumns?.length ? draftWorkspace.selectedColumns : [...DEFAULT_COLUMNS];
    return columns.filter((column): column is ColumnKey => (DEFAULT_COLUMNS as readonly string[]).includes(column));
  }, [draftWorkspace?.selectedColumns]);

  const chartsPerPage = Math.max(1, (draftWorkspace?.gridLayout.rows || 3) * (draftWorkspace?.gridLayout.columns || 3));
  const chartPageCount = Math.max(1, Math.ceil(chartRows.length / chartsPerPage));
  const chartPageStart = chartPage * chartsPerPage;
  const chartPageRows = chartRows.slice(chartPageStart, chartPageStart + chartsPerPage);
  const chartPageFrom = chartRows.length ? chartPageStart + 1 : 0;
  const chartPageTo = Math.min(chartRows.length, chartPageStart + chartPageRows.length);
  const activeTimeframe = draftWorkspace?.chartSettings.timeframe || "5m";
  const candleLimit = Math.max(50, Math.min(1000, draftWorkspace?.chartSettings.candleLimit || 400));
  const rightOffset = Math.max(0, draftWorkspace?.chartSettings.rightOffset || 0);
  useEffect(() => {
    setChartPage(0);
  }, [draftWorkspace?.sortingType, requestMarket, requestRange, search, selectedWorkspaceId]);

  useEffect(() => {
    setChartPage((page) => Math.min(page, chartPageCount - 1));
  }, [chartPageCount]);

  useEffect(() => {
    if (!fullscreenChart) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullscreenChart(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [fullscreenChart]);

  const saveNow = () => {
    if (!draftWorkspace) return;
    lastSavedHashRef.current = draftHash;
    saveWorkspaceMutation.mutate(draftWorkspace);
  };

  const updateDraft = (updater: (workspace: Workspace) => Workspace) => {
    setDraftWorkspace((current) => (current ? updater(current) : current));
  };

  const toggleWatchlist = (row: ScreenerRow) => {
    const exists = watchlistItems.some((entry) => entry.symbol === row.symbol && entry.market === row.market);
    const next: WatchlistEntry[] = exists
      ? watchlistItems.filter((entry) => !(entry.symbol === row.symbol && entry.market === row.market))
      : [...watchlistItems, { symbol: row.symbol, market: row.market, exchange: row.exchange }];
    watchlistMutation.mutate(next);
  };

  const createQuickAlert = (row: ScreenerRow) => {
    alertMutation.mutate({
      ...alertDraft,
      id: `alert-${Date.now()}`,
      symbols: [row.symbol],
      market: row.market
    });
  };

  const currentWorkspaceTitle = workspaceTitle(draftWorkspace);
  const generatedAtSource = liveScreenerData?.generatedAt || screenerQuery.data?.generatedAt;
  const generatedAt = generatedAtSource ? new Date(generatedAtSource).toLocaleTimeString("ru-RU") : liveScreenerError || "нет данных";
  const activeSort = draftWorkspace?.sortingType || "top_gainers";
  const activeRange = "24h";
  const refreshChartOrder = () => {
    setChartOrder(filteredRows.map((row) => `${row.symbol}:${row.market}`));
    setChartPage(0);
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">CS</span>
          <strong>Crypto Screener</strong>
        </div>
        <nav className="main-nav" aria-label="Разделы">
          <button data-active="true">Скринер</button>
          <button>Монеты</button>
          <button>Карта плотностей</button>
          <button>Оповещения</button>
          <button>Формации</button>
          <button>Обновления</button>
        </nav>
        <div className="top-actions">
          <IconButton label="Пересканировать" onClick={() => rescanMutation.mutate()}>
            <RefreshCw size={18} />
          </IconButton>
          <button data-variant="primary" onClick={saveNow}>
            <Save size={16} /> Сохранить
          </button>
        </div>
      </header>

      <main className="content">
        <section className="chart-board">
          <div className="section-head">
            <div className="profile-tabs" aria-label="Торговые профили">
              {activeWorkspaces.map((workspace) => (
                <button
                  key={workspace.id}
                  data-active={workspace.id === selectedWorkspaceId}
                  onClick={() => {
                    setSelectedWorkspaceId(workspace.id);
                    initialisedDraftRef.current = false;
                    lastSavedHashRef.current = "";
                  }}
                  onDoubleClick={() => {
                    initialisedDraftRef.current = false;
                    lastSavedHashRef.current = "";
                    setSelectedWorkspaceId(workspace.id);
                    setDraftWorkspace(cloneWorkspace(workspace));
                    setWorkspaceTab("start");
                    setModal("workspace");
                  }}
                >
                  {workspaceTitle(workspace)}
                </button>
              ))}
              <IconButton
                label="Создать торговый профиль"
                onClick={() => {
                  const next = getDefaultWorkspace(`workspace-${Date.now()}`);
                  initialisedDraftRef.current = false;
                  lastSavedHashRef.current = "";
                  setSelectedWorkspaceId(next.id);
                  setDraftWorkspace(next);
                  setWorkspaceTab("start");
                  setModal("workspace");
                }}
              >
                <Plus size={20} />
              </IconButton>
            </div>
            <div className="chart-board-tools">
              <div className="chart-pager" aria-label="\u0413\u0440\u0443\u043f\u043f\u044b \u0433\u0440\u0430\u0444\u0438\u043a\u043e\u0432">
                <IconButton label="\u041f\u0440\u0435\u0434\u044b\u0434\u0443\u0449\u0438\u0435 12 \u0433\u0440\u0430\u0444\u0438\u043a\u043e\u0432" onClick={() => setChartPage((page) => Math.max(0, page - 1))} disabled={chartPage === 0}>
                  <ChevronLeft size={17} />
                </IconButton>
                <span className="chart-page-count">
                  {chartPageFrom}-{chartPageTo} / {filteredRows.length}
                </span>
                <IconButton label="\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0435 12 \u0433\u0440\u0430\u0444\u0438\u043a\u043e\u0432" onClick={() => setChartPage((page) => Math.min(chartPageCount - 1, page + 1))} disabled={chartPage >= chartPageCount - 1}>
                  <ChevronRight size={17} />
                </IconButton>
              </div>
              <div className="timeframe-menu">
                <button
                  className="timeframe-menu-trigger"
                  type="button"
                  aria-expanded={isTimeframeMenuOpen}
                  aria-haspopup="menu"
                  onClick={() => setIsTimeframeMenuOpen((isOpen) => !isOpen)}
                >
                  {activeTimeframe} <ChevronDown size={16} aria-hidden="true" />
                </button>
                <div className="timeframe-menu-options" data-open={isTimeframeMenuOpen} role="menu">
                  {["1m", "5m", "15m", "1h", "4h", "1d"].map((timeframe) => (
                    <button
                      key={timeframe}
                      type="button"
                      role="menuitem"
                      data-active={activeTimeframe === timeframe}
                      onClick={() => {
                        updateDraft((workspace) => ({ ...workspace, chartSettings: { ...workspace.chartSettings, timeframe } }));
                        setCardTimeframes({});
                        setIsTimeframeMenuOpen(false);
                      }}
                    >
                      {timeframe}
                    </button>
                  ))}
                </div>
              </div>
              <IconButton
                label={isCompactChartLayout ? "\u041f\u043e\u043b\u043d\u044b\u0439 \u0432\u0438\u0434 \u0433\u0440\u0430\u0444\u0438\u043a\u043e\u0432" : "\u041a\u043e\u043c\u043f\u0430\u043a\u0442\u043d\u044b\u0439 \u0432\u0438\u0434 \u0433\u0440\u0430\u0444\u0438\u043a\u043e\u0432"}
                onClick={() => setIsCompactChartLayout((compact) => !compact)}
                active={isCompactChartLayout}
              >
                <Menu size={19} />
              </IconButton>
              <IconButton label="\u041e\u0431\u043d\u043e\u0432\u0438\u0442\u044c \u043f\u043e\u0440\u044f\u0434\u043e\u043a \u043c\u043e\u043d\u0435\u0442" onClick={refreshChartOrder}>
                <RefreshCw size={19} />
              </IconButton>
            </div>
          </div>
          <div className="mini-grid" style={{ gridTemplateColumns: `repeat(${Math.max(1, draftWorkspace?.gridLayout.columns || 3)}, minmax(280px, 1fr))` }}>
            {chartPageRows.map((row) => (
              <LazyChartCard
                key={`${row.symbol}-${row.market}`}
                row={row}
                activeRange={activeRange}
                activeTimeframe={cardTimeframes[`${row.symbol}:${row.market}`] || activeTimeframe}
                candleLimit={candleLimit}
                rightOffset={rightOffset}
                compact={isCompactChartLayout}
                selected={selectedRow?.symbol === row.symbol && selectedRow?.market === row.market}
                onSelect={() => setSelectedSymbol(row.symbol, row.market)}
                onTimeframeChange={(timeframe) =>
                  setCardTimeframes((current) => ({
                    ...current,
                    [`${row.symbol}:${row.market}`]: timeframe
                  }))
                }
                onFullscreen={() => setFullscreenChart(row)}
              />
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <strong>Скринер</strong>
              <span className="muted">{filteredRows.length} монет</span>
            </div>
            <div className="toolbar-group">
              <button data-active={draftWorkspace?.filters.onlyActive} onClick={() => updateDraft((workspace) => ({ ...workspace, filters: { ...workspace.filters, onlyActive: !workspace.filters.onlyActive } }))}>
                <Filter size={16} /> Активные
              </button>
              <button data-active={draftWorkspace?.filters.onlyWatchlist} onClick={() => updateDraft((workspace) => ({ ...workspace, filters: { ...workspace.filters, onlyWatchlist: !workspace.filters.onlyWatchlist } }))}>
                <Star size={16} /> Watchlist
              </button>
              <button data-active={draftWorkspace?.filters.onlyAlerts} onClick={() => updateDraft((workspace) => ({ ...workspace, filters: { ...workspace.filters, onlyAlerts: !workspace.filters.onlyAlerts } }))}>
                <Bell size={16} /> Алерты
              </button>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {visibleColumns.map((column) => (
                    <th key={column}>{columnLabels[column]}</th>
                  ))}
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row) => (
                  <tr key={`${row.symbol}-${row.market}`} data-selected={selectedRow?.symbol === row.symbol && selectedRow?.market === row.market}>
                    {visibleColumns.map((column) => (
                      <td key={column} data-positive={column === "priceChange24h" ? row.priceChange24h >= 0 : undefined}>
                        {column === "formation" ? rowFormationTag(row) : column === "hasAlert" ? (row.hasAlert ? <span className="tag" data-state="warn">Да</span> : <span className="muted">Нет</span>) : column === "inWatchlist" ? (row.inWatchlist ? <span className="tag" data-state="good">Да</span> : <span className="muted">Нет</span>) : toColumnValue(row, column)}
                      </td>
                    ))}
                    <td>
                      <div className="row-actions">
                        <IconButton label="Открыть" onClick={() => setSelectedSymbol(row.symbol, row.market)}>
                          <Activity size={15} />
                        </IconButton>
                        <IconButton label={row.inWatchlist ? "Убрать из watchlist" : "Добавить в watchlist"} onClick={() => toggleWatchlist(row)}>
                          {row.inWatchlist ? <Check size={15} /> : <CirclePlus size={15} />}
                        </IconButton>
                        <IconButton
                          label="AI-анализ"
                          onClick={() => {
                            setAiTarget(row);
                            setAiResult(null);
                            setModal("ai");
                          }}
                        >
                          <Brain size={15} />
                        </IconButton>
                        <IconButton label="Создать алерт" onClick={() => createQuickAlert(row)}>
                          <Bell size={15} />
                        </IconButton>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="info-grid">
          <div className="panel">
            <div className="panel-header">
              <div>
                <strong>Выбрано</strong>
                <span className="muted">{selectedRow?.symbol || "нет"}</span>
              </div>
            </div>
            <div className="panel-body">
              {selectedRow ? (
                <div className="right-stack">
                  <div className="statline">
                    <div className="stat">
                      <small>Цена</small>
                      <strong>{formatPrice(selectedRow.price)}</strong>
                    </div>
                    <div className="stat">
                      <small>24h</small>
                      <strong data-state={selectedRow.priceChange24h >= 0 ? "good" : "bad"}>{formatPct(selectedRow.priceChange24h)}</strong>
                    </div>
                    <div className="stat">
                      <small>Объем</small>
                      <strong>{formatCompact(selectedRow.volumeSum24h)}</strong>
                    </div>
                    <div className="stat">
                      <small>Сделки</small>
                      <strong>{formatCompact(selectedRow.tradesSum24h)}</strong>
                    </div>
                  </div>
                  <div>{rowFormationTag(selectedRow)}</div>
                  <div className="muted">{selectedRow.formation?.reason || "Формации не найдено."}</div>
                  <div className="toolbar-group">
                    <button
                      onClick={() => {
                        setAiTarget(selectedRow);
                        setAiResult(null);
                        setModal("ai");
                      }}
                    >
                      <Brain size={16} /> AI-анализ
                    </button>
                    <button onClick={() => toggleWatchlist(selectedRow)}>
                      <Star size={16} /> {selectedRow.inWatchlist ? "Убрать" : "В watchlist"}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="muted">Нет выбранной монеты</div>
              )}
            </div>
          </div>

          <div className="panel compact-list">
            <div className="panel-header">
              <strong>Watchlist</strong>
              <span className="muted">{watchlistItems.length}</span>
            </div>
            <div className="panel-body list">
              {watchlistItems.map((item) => (
                <div className="list-item" key={`${item.symbol}-${item.market}`}>
                  <div>
                    <strong>{item.symbol}</strong>
                    <div className="muted">{item.market}</div>
                  </div>
                  <IconButton label="Удалить" onClick={() => watchlistMutation.mutate(watchlistItems.filter((entry) => !(entry.symbol === item.symbol && entry.market === item.market)))}>
                    <Trash2 size={15} />
                  </IconButton>
                </div>
              ))}
              {watchlistItems.length === 0 ? <div className="muted">Пусто</div> : null}
            </div>
          </div>

          <div className="panel compact-list">
            <div className="panel-header">
              <strong>Алерты</strong>
              <span className="muted">{alerts.length}</span>
            </div>
            <div className="panel-body list">
              {alerts.map((alert) => (
                <div className="list-item" key={alert.id}>
                  <div>
                    <strong>{alert.type}</strong>
                    <div className="muted">{alert.symbols.join(", ") || alert.market}</div>
                  </div>
                  <IconButton label="Удалить" onClick={() => deleteAlertMutation.mutate(alert.id)}>
                    <Trash2 size={15} />
                  </IconButton>
                </div>
              ))}
              {alerts.length === 0 ? <div className="muted">Пусто</div> : null}
            </div>
          </div>
        </section>
      </main>

      {fullscreenChart ? (
        <div className="chart-fullscreen-backdrop" role="dialog" aria-modal="true" aria-label={`График ${fullscreenChart.symbol}`} onMouseDown={() => setFullscreenChart(null)}>
          <div className="chart-fullscreen-dialog" onMouseDown={(event) => event.stopPropagation()}>
            <button className="chart-fullscreen-close" type="button" onClick={() => setFullscreenChart(null)} aria-label="Закрыть полноэкранный график">
              <X size={20} />
            </button>
            <LazyChartCard
              row={fullscreenChart}
              activeRange={activeRange}
              activeTimeframe={cardTimeframes[`${fullscreenChart.symbol}:${fullscreenChart.market}`] || activeTimeframe}
              candleLimit={candleLimit}
              rightOffset={rightOffset}
              compact={false}
              selected
              fullscreen
              onSelect={() => setSelectedSymbol(fullscreenChart.symbol, fullscreenChart.market)}
              onTimeframeChange={(timeframe) =>
                setCardTimeframes((current) => ({
                  ...current,
                  [`${fullscreenChart.symbol}:${fullscreenChart.market}`]: timeframe
                }))
              }
              onFullscreen={() => setFullscreenChart(null)}
            />
          </div>
        </div>
      ) : null}

      {modal === "workspace" && draftWorkspace ? (
        <ModalShell
          title="Настройка торгового профиля"
          onClose={() => setModal(null)}
          footer={
            <>
              <button
                onClick={() => {
                  const profile = activeWorkspaces.find((workspace) => workspace.id === selectedWorkspaceId);
                  if (!profile) return;
                  deleteWorkspace(profile.id).then(async () => {
                    await queryClient.invalidateQueries({ queryKey: ["workspaces"] });
                    const next = activeWorkspaces.find((workspace) => workspace.id !== profile.id) || getDefaultWorkspace(`workspace-${Date.now()}`);
                    initialisedDraftRef.current = false;
                    lastSavedHashRef.current = "";
                    setSelectedWorkspaceId(next.id);
                    setDraftWorkspace(cloneWorkspace(next));
                    setModal(null);
                  });
                }}
              >
                <Trash2 size={16} /> Удалить
              </button>
              <button data-variant="primary" onClick={() => { saveNow(); setModal(null); }}>
                <Check size={16} /> Готово
              </button>
            </>
          }
        >
          <div className="profile-settings">
            <nav className="profile-settings-nav" aria-label="Разделы настройки профиля">
              <button data-active={workspaceTab === "start"} onClick={() => setWorkspaceTab("start")}>Начало</button>
              <button data-active={workspaceTab === "filters"} onClick={() => setWorkspaceTab("filters")}>Фильтры</button>
              <button data-active={workspaceTab === "sorting"} onClick={() => setWorkspaceTab("sorting")}>Сортировка</button>
              <button data-active={workspaceTab === "chart"} onClick={() => setWorkspaceTab("chart")}>График</button>
            </nav>

            <div className="profile-settings-content">
              {workspaceTab === "start" ? (
                <section className="settings-card">
                  <div className="settings-card-title">Название торгового профиля</div>
                  <label>
                    Название
                    <input autoFocus value={draftWorkspace.title} placeholder="Например, Futures скальпинг" onChange={(event) => updateDraft((workspace) => ({ ...workspace, title: event.target.value }))} />
                  </label>
                </section>
              ) : null}

              {workspaceTab === "filters" ? (
                <div className="settings-stack">
                  <section className="settings-card filter-market">
                    <div className="settings-card-title">Рынок</div>
                    <label>Тип рынка
                      <select value={normalizeMarket(draftWorkspace.market)} onChange={(event) => updateDraft((workspace) => ({ ...workspace, market: event.target.value }))}>
                        <option value="BINANCE_FUTURES">Futures</option>
                        <option value="BINANCE_SPOT">Spot</option>
                      </select>
                    </label>
                  </section>
                  <section className="settings-card">
                    <div className="settings-card-title">Чёрный список</div>
                    <label>Монеты через запятую или с новой строки
                      <textarea rows={3} value={draftWorkspace.filters.blacklist.join(", ")} placeholder="BTC/USDT, ETH/USDT" onChange={(event) => updateDraft((workspace) => ({ ...workspace, filters: { ...workspace.filters, blacklist: event.target.value.split(/[\n,]/).map((symbol) => symbol.trim().toUpperCase()).filter(Boolean) } }))} />
                    </label>
                  </section>
                  {([
                    ["Фильтр по объёму", "volume", "От ($)", "До ($)"],
                    ["Фильтр по изменению цены", "priceChange", "От (%)", "До (%)"],
                    ["Фильтр по сделкам", "trades", "От", "До"]
                  ] as const).map(([title, key, fromLabel, toLabel]) => (
                    <section className="settings-card" key={key}>
                      <div className="settings-card-title">{title}</div>
                      <div className="filter-fields">
                        <label>{fromLabel}<input type="number" value={draftWorkspace.filters[`${key}From` as "volumeFrom" | "priceChangeFrom" | "tradesFrom"] ?? ""} onChange={(event) => updateDraft((workspace) => ({ ...workspace, filters: { ...workspace.filters, [`${key}From`]: optionalNumber(event.target.value) } }))} /></label>
                        <label>{toLabel}<input type="number" value={draftWorkspace.filters[`${key}To` as "volumeTo" | "priceChangeTo" | "tradesTo"] ?? ""} onChange={(event) => updateDraft((workspace) => ({ ...workspace, filters: { ...workspace.filters, [`${key}To`]: optionalNumber(event.target.value) } }))} /></label>
                        <label>Интервал
                          <select value={draftWorkspace.filters[`${key}Range` as "volumeRange" | "priceChangeRange" | "tradesRange"] || "24h"} onChange={(event) => updateDraft((workspace) => ({ ...workspace, filters: { ...workspace.filters, [`${key}Range`]: event.target.value } }))}>
                            <option value="1m">1 минута</option><option value="5m">5 минут</option><option value="1h">1 час</option><option value="24h">24 часа</option>
                          </select>
                        </label>
                      </div>
                    </section>
                  ))}
                </div>
              ) : null}

              {workspaceTab === "sorting" ? (
                <section className="settings-card">
                  <div className="settings-card-title">Тип сортировки</div>
                  <div className="sorting-fields">
                    <label>Тип сортировки
                      <select value={draftWorkspace.sortingType} onChange={(event) => updateDraft((workspace) => ({ ...workspace, sortingType: event.target.value }))}>
                        {Object.entries(sortLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                    </label>
                    <label className="check-row"><input type="checkbox" checked={Boolean(draftWorkspace.pinAlerts)} onChange={(event) => updateDraft((workspace) => ({ ...workspace, pinAlerts: event.target.checked }))} /> Закрепить монеты с ценовыми оповещениями</label>
                  </div>
                </section>
              ) : null}

              {workspaceTab === "chart" ? (
                <section className="settings-card chart-settings-card">
                  <div className="settings-card-title">Параметры графика</div>
                  <label>Временной интервал</label>
                  <div className="interval-buttons">
                    {["1m", "5m", "15m", "1h", "4h", "1d"].map((timeframe) => <button key={timeframe} data-active={activeTimeframe === timeframe} onClick={() => updateDraft((workspace) => ({ ...workspace, chartSettings: { ...workspace.chartSettings, timeframe } }))}>{timeframe}</button>)}
                  </div>
                  <div className="chart-number-fields">
                    <label>Количество свечей<input type="number" min={50} max={1000} value={candleLimit} onChange={(event) => updateDraft((workspace) => ({ ...workspace, chartSettings: { ...workspace.chartSettings, candleLimit: Math.max(50, Math.min(1000, Number(event.target.value) || 50)) } }))} /></label>
                    <label>Отступ графика (кол-во свечей)<input type="number" min={0} max={500} value={rightOffset} onChange={(event) => updateDraft((workspace) => ({ ...workspace, chartSettings: { ...workspace.chartSettings, rightOffset: Math.max(0, Math.min(500, Number(event.target.value) || 0)) } }))} /></label>
                  </div>
                  <button className="screener-view-trigger" onClick={() => setIsScreenerViewOpen((open) => !open)}><Columns3 size={17} /> Вид скринера: {draftWorkspace.gridLayout.columns} × {draftWorkspace.gridLayout.rows}</button>
                  {isScreenerViewOpen ? <div className="screener-view-picker" aria-label="Выбор размера сетки">{Array.from({ length: 30 }, (_, index) => {
                    const columns = (index % 6) + 1;
                    const rows = Math.floor(index / 6) + 1;
                    const selected = columns <= draftWorkspace.gridLayout.columns && rows <= draftWorkspace.gridLayout.rows;
                    return <button key={`${columns}-${rows}`} data-selected={selected} aria-label={`${columns} колонок, ${rows} рядов`} onClick={() => { updateDraft((workspace) => ({ ...workspace, gridLayout: { columns, rows } })); setIsScreenerViewOpen(false); }} />;
                  })}</div> : null}
                </section>
              ) : null}
            </div>
          </div>
        </ModalShell>
      ) : null}

      {modal === "columns" && draftWorkspace ? (
        <ModalShell title="Колонки таблицы" onClose={() => setModal(null)}>
          <div className="settings-grid">
            {DEFAULT_COLUMNS.map((column) => (
              <label key={column} className="check-row">
                <input
                  type="checkbox"
                  checked={draftWorkspace.selectedColumns.includes(column)}
                  onChange={(event) =>
                    updateDraft((workspace) => ({
                      ...workspace,
                      selectedColumns: event.target.checked
                        ? [...workspace.selectedColumns, column]
                        : workspace.selectedColumns.filter((key) => key !== column)
                    }))
                  }
                />
                {columnLabels[column]}
              </label>
            ))}
          </div>
        </ModalShell>
      ) : null}

      {modal === "formations" && draftWorkspace ? (
        <ModalShell title="Настройки формаций" onClose={() => setModal(null)}>
          <div className="settings-grid">
            <label>
              Режим
              <select value={draftWorkspace.formationSettings.formation} onChange={(event) => updateDraft((workspace) => ({ ...workspace, formationSettings: { ...workspace.formationSettings, formation: event.target.value as FormationType } }))}>
                {Object.entries(formationLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="check-row">
              <input
                type="checkbox"
                checked={draftWorkspace.formationSettings.showOnlyFormations}
                onChange={(event) => updateDraft((workspace) => ({ ...workspace, formationSettings: { ...workspace.formationSettings, showOnlyFormations: event.target.checked } }))}
              />
              Только монеты с формациями
            </label>
            <label className="check-row">
              <input
                type="checkbox"
                checked={draftWorkspace.formationSettings.sortByFormations}
                onChange={(event) => updateDraft((workspace) => ({ ...workspace, formationSettings: { ...workspace.formationSettings, sortByFormations: event.target.checked } }))}
              />
              Сортировать по формациям
            </label>
            <label className="check-row">
              <input
                type="checkbox"
                checked={draftWorkspace.formationSettings.sortByLevelFormations}
                onChange={(event) => updateDraft((workspace) => ({ ...workspace, formationSettings: { ...workspace.formationSettings, sortByLevelFormations: event.target.checked } }))}
              />
              Учитывать уровни
            </label>
            <label>
              Положение лимитки
              <select value={draftWorkspace.formationSettings.formationLimitOrderLevelLocation} onChange={(event) => updateDraft((workspace) => ({ ...workspace, formationSettings: { ...workspace.formationSettings, formationLimitOrderLevelLocation: event.target.value as FormationSettings["formationLimitOrderLevelLocation"] } }))}>
                {["up", "down", "same", "none"].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Дистанция лимитки, %
              <input type="number" min={0} max={5} step={0.1} value={draftWorkspace.formationSettings.formationLimitOrderLevelDistance} onChange={(event) => updateDraft((workspace) => ({ ...workspace, formationSettings: { ...workspace.formationSettings, formationLimitOrderLevelDistance: Number(event.target.value) } }))} />
            </label>
          </div>
        </ModalShell>
      ) : null}

      {modal === "levels" && draftWorkspace ? (
        <ModalShell title="Уровни" onClose={() => setModal(null)}>
          <div className="split">
            <div className="panel">
              <div className="panel-header">
                <strong>Горизонтальные</strong>
              </div>
              <div className="panel-body settings-grid">
                <label className="check-row">
                  <input type="checkbox" checked={draftWorkspace.horizontalLevelSettings.showHorizontalLevels} onChange={(event) => updateDraft((workspace) => ({ ...workspace, horizontalLevelSettings: { ...workspace.horizontalLevelSettings, showHorizontalLevels: event.target.checked } }))} />
                  Показывать уровни
                </label>
                <label className="check-row">
                  <input type="checkbox" checked={draftWorkspace.horizontalLevelSettings.showDailyHighAndLow} onChange={(event) => updateDraft((workspace) => ({ ...workspace, horizontalLevelSettings: { ...workspace.horizontalLevelSettings, showDailyHighAndLow: event.target.checked } }))} />
                  High/Low дня
                </label>
                <label>
                  Период
                  <input type="number" min={20} max={1000} value={draftWorkspace.horizontalLevelSettings.horizontalLevelsPeriod} onChange={(event) => updateDraft((workspace) => ({ ...workspace, horizontalLevelSettings: { ...workspace.horizontalLevelSettings, horizontalLevelsPeriod: Number(event.target.value) } }))} />
                </label>
                <label>
                  Касания
                  <input type="number" min={1} max={10} value={draftWorkspace.horizontalLevelSettings.horizontalLevelsTouches} onChange={(event) => updateDraft((workspace) => ({ ...workspace, horizontalLevelSettings: { ...workspace.horizontalLevelSettings, horizontalLevelsTouches: Number(event.target.value) } }))} />
                </label>
              </div>
            </div>
            <div className="panel">
              <div className="panel-header">
                <strong>Трендовые</strong>
              </div>
              <div className="panel-body settings-grid">
                <label className="check-row">
                  <input type="checkbox" checked={draftWorkspace.trendLevelSettings.showTrendLevels} onChange={(event) => updateDraft((workspace) => ({ ...workspace, trendLevelSettings: { ...workspace.trendLevelSettings, showTrendLevels: event.target.checked } }))} />
                  Показывать трендовые
                </label>
                <label>
                  Источник
                  <select value={draftWorkspace.trendLevelSettings.trendlinesSource} onChange={(event) => updateDraft((workspace) => ({ ...workspace, trendLevelSettings: { ...workspace.trendLevelSettings, trendlinesSource: event.target.value as "high/low" | "close" } }))}>
                    {["high/low", "close"].map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Период
                  <input type="number" min={20} max={1000} value={draftWorkspace.trendLevelSettings.trendlinesPeriod} onChange={(event) => updateDraft((workspace) => ({ ...workspace, trendLevelSettings: { ...workspace.trendLevelSettings, trendlinesPeriod: Number(event.target.value) } }))} />
                </label>
              </div>
            </div>
          </div>
        </ModalShell>
      ) : null}

      {modal === "densities" && draftWorkspace ? (
        <ModalShell title="Плотности" onClose={() => setModal(null)}>
          <div className="settings-grid">
            <label className="check-row">
              <input type="checkbox" checked={draftWorkspace.densitySettings.showLimitOrders} onChange={(event) => updateDraft((workspace) => ({ ...workspace, densitySettings: { ...workspace.densitySettings, showLimitOrders: event.target.checked } }))} />
              Показывать лимитные заявки
            </label>
            <label className="check-row">
              <input type="checkbox" checked={draftWorkspace.densitySettings.showDensitiesWidget} onChange={(event) => updateDraft((workspace) => ({ ...workspace, densitySettings: { ...workspace.densitySettings, showDensitiesWidget: event.target.checked } }))} />
              Виджет плотностей
            </label>
            <label>
              Фильтр, USD
              <input type="number" min={0} step={1000} value={draftWorkspace.densitySettings.limitOrderFilter} onChange={(event) => updateDraft((workspace) => ({ ...workspace, densitySettings: { ...workspace.densitySettings, limitOrderFilter: Number(event.target.value) } }))} />
            </label>
            <label>
              Дистанция, %
              <input type="number" min={0} max={10} step={0.1} value={draftWorkspace.densitySettings.limitOrderDistance} onChange={(event) => updateDraft((workspace) => ({ ...workspace, densitySettings: { ...workspace.densitySettings, limitOrderDistance: Number(event.target.value) } }))} />
            </label>
            <label>
              Жизнь, мин
              <input type="number" min={0} max={1000} value={draftWorkspace.densitySettings.limitOrderLife} onChange={(event) => updateDraft((workspace) => ({ ...workspace, densitySettings: { ...workspace.densitySettings, limitOrderLife: Number(event.target.value) } }))} />
            </label>
            <label>
              Коррозия, мин
              <input type="number" min={0} max={50} value={draftWorkspace.densitySettings.limitOrderCorrosionTime} onChange={(event) => updateDraft((workspace) => ({ ...workspace, densitySettings: { ...workspace.densitySettings, limitOrderCorrosionTime: Number(event.target.value) } }))} />
            </label>
          </div>
        </ModalShell>
      ) : null}

      {modal === "alert" && selectedRow ? (
        <ModalShell
          title="Создать алерт"
          onClose={() => setModal(null)}
          footer={
            <button data-variant="primary" onClick={() => createQuickAlert(selectedRow)}>
              <Bell size={16} /> Создать
            </button>
          }
        >
          <div className="settings-grid">
            <label>
              Тип
              <select value={alertDraft.type} onChange={(event) => setAlertDraft((draft) => ({ ...draft, type: event.target.value }))}>
                {["priceChange", "volumeSplash", "volatility", "limitOrder", "funding", "openInterest", "listing", "trendLevels", "formationDetected"].map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Направление
              <select value={alertDraft.direction || "all"} onChange={(event) => setAlertDraft((draft) => ({ ...draft, direction: event.target.value as "up" | "down" | "all" }))}>
                {["all", "up", "down"].map((direction) => (
                  <option key={direction} value={direction}>
                    {direction}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Порог
              <input type="number" value={alertDraft.threshold || 0} onChange={(event) => setAlertDraft((draft) => ({ ...draft, threshold: Number(event.target.value) }))} />
            </label>
            <label>
              Дистанция
              <input type="number" value={alertDraft.distance || 0} onChange={(event) => setAlertDraft((draft) => ({ ...draft, distance: Number(event.target.value) }))} />
            </label>
            <label className="check-row">
              <input type="checkbox" checked={alertDraft.watchlistOnly} onChange={(event) => setAlertDraft((draft) => ({ ...draft, watchlistOnly: event.target.checked }))} />
              Только watchlist
            </label>
            <label className="check-row">
              <input type="checkbox" checked={alertDraft.telegramNotification} onChange={(event) => setAlertDraft((draft) => ({ ...draft, telegramNotification: event.target.checked }))} />
              Telegram
            </label>
          </div>
        </ModalShell>
      ) : null}

      {modal === "ai" && aiTarget ? (
        <ModalShell
          title={`AI-анализ: ${aiTarget.symbol}`}
          onClose={() => setModal(null)}
          footer={
            <div className="toolbar-group">
              <button onClick={() => aiMutation.mutate({ row: aiTarget, mode: "quick" })}>
                <Brain size={16} /> Быстро
              </button>
              <button data-variant="primary" onClick={() => aiMutation.mutate({ row: aiTarget, mode: "deep" })}>
                <Brain size={16} /> Глубоко
              </button>
            </div>
          }
        >
          <div className="right-stack">
            <div className="muted">AI возвращает структурированный JSON и не дает прямых команд купить или продать.</div>
            <pre className="json-box">{aiResult ? JSON.stringify(aiResult, null, 2) : "Запустите быстрый или глубокий анализ."}</pre>
          </div>
        </ModalShell>
      ) : null}
    </div>
  );
}
