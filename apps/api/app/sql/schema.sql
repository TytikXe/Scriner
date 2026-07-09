CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_preferences (
  user_id TEXT PRIMARY KEY,
  data JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS workspaces (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  title TEXT NOT NULL,
  market TEXT NOT NULL,
  data JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS coins (
  symbol TEXT PRIMARY KEY,
  base TEXT,
  quote TEXT,
  active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS markets (
  id TEXT PRIMARY KEY,
  exchange TEXT NOT NULL,
  market TEXT NOT NULL,
  data JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS candles (
  ts TIMESTAMPTZ NOT NULL,
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  exchange TEXT NOT NULL,
  open NUMERIC NOT NULL,
  high NUMERIC NOT NULL,
  low NUMERIC NOT NULL,
  close NUMERIC NOT NULL,
  volume NUMERIC NOT NULL,
  trades NUMERIC,
  PRIMARY KEY (ts, symbol, market, exchange)
);

CREATE TABLE IF NOT EXISTS coin_metrics (
  ts TIMESTAMPTZ NOT NULL,
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  exchange TEXT NOT NULL,
  data JSONB NOT NULL,
  PRIMARY KEY (ts, symbol, market, exchange)
);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
  ts TIMESTAMPTZ NOT NULL,
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  exchange TEXT NOT NULL,
  data JSONB NOT NULL,
  PRIMARY KEY (ts, symbol, market, exchange)
);

CREATE TABLE IF NOT EXISTS densities (
  id TEXT PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL,
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  exchange TEXT NOT NULL,
  data JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS levels (
  id TEXT PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL,
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  exchange TEXT NOT NULL,
  data JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS formations (
  id TEXT PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL,
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  exchange TEXT NOT NULL,
  data JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_analyses (
  id TEXT PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL,
  cache_key TEXT NOT NULL,
  data JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  data JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlists (
  user_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  exchange TEXT NOT NULL,
  PRIMARY KEY (user_id, symbol, market, exchange)
);

-- Timescale hypertables:
-- SELECT create_hypertable('candles', 'ts');
-- SELECT create_hypertable('coin_metrics', 'ts');
-- SELECT create_hypertable('orderbook_snapshots', 'ts');

