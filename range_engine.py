"""
range_engine.py — Range trading bot signal detection.

Fires when H4 ADX < RANGE_ADX_MAX (20), meaning gold is consolidating.
Identifies the current range boundaries, then enters at the edges with
confirmation. Session filter blocks London and NY opens (most common
breakout windows). Breakout detection via candle close beyond range.

ADX gate summary:
  H4 ADX > 25  →  trend bot fires, range bot off  (handled in signal_engine)
  H4 ADX < 20  →  range bot fires, trend bot off
  H4 ADX 20-25 →  neither fires (no man's land)
"""
from dataclasses import dataclass
from datetime import datetime, timezone

import config
import indicators as ind
import price_action as pa
import data_client
import news_filter


@dataclass
class RangeSignal:
    symbol:      str
    action:      str       # "BUY" | "SELL"
    entry:       float
    sl:          float
    tp:          float
    lots:        float
    rr:          float
    range_low:   float
    range_high:  float
    range_width: float
    pattern:     str
    adx:         float
    sl_pts:      float
    tp_pts:      float


def _is_range_session() -> bool:
    """Return False during London and NY opens — most common breakout windows."""
    now = datetime.now(timezone.utc)
    hm  = now.hour * 100 + now.minute
    if 700  <= hm < 900:  return False   # London open 07:00–09:00 UTC
    if 1300 <= hm < 1530: return False   # NY open    13:00–15:30 UTC
    return True


def _find_range(df) -> tuple[float, float] | None:
    """
    Scan last RANGE_LOOKBACK closed bars for a valid range.
    Returns (range_low, range_high) or None if no valid range exists.

    Valid range requires:
    - Width between RANGE_MIN_WIDTH and RANGE_MAX_WIDTH
    - At least RANGE_MIN_BARS bars fully contained within the boundary
    - At least RANGE_MIN_TOUCHES touches on each boundary
    """
    lookback = min(config.RANGE_LOOKBACK, len(df) - 2)
    if lookback < config.RANGE_MIN_BARS:
        return None

    window = df.iloc[-(lookback + 1):-1]   # exclude the forming candle
    hi = float(window["high"].max())
    lo = float(window["low"].min())
    width = hi - lo

    if width < config.RANGE_MIN_WIDTH or width > config.RANGE_MAX_WIDTH:
        return None

    # Most bars must sit fully inside the range
    inside = int(((window["high"] <= hi + 2) & (window["low"] >= lo - 2)).sum())
    if inside < config.RANGE_MIN_BARS:
        return None

    # Both boundaries must be tested multiple times
    hi_touches = int((window["high"] >= hi - 3).sum())
    lo_touches = int((window["low"]  <= lo + 3).sum())
    if hi_touches < config.RANGE_MIN_TOUCHES or lo_touches < config.RANGE_MIN_TOUCHES:
        return None

    return lo, hi


def _lot_size(sl_distance: float) -> float:
    risk_usd = config.ACCOUNT_BALANCE * (config.RANGE_RISK_PCT / 100)
    return data_client.calc_lot_size("XAUUSD", sl_distance, risk_usd)


def evaluate(symbol: str) -> RangeSignal | None:
    """
    Evaluate range conditions for symbol. Returns a RangeSignal if entry
    conditions are met, otherwise None.
    """
    if not config.USE_RANGE_BOT:
        return None

    # Session gate — block during high-volatility open windows
    if not _is_range_session():
        print(f"  [{symbol}] Range: outside safe session (London/NY open blocked)")
        return None

    # News gate
    blocked, msg = news_filter.is_news_window()
    if blocked:
        print(f"  [{symbol}] Range: news block — {msg}")
        return None

    # Fetch data
    try:
        df    = ind.enrich(data_client.get_bars(symbol, config.PRIMARY_TF))
        df_h4 = ind.enrich(data_client.get_bars(symbol, "H4", 50))
        tick  = data_client.get_tick(symbol)
    except Exception as e:
        print(f"  [{symbol}] Range: data error — {e}")
        return None

    if len(df) < config.RANGE_LOOKBACK + 5:
        return None

    # H4 ADX gate — range mode only when market is genuinely consolidating
    h4_adx = ind.adx_value(df_h4)
    if h4_adx >= config.RANGE_ADX_MAX:
        print(f"  [{symbol}] Range: H4 ADX {h4_adx:.1f} >= {config.RANGE_ADX_MAX} — trending, range bot off")
        return None

    # Find valid range
    result = _find_range(df)
    if result is None:
        print(f"  [{symbol}] Range: no valid range found | ADX {h4_adx:.1f}")
        return None

    range_low, range_high = result
    range_width = range_high - range_low
    price = tick["ask"]

    print(f"  [{symbol}] Range: {range_low:.2f} — {range_high:.2f} ({range_width:.1f}pts) | ADX {h4_adx:.1f}")

    # Reject mid-range — only enter at the edges (outer third each side)
    if range_low + range_width * 0.33 < price < range_high - range_width * 0.33:
        print(f"  [{symbol}] Range: price {price:.2f} in mid-range — wait for edge")
        return None

    rsi       = ind.rsi_value(df)
    macd_bull = ind.macd_bullish(df)
    macd_bear = ind.macd_bearish(df)

    action = pattern = None
    sl = tp = entry = 0.0

    # ── BUY at range low ──────────────────────────────────────────────────────
    if price <= range_low + config.RANGE_ENTRY_ZONE:
        candle_bull = pa.bullish_pattern(df)
        rsi_ok = rsi < 40
        if not candle_bull and not macd_bull and not rsi_ok:
            print(f"  [{symbol}] Range: at LOW {range_low:.2f} — no bull confirmation | RSI {rsi:.1f}")
            return None
        action  = "BUY"
        entry   = tick["ask"]
        sl      = range_low - config.RANGE_SL_PTS
        tp      = range_high - 5
        pattern = candle_bull or ("Range MACD" if macd_bull else "Range RSI<40")

    # ── SELL at range high ────────────────────────────────────────────────────
    elif price >= range_high - config.RANGE_ENTRY_ZONE:
        candle_bear = pa.bearish_pattern(df)
        rsi_ok = rsi > 60
        if not candle_bear and not macd_bear and not rsi_ok:
            print(f"  [{symbol}] Range: at HIGH {range_high:.2f} — no bear confirmation | RSI {rsi:.1f}")
            return None
        action  = "SELL"
        entry   = tick["bid"]
        sl      = range_high + config.RANGE_SL_PTS
        tp      = range_low + 5
        pattern = candle_bear or ("Range MACD" if macd_bear else "Range RSI>60")

    else:
        return None

    sl_pts = round(abs(entry - sl), 2)
    tp_pts = round(abs(tp - entry), 2)

    if tp_pts < 10:
        print(f"  [{symbol}] Range: TP only {tp_pts:.1f}pts — skip")
        return None

    lots = _lot_size(sl_pts)
    rr   = round(tp_pts / sl_pts, 2) if sl_pts > 0 else 0

    return RangeSignal(
        symbol      = symbol,
        action      = action,
        entry       = round(entry, 2),
        sl          = round(sl, 2),
        tp          = round(tp, 2),
        lots        = lots,
        rr          = rr,
        range_low   = round(range_low, 2),
        range_high  = round(range_high, 2),
        range_width = round(range_width, 1),
        pattern     = pattern,
        adx         = round(h4_adx, 1),
        sl_pts      = sl_pts,
        tp_pts      = tp_pts,
    )
