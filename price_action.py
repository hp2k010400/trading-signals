import pandas as pd
import numpy as np
import config


# ── Support / Resistance levels ───────────────────────────────────────────────

def daily_pivots(df: pd.DataFrame) -> dict:
    """Classic pivot points from the previous completed day's candle."""
    daily = df.resample("D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    if len(daily) < 2:
        return {}
    prev = daily.iloc[-2]
    H, L, C = float(prev["high"]), float(prev["low"]), float(prev["close"])
    PP = (H + L + C) / 3
    return {
        "PP": PP,
        "R1": 2 * PP - L,
        "R2": PP + (H - L),
        "R3": H + 2 * (PP - L),
        "S1": 2 * PP - H,
        "S2": PP - (H - L),
        "S3": L - 2 * (H - PP),
    }


def round_number_levels(price: float, count: int = 6) -> list[float]:
    """Return the nearest round-number levels above and below price."""
    step = config.ROUND_NUMBER_STEP
    base = round(price / step) * step
    levels = [base + step * i for i in range(-count, count + 1)]
    return sorted(set(levels))


def swing_levels(df: pd.DataFrame, window: int = 10) -> tuple[list, list]:
    """Swing highs and lows from recent price action."""
    highs, lows = [], []
    h = df["high"].values
    l = df["low"].values
    for i in range(window, len(h) - window):
        if h[i] == max(h[i - window: i + window]):
            highs.append(float(h[i]))
        if l[i] == min(l[i - window: i + window]):
            lows.append(float(l[i]))
    return highs[-5:], lows[-5:]   # keep only 5 most recent


def all_levels(df: pd.DataFrame) -> list[float]:
    """Combine pivot points, round numbers and swing levels into one sorted list."""
    price = float(df["close"].iloc[-2])
    levels = set()

    pivots = daily_pivots(df)
    levels.update(pivots.values())

    levels.update(round_number_levels(price))

    highs, lows = swing_levels(df)
    levels.update(highs)
    levels.update(lows)

    return sorted(levels)


def find_entry_level(price: float, levels: list[float], tolerance: float) -> float | None:
    """Return the nearest S/R level within tolerance of price, or None."""
    candidates = [l for l in levels if abs(price - l) <= tolerance]
    if not candidates:
        return None
    return min(candidates, key=lambda l: abs(price - l))


def find_tp(current_price: float, direction: str, levels: list[float], min_dist: float | None = None) -> float | None:
    """
    Find the nearest S/R level in the trade direction at least min_dist away.
    Returns the level minus TP_BUFFER (to close just before resistance hits).
    """
    if min_dist is None:
        min_dist = config.SL_POINTS + config.TP_BUFFER
    if direction == "bull":
        candidates = [l for l in levels if l > current_price + min_dist]
        return (min(candidates) - config.TP_BUFFER) if candidates else None
    else:
        candidates = [l for l in levels if l < current_price - min_dist]
        return (max(candidates) + config.TP_BUFFER) if candidates else None


# ── Candlestick patterns ──────────────────────────────────────────────────────

def _body(row) -> float:
    return abs(row["close"] - row["open"])

def _range(row) -> float:
    return row["high"] - row["low"]

def _lower_wick(row) -> float:
    return min(row["open"], row["close"]) - row["low"]

def _upper_wick(row) -> float:
    return row["high"] - max(row["open"], row["close"])


def is_bullish_engulfing(df: pd.DataFrame) -> bool:
    prev, curr = df.iloc[-3], df.iloc[-2]
    return (prev["close"] < prev["open"] and curr["close"] > curr["open"]
            and curr["open"] < prev["close"] and curr["close"] > prev["open"])


def is_bearish_engulfing(df: pd.DataFrame) -> bool:
    prev, curr = df.iloc[-3], df.iloc[-2]
    return (prev["close"] > prev["open"] and curr["close"] < curr["open"]
            and curr["open"] > prev["close"] and curr["close"] < prev["open"])


def is_bullish_pin_bar(df: pd.DataFrame) -> bool:
    row = df.iloc[-2]
    rng = _range(row)
    return rng > 0 and _lower_wick(row) >= rng * 0.6 and _body(row) <= rng * 0.3


def is_bearish_pin_bar(df: pd.DataFrame) -> bool:
    row = df.iloc[-2]
    rng = _range(row)
    return rng > 0 and _upper_wick(row) >= rng * 0.6 and _body(row) <= rng * 0.3


def bullish_pattern(df: pd.DataFrame) -> str | None:
    if is_bullish_engulfing(df): return "Bullish Engulfing"
    if is_bullish_pin_bar(df):   return "Bullish Pin Bar"
    return None


def bearish_pattern(df: pd.DataFrame) -> str | None:
    if is_bearish_engulfing(df): return "Bearish Engulfing"
    if is_bearish_pin_bar(df):   return "Bearish Pin Bar"
    return None
