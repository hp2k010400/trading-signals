import pandas as pd
import numpy as np


# ── Support / Resistance ──────────────────────────────────────────────────────

def pivot_levels(df: pd.DataFrame, lookback: int = 50) -> dict:
    """
    Classic pivot point levels from the most recent completed session bar.
    Returns dict with keys: P, R1, R2, S1, S2.
    """
    window = df.iloc[-lookback - 1 : -1]
    H = window["high"].max()
    L = window["low"].min()
    C = float(df["close"].iloc[-2])
    P  = (H + L + C) / 3
    R1 = 2 * P - L
    S1 = 2 * P - H
    R2 = P + (H - L)
    S2 = P - (H - L)
    return {"P": P, "R1": R1, "R2": R2, "S1": S1, "S2": S2}


def near_level(price: float, levels: dict, tolerance_pct: float = 0.0015) -> str | None:
    """
    Returns the level name if price is within tolerance of a pivot level,
    else None.  tolerance_pct = 0.15% of price by default.
    """
    tol = price * tolerance_pct
    for name, lvl in levels.items():
        if abs(price - lvl) <= tol:
            return name
    return None


def swing_levels(df: pd.DataFrame, window: int = 20) -> tuple[list, list]:
    """Return (swing_highs, swing_lows) as lists of prices from recent bars."""
    highs, lows = [], []
    closes = df["close"].values
    for i in range(window, len(closes) - window):
        if closes[i] == max(closes[i - window : i + window]):
            highs.append(closes[i])
        if closes[i] == min(closes[i - window : i + window]):
            lows.append(closes[i])
    return highs, lows


# ── Candlestick Patterns ──────────────────────────────────────────────────────

def _body(row) -> float:
    return abs(row["close"] - row["open"])


def _range(row) -> float:
    return row["high"] - row["low"]


def _upper_wick(row) -> float:
    return row["high"] - max(row["open"], row["close"])


def _lower_wick(row) -> float:
    return min(row["open"], row["close"]) - row["low"]


def is_bullish_engulfing(df: pd.DataFrame) -> bool:
    prev = df.iloc[-3]
    curr = df.iloc[-2]
    return (
        prev["close"] < prev["open"]           # prev bearish
        and curr["close"] > curr["open"]        # curr bullish
        and curr["open"]  < prev["close"]       # opens below prev close
        and curr["close"] > prev["open"]        # closes above prev open
    )


def is_bearish_engulfing(df: pd.DataFrame) -> bool:
    prev = df.iloc[-3]
    curr = df.iloc[-2]
    return (
        prev["close"] > prev["open"]
        and curr["close"] < curr["open"]
        and curr["open"]  > prev["close"]
        and curr["close"] < prev["open"]
    )


def is_bullish_pin_bar(df: pd.DataFrame) -> bool:
    """Long lower wick, small body near top — rejection of lower prices."""
    row = df.iloc[-2]
    body  = _body(row)
    rng   = _range(row)
    lower = _lower_wick(row)
    upper = _upper_wick(row)
    if rng == 0:
        return False
    return (
        lower >= rng * 0.6
        and body <= rng * 0.3
        and upper <= rng * 0.15
    )


def is_bearish_pin_bar(df: pd.DataFrame) -> bool:
    """Long upper wick, small body near bottom — rejection of higher prices."""
    row = df.iloc[-2]
    body  = _body(row)
    rng   = _range(row)
    upper = _upper_wick(row)
    lower = _lower_wick(row)
    if rng == 0:
        return False
    return (
        upper >= rng * 0.6
        and body <= rng * 0.3
        and lower <= rng * 0.15
    )


def is_doji(df: pd.DataFrame) -> bool:
    row = df.iloc[-2]
    rng = _range(row)
    return rng > 0 and _body(row) / rng < 0.1


def bullish_pattern(df: pd.DataFrame) -> str | None:
    if is_bullish_engulfing(df):
        return "Bullish Engulfing"
    if is_bullish_pin_bar(df):
        return "Bullish Pin Bar"
    return None


def bearish_pattern(df: pd.DataFrame) -> str | None:
    if is_bearish_engulfing(df):
        return "Bearish Engulfing"
    if is_bearish_pin_bar(df):
        return "Bearish Pin Bar"
    return None


# ── Trend structure ───────────────────────────────────────────────────────────

def higher_highs_lows(df: pd.DataFrame, n: int = 3) -> bool:
    """True if last n swing highs and lows are ascending."""
    highs, lows = swing_levels(df, window=5)
    return len(highs) >= n and len(lows) >= n and all(
        highs[-i] > highs[-i - 1] for i in range(1, n)
    ) and all(
        lows[-i] > lows[-i - 1] for i in range(1, n)
    )


def lower_highs_lows(df: pd.DataFrame, n: int = 3) -> bool:
    """True if last n swing highs and lows are descending."""
    highs, lows = swing_levels(df, window=5)
    return len(highs) >= n and len(lows) >= n and all(
        highs[-i] < highs[-i - 1] for i in range(1, n)
    ) and all(
        lows[-i] < lows[-i - 1] for i in range(1, n)
    )
