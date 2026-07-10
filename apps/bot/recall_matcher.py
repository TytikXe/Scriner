from __future__ import annotations

import argparse
import bisect
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_TIME_WINDOW_MIN = 60.0
DEFAULT_ZONE_GAP_PCT = 0.35
DEFAULT_UNCONFIRMED_TOUCHES_BY_LEVEL_KIND = {
    "early_single_touch": 1,
    "live_edge": 1,
    "global_extreme": 2,
    "compression": 3,
    "impulse_approach": 2,
}


@dataclass(frozen=True)
class MatchParams:
    time_window_min: float = DEFAULT_TIME_WINDOW_MIN
    zone_gap_pct: float = DEFAULT_ZONE_GAP_PCT


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def parse_timestamp_ms(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp() * 1000)


def normalize_zone(low: Any, high: Any) -> tuple[float, float]:
    left = float(low)
    right = float(high)
    return (left, right) if left <= right else (right, left)


def prepare_digash(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        item = dict(row)
        zone_low, zone_high = normalize_zone(item["zone_low"], item["zone_high"])
        item["_id"] = index
        item["_timestamp_ms"] = parse_timestamp_ms(str(item["timestamp"]))
        item["_zone_low"] = zone_low
        item["_zone_high"] = zone_high
        item["_zone_mid"] = max((zone_low + zone_high) / 2, 1e-12)
        prepared.append(item)
    return prepared


def prepare_candidates(rows: list[dict[str, Any]]) -> dict[tuple[str, str], tuple[list[int], list[dict[str, Any]]]]:
    by_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows):
        item = dict(row)
        item.setdefault("id", index)
        item["_close_ms"] = int(item["close_ms"])
        zone_low, zone_high = normalize_zone(
            item.get("zone_low", item.get("zone_lower")),
            item.get("zone_high", item.get("zone_upper")),
        )
        item["_zone_low"] = zone_low
        item["_zone_high"] = zone_high
        by_pair[(str(item["symbol"]), str(item["side"]))].append(item)

    indexed: dict[tuple[str, str], tuple[list[int], list[dict[str, Any]]]] = {}
    for pair, items in by_pair.items():
        items.sort(key=lambda item: int(item["_close_ms"]))
        indexed[pair] = ([int(item["_close_ms"]) for item in items], items)
    return indexed


def zone_relation(digash: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, float]:
    overlap = max(
        0.0,
        min(float(digash["_zone_high"]), float(candidate["_zone_high"]))
        - max(float(digash["_zone_low"]), float(candidate["_zone_low"])),
    )
    max_width = max(
        float(digash["_zone_high"]) - float(digash["_zone_low"]),
        float(candidate["_zone_high"]) - float(candidate["_zone_low"]),
        1e-12,
    )
    if overlap > 0:
        gap = 0.0
    else:
        gap = max(
            float(digash["_zone_low"]) - float(candidate["_zone_high"]),
            float(candidate["_zone_low"]) - float(digash["_zone_high"]),
            0.0,
        )
    return gap / float(digash["_zone_mid"]) * 100, overlap / max_width


def candidate_matches_zone(digash: dict[str, Any], candidate: dict[str, Any], params: MatchParams) -> bool:
    gap_pct, overlap_ratio = zone_relation(digash, candidate)
    return gap_pct <= params.zone_gap_pct or overlap_ratio > 0


def is_confirmed_breakout(candidate: dict[str, Any]) -> bool:
    return candidate.get("type") == "breakout" and candidate.get("confidence") == "confirmed"


def public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in candidate.items() if not key.startswith("_")}
    result.pop("id", None)
    return result


def best_match(
    indexed: dict[tuple[str, str], tuple[list[int], list[dict[str, Any]]]],
    digash: dict[str, Any],
    params: MatchParams,
    *,
    confirmed_only: bool = False,
) -> dict[str, Any] | None:
    pair = indexed.get((str(digash["symbol"]), str(digash["side"])))
    if not pair:
        return None

    times, candidates = pair
    window_ms = int(params.time_window_min * 60_000)
    low_index = bisect.bisect_left(times, int(digash["_timestamp_ms"]) - window_ms)
    high_index = bisect.bisect_right(times, int(digash["_timestamp_ms"]) + window_ms)
    best: tuple[tuple[float, float, float, float], dict[str, Any]] | None = None
    for candidate in candidates[low_index:high_index]:
        if confirmed_only and not is_confirmed_breakout(candidate):
            continue
        if not candidate_matches_zone(digash, candidate, params):
            continue
        gap_pct, overlap_ratio = zone_relation(digash, candidate)
        time_diff_min = abs(int(candidate["_close_ms"]) - int(digash["_timestamp_ms"])) / 60_000
        score = float(candidate.get("score") or 0)
        rank = (time_diff_min, gap_pct, -overlap_ratio, -score)
        if best is None or rank < best[0]:
            item = public_candidate(candidate)
            item["time_diff_min"] = round(time_diff_min, 4)
            item["zone_gap_pct"] = round(gap_pct, 5)
            item["zone_overlap_ratio"] = round(overlap_ratio, 5)
            best = (rank, item)
    return best[1] if best else None


