# Digash week baseline, 2026-07-03..2026-07-09

Исследовательские артефакты по неделе сигналов конкурента Digash.
Код и production-конфиг бота в этой фазе не менялись.

## Step 1: Digash dataset

- Источник: `C:\Users\goooo\OneDrive\Desktop\Сигналы конкурениа`
- Формат: 81 PNG-скриншот Telegram/Digash, разложены по папкам дат.
- На скриншотах видимое время есть, полной даты нет; дата восстановлена из имени дневной папки.
- Структурированные файлы:
  - `digash_signals.csv`
  - `digash_signals.jsonl`
  - `digash_ocr_raw.jsonl`
  - `digash_parse_final_audit.json`

Итоги Digash:

- Всего: 81 сигнал.
- По дням: 2026-07-03: 10, 2026-07-04: 8, 2026-07-05: 6, 2026-07-06: 20, 2026-07-07: 14, 2026-07-08: 18, 2026-07-09: 5.
- Типы: breakout 81, test 0.
- Стороны: support 48, resistance 33.
- Таймфреймы: 1m 45, 5m 19, 3m 8, 15m 4, 1h 4, 4h 1.

## Step 2: baseline

Окно baseline: `2026-07-03T00:00:00+03:00` .. `2026-07-09T23:59:59+03:00`.

Правило match:

- same symbol
- same side
- time window: `min(180m, max(45m, 2 * Digash timeframe))`
- zone overlaps or relative gap <= 0.5%
- наш timeframe не обязан совпадать, потому что production сканирует `1m,5m,15m,1h`, а у Digash есть `3m` и `4h`

Baseline results:

- Digash total: 81
- Raw detector candidates: 422,508
- Published after current policy: 80,450
- Average published/day: about 11,493
- Needed reduction to 150/day: about 76.6x

Recall:

- Detector loose: 53/81 = 65.43%
- Detector strict same type: 23/81 = 28.40%
- Published loose: 42/81 = 51.85%
- Published strict same type: 21/81 = 25.93%

Main baseline files:

- `baseline/baseline_match_summary.json`
- `baseline/digash_baseline_matches.jsonl`
- `baseline/gap_analysis.json`
- `baseline/miss_symbol_universe_check.json`
- `baseline/baseline_detector_candidates_window.jsonl.gz`
- `baseline/baseline_published_signals.jsonl.gz`
- `baseline/supplement_candidates_20260708_0113_to_20260709_2059.jsonl.gz`

The uncompressed large JSONL files were intentionally not committed because `baseline_detector_candidates_window.jsonl` is larger than GitHub's regular 100 MB file limit. The `.gz` files contain the same data in compressed form.

## Step 3: gap analysis

Detector misses: 28.

- 18: symbol did not enter our candidate universe, mostly due to `MIN_QUOTE_VOLUME_24H=60M`; `SNDRUSDT` was not found in Binance Futures exchangeInfo.
- 7: same symbol/side/time existed, but zone was not close enough.
- 3: same-side candidates existed, but outside the match time window.

Detector-to-published losses: 11.

- 8: `allowed_filter`, usually low-confidence `test` below current `MIN_UNCONFIRMED_SIGNAL_SCORE=60.83`.
- 3: `batch_limit`.
- For matched Digash cases, `signal_key_pause` was not the direct loss reason.

## Step 4: budget options, not implemented

No budget code was implemented. Candidate architectures discussed:

1. Global daily cap with score priority.
2. Daily quota split by hour/scan with carry-over.
3. Adaptive score threshold targeting about 150/day.

Main conclusion: the 150/day budget alone will not fix recall. Current detector-level recall is only 65.43%, so universe/liquidity coverage and zone matching need separate decisions before or alongside any publishing budget.
