import type { Candle, MarketSymbol, MarketKind } from "@/lib/types";

export interface Ticker {
  symbol: string;
  market: MarketKind | string;
  exchange: string;
  last: number;
  bid?: number | null;
  ask?: number | null;
  quoteVolume?: number | null;
  baseVolume?: number | null;
  priceChangePercent?: number | null;
  trades?: number | null;
  ts?: string | null;
}

export interface OrderBookLevel {
  price: number;
  size: number;
  sizeUsd?: number | null;
}

export interface OrderBookSnapshot {
  symbol: string;
  market: MarketKind | string;
  exchange: string;
  ts: string;
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
}

export interface TickerUpdate {
  symbol: string;
  market: MarketKind | string;
  exchange: string;
  ticker: Ticker;
}

export interface OrderBookUpdate {
  symbol: string;
  market: MarketKind | string;
  exchange: string;
  snapshot: OrderBookSnapshot;
}

export interface ExchangeAdapter {
  getMarkets(): Promise<MarketSymbol[]>;
  getTickers(): Promise<Ticker[]>;
  getCandles(symbol: string, timeframe: string, limit: number): Promise<Candle[]>;
  getOrderBook(symbol: string, depth: number): Promise<OrderBookSnapshot>;
  subscribeTickers(symbols: string[]): AsyncIterable<TickerUpdate>;
  subscribeOrderBook(symbols: string[]): AsyncIterable<OrderBookUpdate>;
}

