# Corrected breakout-candle calibration — 2026-07-09

This artifact set replaces the obsolete 264,677-row pre-distance replay.

## Canonical inputs and pipeline

The calibration was produced by a fresh replay of all 228 cached
symbol/timeframe series for:

- 2026-06-24 01:13:05.290 UTC through 2026-07-08 01:13:05.289 UTC;
- `MAX_PUBLISH_DISTANCE_NATR=1.5`;
- confidence-based confirmed filtering;
- score-descending sorting;
- per-`signal_key` pause;
- the current per-level-kind touch policy.

The three metrics being calibrated were deliberately relaxed only inside the
calibration runner (`body=0`, `wick=1`, `close_atr=0`) to avoid truncating their
distributions. Production configuration was not changed.

## Files

- `report.json` — funnel, percentile distributions, reference threshold tests,
  validation result, and the 15-signal sample manifest.
- `published_signals_corrected.jsonl.gz` — complete 152,411-row corrected
  dataset, gzip-compressed to fit GitHub's per-file limit.
- `published_signals_corrected.jsonl.sha256` — checksum of the uncompressed
  JSONL.
- `charts/*.png` — 15 individual random sample charts. Every chart includes
  `distance_natr` and the `<= 1.5` limit in its visible caption.
- `calibration_samples_contact_sheet.jpg` — visual overview of all 15 charts.
- `symbol_metadata.json` — metadata snapshot used by the replay.

To inspect the full dataset:

```bash
gzip -dc published_signals_corrected.jsonl.gz | head
```

## Verified result

- Published signals: 152,411.
- Breakouts: 74,064.
- Tests: 78,347.
- `distance_natr` violations: 0 of 152,411.
- Maximum observed `distance_natr`: 1.4999802481385236.

Do not use any file named
`DEPRECATED_pre_distance_published_signals_264677.jsonl` for calibration.
