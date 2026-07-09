# Final publication funnel — body ratio 0.40

This is the final replay of all 228 cached symbol/timeframe series for
2026-06-24 01:13:05.290 UTC through 2026-07-08 01:13:05.289 UTC.

All production rules were active simultaneously:

- `MAX_PUBLISH_DISTANCE_NATR=1.5`;
- confidence-based confirmed filtering (not `is_breakout_type`);
- score-descending batch sorting;
- per-`signal_key` pause;
- the unified per-level-kind touch policy;
- `MIN_BREAKOUT_BODY_RATIO=0.40`;
- `MAX_BREAKOUT_WICK_RATIO=0.25`;
- `MIN_CLOSE_ATR_MULTIPLIER=0.12`.

## Final funnel

| Stage | Count |
|---|---:|
| Detector candidates after distance, score, and candle filters | 862,470 |
| Dropped by publication policy | 618,955 |
| Dropped by per-signal-key pause | 86,545 |
| Allowed before batch limit | 156,970 |
| Dropped by batch limit | 24,183 |
| Published | 132,787 |

Published composition:

- breakouts: 45,276;
- tests: 87,511;
- breakout:test ratio: 0.517:1;
- equivalently, one breakout per 1.933 tests.

## Change from the first report

| Metric | First report | Final report | Change |
|---|---:|---:|---:|
| Published total | 89,610 | 132,787 | +43,177 (+48.2%) |
| Breakouts | 78,577 | 45,276 | -33,301 (-42.4%) |
| Tests | 11,033 | 87,511 | +76,478 (+693.2%) |
| Breakout:test | 7.122:1 | 0.517:1 | Tests now predominate |

`final_funnel_body040.json` contains the complete machine-readable funnel,
including the comparison policy variants and target-symbol breakdowns.
