"use client";

import { Candle } from "@/lib/types";
import { Minus, Slash, Trash2 } from "lucide-react";
import { createChart } from "lightweight-charts";
import { type PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from "react";

type Props = {
  candles: Candle[];
  title: string;
  timeframe: string;
  rightOffset?: number;
  enableDrawing?: boolean;
};

type ChartPoint = { logical: number; price: number };
type ChartDrawing =
  | { id: string; type: "horizontal"; price: number }
  | { id: string; type: "trend"; start: ChartPoint; end: ChartPoint };
type RenderedDrawing =
  | { id: string; type: "horizontal"; y: number }
  | { id: string; type: "trend"; x1: number; y1: number; x2: number; y2: number };
type RenderedTrendDrawing = Extract<RenderedDrawing, { type: "trend" }>;
type DragState =
  | { type: "horizontal"; id: string }
  | { type: "trend-move"; id: string; origin: ChartPoint; start: ChartPoint; end: ChartPoint }
  | { type: "trend-start"; id: string }
  | { type: "trend-end"; id: string };

const chartTimeFormatter = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Minsk",
  hour: "2-digit",
  minute: "2-digit"
});

function formatChartTime(timestamp: number) {
  return chartTimeFormatter.format(new Date(timestamp * 1000));
}

function timeframeMilliseconds(timeframe: string) {
  const values: Record<string, number> = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000
  };
  return values[timeframe] || values["5m"];
}

