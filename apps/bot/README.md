# Formation Telegram Bot

Telegram bot for Binance Futures breakout alerts.
Each alert is sent as a chart image with the signal text in the caption.

## Setup

```powershell
cd apps\bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill `TELEGRAM_BOT_TOKEN` in `.env`.

## Run

```powershell
python -m formation_bot.main
```

Send `/start` to the bot to subscribe the current Telegram chat to alerts.

## Commands

- `/start` - subscribe to breakout alerts
- `/stop` - unsubscribe
- `/status` - show current scanner settings

## Formation Logic

The bot scans Binance Futures USDT perpetual contracts with 24h quote volume from
`MIN_QUOTE_VOLUME_24H` (60,000,000 USDT by default) on the configured
`SCAN_TIMEFRAMES` (`1m,5m,15m,1h` by default).
If `SIGNAL_SYMBOL_ALLOWLIST` is set, only those symbols are scanned after the
24h volume filter passes.
NATR is computed as `ATR / close * 100` over `NATR_PERIOD` candles and is used
as a volatility scale for zone clustering, chart captions, and scoring context. Signals older than
`MAX_SIGNAL_AGE_MINUTES` (5 by default) are skipped so delivery stays close to the
closed candle that produced the alert. The current unfinished Binance kline is ignored,
so alerts are not emitted from a candle that can still disappear or reverse.

The detector now builds support/resistance zones, not single swing levels. It combines:

- confirmed fractal swings with `FRACTAL_N` candles on both sides;
- live-edge rolling highs/lows from the last `LIVE_WINDOW` closed candles, so recent zones can be tested before a right-side fractal confirmation exists.

Nearby swings of the same side are clustered with an NATR-scaled threshold:
`CLUSTER_TOLERANCE_NATR_K * NATR`. A zone with `ZONE_CONFIRMATION_TOUCHES` or more touches is
`confirmed`; a one-touch zone is `low_confidence`, can only produce a `test`, and is
penalized by `LOW_CONFIDENCE_PENALTY`.

Impulse is no longer a hard filter. The detector searches backward from the first touch by
`IMPULSE_SEARCH_WINDOW` bars and adds the result as the `w_impulse` score component. Zone TTL
is configured per timeframe with `ZONE_TTL_BARS`, and `MIN_RETREAT_M` plus `COOLDOWN_BARS`
protect against repeated signals from the same micro-consolidation. Every candidate that passes
the hard checks, stays within `MAX_PUBLISH_DISTANCE_NATR * NATR` from the relevant zone edge,
and has score from `MIN_SCORE_TO_PUBLISH` is published; independent zones do not compete for a
single top slot.

Published signal captions include signal type, confidence, funding rate, 24h change,
24h quote volume, 24h trades, BTC 1h correlation, NATR, touches, zone, score, and timeframe.
Signals below `MIN_24H_VOLUME_USD` are rejected after symbol metadata is available. For every
candidate zone, the detector writes a structured JSON `signal_candidate_decision` log entry
with the exact checks and rejection reason or publish decision.

Breakout signals also require the breakout candle body to occupy at least
`MIN_BREAKOUT_BODY_RATIO` of its full `high - low` range. The wick opposite to
the breakout direction may occupy at most `MAX_BREAKOUT_WICK_RATIO` of that
range: this is the lower wick for an upward resistance breakout and the upper
wick for a downward support breakout. The close must penetrate the crossed zone
edge by at least `MIN_CLOSE_ATR_MULTIPLIER * ATR`. These three checks apply only
to `breakout` signals. `MIN_NATR_PCT` is a minimum-volatility filter for all
signal types; its default value of `0` disables that filter.

Touch thresholds use one policy: `ZONE_CONFIRMATION_TOUCHES` confirms a
structural zone, `UNCONFIRMED_DEFAULT_TOUCHES` controls publication of other
low-confidence signals, and `UNCONFIRMED_TOUCHES_BY_LEVEL_KIND` contains
per-kind overrides such as `live_edge:1` or `compression:3`.

For every selected signal the bot renders a local PNG candlestick chart from the same
Binance candles used by the detector, highlights the detected level zone,
draws source pivot lines, and displays NATR, touches, and score in the footer.
The Telegram caption also includes funding rate, 24h price change, 24h quote
volume, 24h trade count, BTC 1h correlation, and score. Alert cooldown keys are
scoped to symbol, timeframe, side, zone, and signal state, so different zones and
timeframes of the same pair can be sent independently.

To replay the July 1 reference signals against live Binance candles:

```powershell
$env:PYTHONPATH="apps\bot"
$env:RUN_BINANCE_REFERENCE_TESTS="1"
python -m pytest apps\bot\tests\test_reference_signals_2026_07_01.py -q
```
