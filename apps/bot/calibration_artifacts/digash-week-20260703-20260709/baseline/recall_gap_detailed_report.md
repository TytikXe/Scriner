# Recall gap detailed diagnostics
No production code or config changes were made.
## Summary
- Detector misses: 28 of 81 Digash signals.
- Publication losses after detector match: 11.
- Production timeframes: 1m, 5m, 15m, 1h.
- MIN_QUOTE_VOLUME_24H: 60,000,000.

## Detector Miss Primary Reasons
- universe/liquidity_below_60m: 17
- zone_matching/clustering_gap: 6
- time_alignment/no_candidate_in_match_window: 3
- timeframe_coverage/4h_not_scanned_plus_zone_mismatch: 1
- universe/not_on_exchangeinfo: 1

## Publication Loss Reasons
- allowed_filter: 8
- batch_limit: 3

## Key Files
- `recall_gap_detailed_report.json`
- `recall_gap_detector_misses.csv`
- `recall_gap_publication_losses.csv`