function formatCountdown(milliseconds: number) {
  const totalSeconds = Math.max(0, Math.ceil(milliseconds / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function MiniChart({ candles, title, timeframe, rightOffset = 0, enableDrawing = false }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<any>(null);
  const candleSeriesRef = useRef<any>(null);
  const volumeSeriesRef = useRef<any>(null);
  const priceLineRef = useRef<any>(null);
  const didFitContentRef = useRef(false);
  const dragStateRef = useRef<DragState | null>(null);
  const [markerTop, setMarkerTop] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [drawingMode, setDrawingMode] = useState<"horizontal" | "trend" | null>(null);
  const [drawings, setDrawings] = useState<ChartDrawing[]>([]);
  const [trendStart, setTrendStart] = useState<ChartPoint | null>(null);
  const [trendPreview, setTrendPreview] = useState<ChartPoint | null>(null);
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null);
  const [drawingVersion, setDrawingVersion] = useState(0);

  const candleData = useMemo(
    () =>
      candles.map((candle) => ({
        time: Math.floor(new Date(candle.ts).getTime() / 1000) as any,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close
      })),
    [candles]
  );
  const volumeData = useMemo(
    () =>
      candles.map((candle) => ({
        time: Math.floor(new Date(candle.ts).getTime() / 1000) as any,
        value: candle.volume,
        color: candle.close >= candle.open ? "rgba(0, 181, 126, 0.42)" : "rgba(238, 57, 93, 0.42)"
      })),
    [candles]
  );
  const lastCandle = candles[candles.length - 1];
  const currentPrice = lastCandle?.close || 0;
  const priceIsUp = Boolean(lastCandle && lastCandle.close >= lastCandle.open);
  const candleDuration = timeframeMilliseconds(timeframe);
  const nextCloseAt = Math.floor(now / candleDuration) * candleDuration + candleDuration;
  const countdown = formatCountdown(nextCloseAt - now);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      layout: {
        background: { color: "#070912" },
        textColor: "#a9a8b9",
        attributionLogo: false
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.055)" },
        horzLines: { color: "rgba(255,255,255,0.055)" }
      },
      rightPriceScale: {
        visible: true,
        borderVisible: false,
        textColor: "#c8c7d5",
        scaleMargins: { top: 0.08, bottom: 0.22 }
      },
      timeScale: {
        visible: true,
        borderVisible: false,
        timeVisible: true,
        secondsVisible: false,
        minBarSpacing: 7,
        tickMarkFormatter: (time: unknown) => {
          const timestamp = typeof time === "number" ? time : Number(time);
          return Number.isFinite(timestamp) ? formatChartTime(timestamp) : "";
        }
      },
      crosshair: {
        mode: 0,
        vertLine: { color: "rgba(255,255,255,0.22)", labelVisible: false },
        horzLine: { color: "rgba(255,255,255,0.22)", labelVisible: false }
      },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
      handleScroll: { horzTouchDrag: true, mouseWheel: true, pressedMouseMove: true, vertTouchDrag: false },
      localization: {
        locale: "ru-RU",
        timeFormatter: (time: unknown) => {
          const timestamp = typeof time === "number" ? time : Number(time);
          return Number.isFinite(timestamp) ? formatChartTime(timestamp) : "";
        }
      }
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#00b57e",
      downColor: "#ee395d",
      borderUpColor: "#00b57e",
      borderDownColor: "#ee395d",
      wickUpColor: "#00c58a",
      wickDownColor: "#ff4d6f",
      lastValueVisible: false,
      priceLineVisible: false
    });
    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "",
      lastValueVisible: false,
      priceLineVisible: false
    });
    chart.priceScale("").applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    candleSeries.setData(candleData);
    volumeSeries.setData(volumeData);
    if (candleData.length) {
      chart.timeScale().fitContent();
      chart.timeScale().scrollToPosition(-Math.max(0, rightOffset), false);
      didFitContentRef.current = true;
    }

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth, height: containerRef.current.clientHeight });
      setDrawingVersion((version) => version + 1);
    });
    resizeObserver.observe(containerRef.current);
    const refreshDrawings = () => setDrawingVersion((version) => version + 1);
    chart.timeScale().subscribeVisibleTimeRangeChange(refreshDrawings);

    return () => {
      resizeObserver.disconnect();
      chart.timeScale().unsubscribeVisibleTimeRangeChange(refreshDrawings);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      priceLineRef.current = null;
    };
  }, []);

  useEffect(() => {
    candleSeriesRef.current?.setData(candleData);
    volumeSeriesRef.current?.setData(volumeData);
    if (candleData.length && !didFitContentRef.current) {
      chartRef.current?.timeScale().fitContent();
      didFitContentRef.current = true;
    }
  }, [candleData, volumeData]);

  useEffect(() => {
    if (candleData.length) chartRef.current?.timeScale().scrollToPosition(-Math.max(0, rightOffset), false);
  }, [candleData.length, rightOffset]);

  useEffect(() => {
    if (!enableDrawing) {
      setDrawingMode(null);
      setTrendStart(null);
      setTrendPreview(null);
      setSelectedDrawingId(null);
      dragStateRef.current = null;
      return;
    }
    const refresh = window.setInterval(() => setDrawingVersion((version) => version + 1), 120);
    return () => window.clearInterval(refresh);
  }, [enableDrawing]);

  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    if (!candleSeries || !currentPrice) {
      setMarkerTop(null);
      return;
    }

    const color = priceIsUp ? "#00b57e" : "#ee395d";
    if (!priceLineRef.current) {
      priceLineRef.current = candleSeries.createPriceLine({
        price: currentPrice,
        color,
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: false,
        title: ""
      });
    } else {
      priceLineRef.current.applyOptions({ price: currentPrice, color });
    }

    const frame = window.requestAnimationFrame(() => {
      const nextTop = candleSeries.priceToCoordinate(currentPrice);
      setMarkerTop(typeof nextTop === "number" && Number.isFinite(nextTop) ? nextTop : null);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [currentPrice, priceIsUp, candleData, now]);

  const chartPointFromPointer = (event: ReactPointerEvent<Element>): ChartPoint | null => {
    const rect = containerRef.current?.getBoundingClientRect() || event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const logical = chartRef.current?.timeScale().coordinateToLogical(x);
    const price = candleSeriesRef.current?.coordinateToPrice(y);
    return typeof logical === "number" && Number.isFinite(logical) && typeof price === "number" && Number.isFinite(price) ? { logical, price } : null;
  };

  const addDrawingAtPointer = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!drawingMode) return;
    const point = chartPointFromPointer(event);
    if (!point) return;
    if (drawingMode === "horizontal") {
      const id = crypto.randomUUID();
      setDrawings((current) => [...current, { id, type: "horizontal", price: point.price }]);
      setSelectedDrawingId(id);
      setDrawingMode(null);
      return;
    }
    if (!trendStart) {
      setTrendStart(point);
      setTrendPreview(point);
      return;
    }
    const id = crypto.randomUUID();
    setDrawings((current) => [...current, { id, type: "trend", start: trendStart, end: point }]);
    setSelectedDrawingId(id);
    setTrendStart(null);
    setTrendPreview(null);
    setDrawingMode(null);
  };

  const previewTrendAtPointer = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (drawingMode !== "trend" || !trendStart) return;
    setTrendPreview(chartPointFromPointer(event));
  };

  const beginDragging = (event: ReactPointerEvent<SVGElement>, dragState: DragState) => {
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragStateRef.current = dragState;
    setSelectedDrawingId(dragState.id);
  };

  const editDrawingAtPointer = (event: ReactPointerEvent<SVGSVGElement>) => {
    const dragState = dragStateRef.current;
    if (!dragState) return false;
    const point = chartPointFromPointer(event);
    if (!point) return true;
    setDrawings((current) => current.map((drawing) => {
      if (drawing.id !== dragState.id) return drawing;
      if (dragState.type === "horizontal" && drawing.type === "horizontal") return { ...drawing, price: point.price };
      if (drawing.type !== "trend") return drawing;
      if (dragState.type === "trend-start") return { ...drawing, start: point };
      if (dragState.type === "trend-end") return { ...drawing, end: point };
      if (dragState.type === "trend-move") {
        const logicalOffset = point.logical - dragState.origin.logical;
        const priceOffset = point.price - dragState.origin.price;
        return {
          ...drawing,
          start: { logical: dragState.start.logical + logicalOffset, price: dragState.start.price + priceOffset },
          end: { logical: dragState.end.logical + logicalOffset, price: dragState.end.price + priceOffset }
        };
      }
      return drawing;
    }));
    return true;
  };

  const finishDragging = () => {
    dragStateRef.current = null;
  };

  const renderedDrawings = useMemo<RenderedDrawing[]>(() => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    if (!chart || !candleSeries) return [];
    const rendered: RenderedDrawing[] = [];
    drawings.forEach((drawing) => {
      if (drawing.type === "horizontal") {
        const y = candleSeries.priceToCoordinate(drawing.price);
        if (typeof y === "number" && Number.isFinite(y)) rendered.push({ id: drawing.id, type: "horizontal", y });
        return;
      }
      const x1 = chart.timeScale().logicalToCoordinate(drawing.start.logical);
      const y1 = candleSeries.priceToCoordinate(drawing.start.price);
      const x2 = chart.timeScale().logicalToCoordinate(drawing.end.logical);
      const y2 = candleSeries.priceToCoordinate(drawing.end.price);
      if ([x1, y1, x2, y2].every((value) => typeof value === "number" && Number.isFinite(value))) {
        rendered.push({ id: drawing.id, type: "trend", x1: x1 as number, y1: y1 as number, x2: x2 as number, y2: y2 as number });
      }
    });
    return rendered;
  }, [drawings, drawingVersion]);

  const renderedTrendPreview = useMemo<RenderedTrendDrawing | null>(() => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    if (!chart || !candleSeries || !trendStart || !trendPreview) return null;
    const x1 = chart.timeScale().logicalToCoordinate(trendStart.logical);
    const y1 = candleSeries.priceToCoordinate(trendStart.price);
    const x2 = chart.timeScale().logicalToCoordinate(trendPreview.logical);
    const y2 = candleSeries.priceToCoordinate(trendPreview.price);
    return [x1, y1, x2, y2].every((value) => typeof value === "number" && Number.isFinite(value))
      ? { id: "trend-preview", type: "trend", x1: x1 as number, y1: y1 as number, x2: x2 as number, y2: y2 as number }
      : null;
  }, [trendStart, trendPreview, drawingVersion]);

  const drawingHint = drawingMode === "horizontal"
    ? "Кликните на графике, чтобы добавить горизонталь"
    : trendStart
      ? "Двигайте мышью, затем кликните вторую точку"
      : drawingMode === "trend"
        ? "Выберите первую точку линии"
        : "";

  return (
    <div className="mini-chart-canvas" aria-label={title}>
      {candles.length === 0 ? <div className="chart-empty">No candles</div> : null}
      <div ref={containerRef} style={{ width: "100%", height: "100%" }} />
      {enableDrawing ? (
        <>
          <div className="chart-drawing-toolbar" aria-label="Инструменты рисования">
            <button type="button" title="Горизонтальная линия" aria-label="Рисовать горизонтальные линии" data-active={drawingMode === "horizontal"} onClick={() => { setDrawingMode((mode) => mode === "horizontal" ? null : "horizontal"); setTrendStart(null); setTrendPreview(null); }}><Minus size={17} /></button>
            <button type="button" title="Наклонная линия" aria-label="Рисовать наклонные линии" data-active={drawingMode === "trend"} onClick={() => { setDrawingMode((mode) => mode === "trend" ? null : "trend"); setTrendStart(null); setTrendPreview(null); }}><Slash size={17} /></button>
            <button type="button" title="Очистить линии" aria-label="Очистить все линии" onClick={() => { setDrawings([]); setTrendStart(null); setTrendPreview(null); setDrawingMode(null); }}><Trash2 size={15} /></button>
          </div>
          {drawingHint ? <div className="chart-drawing-hint">{drawingHint}</div> : null}
          <svg className="chart-drawing-layer" data-drawing={drawingMode ? "true" : "false"} aria-hidden="true" onPointerDown={addDrawingAtPointer} onPointerMove={(event) => { if (!editDrawingAtPointer(event)) previewTrendAtPointer(event); }} onPointerUp={finishDragging} onPointerCancel={finishDragging} onPointerLeave={() => { if (!dragStateRef.current) setTrendPreview(null); }}>
            {renderedDrawings.map((drawing) => drawing.type === "horizontal" ? (
              <line key={drawing.id} className="chart-drawing-line chart-drawing-line-horizontal" x1="0" y1={drawing.y} x2="100%" y2={drawing.y} onPointerDown={(event) => beginDragging(event, { type: "horizontal", id: drawing.id })} />
            ) : (
              <g key={drawing.id}>
                <line className="chart-drawing-line chart-drawing-line-trend" x1={drawing.x1} y1={drawing.y1} x2={drawing.x2} y2={drawing.y2} onPointerDown={(event) => {
                  const source = drawings.find((item) => item.id === drawing.id);
                  const origin = chartPointFromPointer(event);
                  if (source?.type === "trend" && origin) beginDragging(event, { type: "trend-move", id: drawing.id, origin, start: source.start, end: source.end });
                }} />
                <circle className="chart-drawing-handle" data-selected={selectedDrawingId === drawing.id} cx={drawing.x1} cy={drawing.y1} r="6" onPointerDown={(event) => beginDragging(event, { type: "trend-start", id: drawing.id })} />
                <circle className="chart-drawing-handle" data-selected={selectedDrawingId === drawing.id} cx={drawing.x2} cy={drawing.y2} r="6" onPointerDown={(event) => beginDragging(event, { type: "trend-end", id: drawing.id })} />
              </g>
            ))}
            {renderedTrendPreview ? <line className="chart-drawing-line chart-drawing-line-preview" x1={renderedTrendPreview.x1} y1={renderedTrendPreview.y1} x2={renderedTrendPreview.x2} y2={renderedTrendPreview.y2} /> : null}
          </svg>
        </>
      ) : null}
      {markerTop !== null ? (
        <div className="live-price-marker" data-state={priceIsUp ? "good" : "bad"} style={{ top: `${markerTop}px` }}>
          <strong>{currentPrice >= 1 ? currentPrice.toFixed(4) : currentPrice.toFixed(6)}</strong>
          <span>{countdown}</span>
        </div>
      ) : null}
    </div>
  );
}
