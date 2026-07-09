# Dataset status

`DEPRECATED_pre_distance_published_signals_264677.jsonl` is the obsolete
264,677-row output from the first replay. It predates the corrected publication
pipeline and must not be used for calibration or production estimates.

The corrected calibration dataset is:

`../breakout-candle-calibration-corrected-20260709/published_signals_corrected.jsonl`

It contains 152,411 signals produced by a fresh replay of all 228 cached series
with:

- `MAX_PUBLISH_DISTANCE_NATR=1.5`;
- confidence-based publication filtering;
- score-descending sorting;
- per-`signal_key` pause;
- the current per-level-kind touch policy.

Every corrected published signal was checked for `distance_natr <= 1.5`.
See `../breakout-candle-calibration-corrected-20260709/report.json` for the
funnel, distributions, reference threshold tests, and validation result.
