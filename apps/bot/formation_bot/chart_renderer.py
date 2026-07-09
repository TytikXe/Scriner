from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from .formations import format_price
from .models import BreakoutSignal, Candle


BACKGROUND = (10, 12, 22)
PANEL = (16, 19, 32)
GRID = (36, 42, 58)
TEXT = (238, 242, 250)
MUTED = (125, 136, 157)
GREEN = (22, 190, 130)
GREEN_ZONE = (14, 130, 95, 82)
RED = (245, 77, 109)
RED_ZONE = (160, 42, 65, 82)
BLUE = (63, 135, 255)


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    font_names = ("arialbd.ttf", "segoeuib.ttf") if bold else ("arial.ttf", "segoeui.ttf")
    search_roots = (
        Path("C:/Windows/Fonts"),
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/truetype/liberation2"),
    )
    for root in search_roots:
        for name in font_names:
            path = root / name
            if path.exists():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _fit_font(text: str, max_width: int, start_size: int, min_size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    for size in range(start_size, min_size - 1, -1):
        font = _font(size, bold=bold)
        if ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(text, font=font) <= max_width:
            return font
    return _font(min_size, bold=bold)


def _price_bounds(candles: Sequence[Candle], signal: BreakoutSignal) -> tuple[float, float]:
    low = min(min(candle.low for candle in candles), signal.zone_lower)
    high = max(max(candle.high for candle in candles), signal.zone_upper)
    if high <= low:
        high = low + max(abs(low) * 0.01, 1.0)
    padding = (high - low) * 0.12
    return low - padding, high + padding


def _visible_candle_window(
    candles: Sequence[Candle],
    signal: BreakoutSignal,
    max_candles: int,
) -> tuple[list[Candle], int]:
    total = len(candles)
    pivot_indexes = [index for index, _ in signal.pivot_points if 0 <= index < total]
    if pivot_indexes:
        fitting_pivots = [index for index in pivot_indexes if total - index <= max_candles - 12]
        if fitting_pivots:
            first_pivot = min(fitting_pivots)
            start = max(0, first_pivot - min(48, max_candles // 6))
            if total - start > max_candles:
                start = max(0, total - max_candles)
        else:
            start = max(0, total - max_candles)
    else:
        start = max(0, total - max_candles)
    return list(candles[start:]), start


def _level_label_prices(signal: BreakoutSignal, tick_size: float) -> list[float]:
    if abs(signal.zone_upper - signal.zone_lower) <= max(tick_size / 2, 1e-12):
        return [signal.zone_upper if signal.side == "resistance" else signal.zone_lower]
    return sorted((signal.zone_upper, signal.zone_lower), reverse=True)


def _draw_price_labels(
    draw: ImageDraw.ImageDraw,
    y_for_price,
    price_min: float,
    price_max: float,
    tick_size: float,
    right: int,
    chart_top: int,
    chart_bottom: int,
) -> None:
    label_font = _font(16)
    for index in range(6):
        price = price_min + (price_max - price_min) * index / 5
        y = y_for_price(price)
        draw.line([(64, y), (right, y)], fill=GRID, width=1)
        text = format_price(price, tick_size)
        draw.text((right + 10, y - 9), text, fill=MUTED, font=label_font)

    draw.line([(64, chart_top), (64, chart_bottom)], fill=GRID, width=1)
    draw.line([(right, chart_top), (right, chart_bottom)], fill=GRID, width=1)


def render_signal_chart(
    candles: Sequence[Candle],
    signal: BreakoutSignal,
    tick_size: float,
    *,
    width: int = 900,
    height: int = 620,
    max_candles: int = 340,
) -> bytes:
    recent, recent_start_index = _visible_candle_window(candles, signal, max_candles)
    if len(recent) < 2:
        raise ValueError("at least two candles are required to render a chart")

    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    chart_left = 64
    chart_right = width - 116
    chart_top = 96
    chart_bottom = height - 164
    volume_top = chart_bottom + 14
    volume_bottom = height - 84
    chart_width = chart_right - chart_left
    chart_height = chart_bottom - chart_top

    draw.rounded_rectangle((18, 18, width - 18, height - 18), radius=12, fill=PANEL)

    title_font = _fit_font(signal.symbol, width - 330, 26, 18, bold=True)
    small_font = _font(16)
    metric_font = _font(15)
    price_text = format_price(signal.price, tick_size)
    price_font = _fit_font(price_text, 190, 24, 16, bold=True)
    swing_kind = "swing high" if signal.side == "resistance" else "swing low"
    is_level_zone = signal.touches > 1 or abs(signal.zone_upper - signal.zone_lower) > max(tick_size / 2, 1e-12)
    setup_kind = "level" if is_level_zone else swing_kind
    signal_kind = "breakout" if signal.is_breakout_type else "probe"
    draw.text((36, 30), f"{signal.symbol}", fill=TEXT, font=title_font)
    timeframe_width = int(draw.textlength(signal.timeframe, font=small_font)) + 24
    draw.rounded_rectangle((36, 62, 36 + timeframe_width, 86), radius=6, fill=(26, 76, 150))
    draw.text((48, 64), signal.timeframe, fill=TEXT, font=small_font)
    draw.text((48 + timeframe_width, 64), f"Binance Futures · {setup_kind} {signal_kind}", fill=MUTED, font=small_font)
    price_width = int(draw.textlength(price_text, font=price_font))
    draw.text((width - 36 - price_width, 32), price_text, fill=TEXT, font=price_font)

    price_min, price_max = _price_bounds(recent, signal)

    def y_for_price(price: float) -> int:
        return int(chart_top + (price_max - price) / (price_max - price_min) * chart_height)

    _draw_price_labels(draw, y_for_price, price_min, price_max, tick_size, chart_right, chart_top, chart_bottom)

    zone_color = GREEN if signal.side == "resistance" else RED
    zone_fill = GREEN_ZONE if signal.side == "resistance" else RED_ZONE
    zone_top = y_for_price(signal.zone_upper)
    zone_bottom = y_for_price(signal.zone_lower)
    if zone_bottom - zone_top < 6:
        middle = (zone_top + zone_bottom) // 2
        zone_top = middle - 3
        zone_bottom = middle + 3

    max_volume = max(candle.volume for candle in recent) or 1.0
    slot = chart_width / len(recent)
    body_width = max(1, min(9, int(slot * 0.64)))
    wick_width = 1 if slot < 5 else 2

    visible_pivots = [
        (index, price)
        for index, price in signal.pivot_points
        if recent_start_index <= index < recent_start_index + len(recent)
    ]
    level_start_x = chart_left
    if visible_pivots:
        first_visible_pivot = min(index for index, _ in visible_pivots)
        level_start_x = int(chart_left + (first_visible_pivot - recent_start_index) * slot + slot / 2)
        level_start_x = max(chart_left, min(chart_right - 12, level_start_x))

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle((level_start_x, zone_top, chart_right, zone_bottom), fill=zone_fill)
    overlay_draw.line((level_start_x, zone_top, chart_right, zone_top), fill=(*zone_color, 225), width=2)
    overlay_draw.line((level_start_x, zone_bottom, chart_right, zone_bottom), fill=(*zone_color, 225), width=2)
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(image)

    for index, candle in enumerate(recent):
        x = int(chart_left + index * slot + slot / 2)
        up = candle.close >= candle.open
        color = GREEN if up else RED

        high_y = y_for_price(candle.high)
        low_y = y_for_price(candle.low)
        open_y = y_for_price(candle.open)
        close_y = y_for_price(candle.close)
        draw.line((x, high_y, x, low_y), fill=color, width=wick_width)

        body_top = min(open_y, close_y)
        body_bottom = max(open_y, close_y)
        if body_bottom - body_top < 2:
            draw.line((x - body_width // 2, body_top, x + body_width // 2, body_top), fill=color, width=max(1, body_width))
        else:
            draw.rectangle((x - body_width // 2, body_top, x + body_width // 2, body_bottom), fill=color)

        volume_height = int((candle.volume / max_volume) * (volume_bottom - volume_top))
        volume_color = (35, 109, 84) if up else (112, 45, 61)
        draw.rectangle(
            (
                x - max(1, body_width // 2),
                volume_bottom - volume_height,
                x + max(1, body_width // 2),
                volume_bottom,
            ),
            fill=volume_color,
        )

    draw.line((level_start_x, zone_top, chart_right, zone_top), fill=zone_color, width=2)
    draw.line((level_start_x, zone_bottom, chart_right, zone_bottom), fill=zone_color, width=2)

    price_label_ys: list[int] = []
    if visible_pivots:
        for pivot_index, pivot_price in visible_pivots:
            pivot_x = int(chart_left + (pivot_index - recent_start_index) * slot + slot / 2)
            pivot_y = y_for_price(pivot_price)
            draw.ellipse((pivot_x - 4, pivot_y - 4, pivot_x + 4, pivot_y + 4), fill=zone_color)
            draw.line((pivot_x - 8, pivot_y, pivot_x + 8, pivot_y), fill=TEXT, width=1)

    for pivot_price in _level_label_prices(signal, tick_size):
        label = format_price(pivot_price, tick_size)
        label_w = int(draw.textlength(label, font=small_font)) + 18
        label_y = max(chart_top + 15, min(chart_bottom - 15, y_for_price(pivot_price)))
        for _ in range(6):
            if not any(abs(label_y - used_y) < 28 for used_y in price_label_ys):
                break
            step = 28 if label_y < (chart_top + chart_bottom) // 2 else -28
            next_y = max(chart_top + 15, min(chart_bottom - 15, label_y + step))
            if next_y == label_y:
                break
            label_y = next_y
        price_label_ys.append(label_y)
        draw.rounded_rectangle((chart_right - label_w, label_y - 13, chart_right, label_y + 13), radius=5, fill=zone_color)
        draw.text((chart_right - label_w + 9, label_y - 10), label, fill=TEXT, font=small_font)

    latest_x = int(chart_left + (len(recent) - 1) * slot + slot / 2)
    latest_y = y_for_price(signal.price)
    draw.line((chart_left, latest_y, chart_right, latest_y), fill=(68, 78, 98), width=1)
    draw.ellipse((latest_x - 5, latest_y - 5, latest_x + 5, latest_y + 5), fill=BLUE)

    if not is_level_zone:
        zone_text = format_price(signal.zone_upper if signal.side == "resistance" else signal.zone_lower, tick_size)
        zone_title = swing_kind.title()
    else:
        zone_text = f"{format_price(signal.zone_lower, tick_size)} - {format_price(signal.zone_upper, tick_size)}"
        zone_title = "Level zone"
    footer_y = height - 58
    draw.text((chart_left, footer_y), f"{zone_title}: {zone_text}", fill=zone_color, font=small_font)
    metrics_y = height - 34
    draw.text((chart_left, metrics_y), f"NATR {signal.natr_pct:.2f}%", fill=(245, 188, 66), font=metric_font)
    draw.text((chart_left + 140, metrics_y), f"Touches {signal.touches}", fill=MUTED, font=metric_font)
    draw.text((chart_left + 260, metrics_y), f"Score {signal.score:.0f}", fill=MUTED, font=metric_font)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