def match_dataset(
    digash_rows: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    params: MatchParams,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    indexed = prepare_candidates(candidates)
    rows: list[dict[str, Any]] = []
    alignment_counts: Counter[str] = Counter()
    loose_count = 0
    confirmed_count = 0

    for digash in digash_rows:
        loose = best_match(indexed, digash, params, confirmed_only=False)
        confirmed = best_match(indexed, digash, params, confirmed_only=True)
        if confirmed:
            alignment = "breakout_confirmed_aligned"
            confirmed_count += 1
        elif loose:
            alignment = "classification_mismatch_zone_found_not_confirmed_breakout"
        else:
            alignment = "not_found"
        if loose:
            loose_count += 1
        alignment_counts[alignment] += 1
        rows.append(
            {
                "digash": public_digash(digash),
                "loose_match": loose,
                "confirmed_breakout_match": confirmed,
                "alignment": alignment,
            }
        )

    total = len(digash_rows)
    summary = {
        "loose": {
            "matched": loose_count,
            "total": total,
            "recall_pct": round(loose_count / total * 100, 2) if total else 0.0,
        },
        "confirmed_breakout_aligned": {
            "matched": confirmed_count,
            "total": total,
            "recall_pct": round(confirmed_count / total * 100, 2) if total else 0.0,
        },
        "alignment_counts": dict(alignment_counts),
    }
    return summary, rows


def public_digash(digash: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in digash.items() if not key.startswith("_")}


def signal_key(signal: dict[str, Any]) -> str:
    key = signal.get("key")
    if key:
        return str(key)
    zone = f"{float(signal['zone_low']):.12g}-{float(signal['zone_high']):.12g}"
    state = signal.get("type") or ("breakout" if signal.get("is_breakout_type") else "test")
    return f"{signal['symbol']}:{signal['timeframe']}:{signal['side']}:{zone}:{state}:{signal.get('confidence', 'confirmed')}"


def allowed_by_publish_filter(signal: dict[str, Any], args: argparse.Namespace) -> bool:
    if signal.get("confidence") == "confirmed":
        return True
    if signal.get("type") == "early_breakout":
        return bool(args.enable_early_breakout) and bool(args.send_unconfirmed) and float(signal.get("score") or 0) >= args.min_early_breakout_score
    if not args.send_unconfirmed:
        return False
    if float(signal.get("score") or 0) < args.min_unconfirmed_score:
        return False
    touches_by_kind = json.loads(args.unconfirmed_touches_by_level_kind)
    required_touches = int(touches_by_kind.get(str(signal.get("level_kind")), args.unconfirmed_default_touches))
    return int(signal.get("touches") or 0) >= required_touches


def apply_publication_policy(signals: list[dict[str, Any]], args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[int, str]]:
    rows = [dict(signal, id=index, key=signal_key(signal)) for index, signal in enumerate(signals)]
    by_time: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for signal in rows:
        by_time[int(signal["close_ms"])].append(signal)

    cooldown_ms = int(args.alert_cooldown_minutes * 60_000)
    pause_ms = int(args.symbol_analysis_pause_minutes * 60_000)
    sent_keys: dict[str, int] = {}
    paused_until: dict[str, int] = {}
    statuses: dict[int, str] = {}
    published: list[dict[str, Any]] = []

    for close_ms in sorted(by_time):
        candidates: list[dict[str, Any]] = []
        for signal in by_time[close_ms]:
            pause_key = signal_key(signal) if args.pause_scope == "signal_key" else str(signal["symbol"])
            if pause_ms > 0 and paused_until.get(pause_key, 0) > close_ms:
                statuses[int(signal["id"])] = f"{args.pause_scope}_pause"
                continue
            if not allowed_by_publish_filter(signal, args):
                statuses[int(signal["id"])] = "allowed_filter"
                continue
            candidates.append(signal)

        candidates.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
        kept = candidates
        if args.max_signals_per_scan and len(candidates) > args.max_signals_per_scan:
            kept = candidates[: args.max_signals_per_scan]
            for signal in candidates[args.max_signals_per_scan :]:
                statuses[int(signal["id"])] = "batch_limit"

        sent_pause_keys: set[str] = set()
        for signal in kept:
            key = signal_key(signal)
            last_sent = sent_keys.get(key)
            if last_sent is not None and close_ms - last_sent < cooldown_ms:
                statuses[int(signal["id"])] = "cooldown"
                continue
            sent_keys[key] = close_ms
            statuses[int(signal["id"])] = "published"
            published.append(public_candidate(signal))
            pause_key = key if args.pause_scope == "signal_key" else str(signal["symbol"])
            sent_pause_keys.add(pause_key)
        if pause_ms > 0:
            for pause_key in sent_pause_keys:
                paused_until[pause_key] = close_ms + pause_ms

    return published, statuses


def parse_sensitivity(value: str) -> list[MatchParams]:
    if not value:
        return []
    result: list[MatchParams] = []
    for item in value.split(","):
        window, gap = item.split(":", 1)
        result.append(MatchParams(float(window), float(gap)))
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    params = MatchParams(args.time_window_min, args.zone_gap_pct)
    digash = prepare_digash(load_jsonl(args.digash))
    detector = load_jsonl(args.detector)

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    detector_summary, detector_rows = match_dataset(digash, detector, params)
    write_jsonl(out_dir / "detector_matches.jsonl", detector_rows)

    result: dict[str, Any] = {
        "method": {
            "time_window_min": params.time_window_min,
            "zone_gap_pct": params.zone_gap_pct,
            "zone_rule": "candidate matches when same symbol+side and zone intervals overlap or gap <= zone_gap_pct of Digash zone midpoint",
            "confirmed_rule": "confirmed recall requires candidate type=breakout and confidence=confirmed",
        },
        "detector": detector_summary,
    }

    published_rows: list[dict[str, Any]] | None = None
    statuses: dict[int, str] | None = None
    if args.published:
        published_rows = load_jsonl(args.published)
    elif args.replay_policy:
        published_rows, statuses = apply_publication_policy(detector, args)
        write_jsonl(out_dir / "published_replayed.jsonl", published_rows)

    if published_rows is not None:
        published_summary, published_matches = match_dataset(digash, published_rows, params)
        write_jsonl(out_dir / "published_matches.jsonl", published_matches)
        result["published"] = published_summary

    if statuses is not None:
        result["policy_replay"] = {
            "status_counts": dict(Counter(statuses.values())),
            "pause_scope": args.pause_scope,
            "max_signals_per_scan": args.max_signals_per_scan,
            "alert_cooldown_minutes": args.alert_cooldown_minutes,
            "symbol_analysis_pause_minutes": args.symbol_analysis_pause_minutes,
        }
        status_rows = []
        for index, signal in enumerate(detector):
            row = dict(signal)
            row["publication_status"] = statuses.get(index, "unknown")
            status_rows.append(row)
        write_jsonl(out_dir / "detector_with_publication_status.jsonl", status_rows)

    sensitivity = []
    for item in parse_sensitivity(args.sensitivity):
        entry: dict[str, Any] = {
            "time_window_min": item.time_window_min,
            "zone_gap_pct": item.zone_gap_pct,
            "detector": match_dataset(digash, detector, item)[0],
        }
        if published_rows is not None:
            entry["published"] = match_dataset(digash, published_rows, item)[0]
        sensitivity.append(entry)
    if sensitivity:
        result["sensitivity"] = sensitivity

    summary_path = out_dir / "recall_match_summary.json"
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Canonical Digash recall matcher.")
    parser.add_argument("--digash", type=Path, required=True)
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--published", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--time-window-min", type=float, default=DEFAULT_TIME_WINDOW_MIN)
    parser.add_argument("--zone-gap-pct", type=float, default=DEFAULT_ZONE_GAP_PCT)
    parser.add_argument("--sensitivity", default="")
    parser.add_argument("--replay-policy", action="store_true")
    parser.add_argument("--send-unconfirmed", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--enable-early-breakout", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--min-unconfirmed-score", type=float, default=60.83)
    parser.add_argument("--min-early-breakout-score", type=float, default=60.83)
    parser.add_argument("--unconfirmed-default-touches", type=int, default=2)
    parser.add_argument(
        "--unconfirmed-touches-by-level-kind",
        default=json.dumps(DEFAULT_UNCONFIRMED_TOUCHES_BY_LEVEL_KIND, separators=(",", ":")),
    )
    parser.add_argument("--max-signals-per-scan", type=int, default=20)
    parser.add_argument("--alert-cooldown-minutes", type=int, default=5)
    parser.add_argument("--symbol-analysis-pause-minutes", type=int, default=5)
    parser.add_argument("--pause-scope", choices=("signal_key", "symbol"), default="signal_key")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
