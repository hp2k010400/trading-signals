"""
Signal engine — rebuilt to match the Gold Signals group strategy:

  1. Identify a key S/R level as the TP target
  2. Enter when trend + momentum + candle pattern confirm direction
  3. Allow up to 3 DCA entries toward the same target
  4. Fixed 15-point SL on every entry
  5. TP is the S/R level minus a small buffer
"""
from dataclasses import dataclass
import config
import indicators as ind
import price_action as pa
import news_filter
import risk_manager
import data_client
import targets as tgt


@dataclass
class Signal:
    symbol:      str
    action:      str          # "BUY" | "SELL"
    entry:       float
    sl:          float
    tp:          float
    lots:        float
    rr:          float
    pattern:     str
    entry_num:   int          # 1 = first entry, 2/3 = DCA
    tp_points:   float
    sl_points:   float = config.SL_POINTS


def _lot_size(risk_usd: float) -> float:
    if config.FIXED_LOT is not None:
        return config.FIXED_LOT
    risk_per_lot = config.SL_POINTS * 100
    lot = risk_usd / risk_per_lot
    lot = round(round(lot / 0.01) * 0.01, 2)
    return max(config.MIN_LOT, min(config.MAX_LOT, lot))


def _rr(entry, sl, tp) -> float:
    risk   = abs(entry - sl)
    reward = abs(tp - entry)
    return round(reward / risk, 2) if risk > 0 else 0


def evaluate(symbol: str) -> Signal | None:
    # ── News & risk gates ─────────────────────────────────────────────────────
    blocked, news_msg = news_filter.is_news_window()
    if blocked:
        print(f"  [{symbol}] News: {news_msg}")
        return None

    allowed, risk_msg = risk_manager.is_trading_allowed()
    if not allowed:
        print(f"  [{symbol}] Risk: {risk_msg}")
        return None

    # ── Fetch data ────────────────────────────────────────────────────────────
    try:
        df = ind.enrich(data_client.get_bars(symbol, config.PRIMARY_TF))
        tick = data_client.get_tick(symbol)
    except Exception as e:
        print(f"  [{symbol}] Data error: {e}")
        return None

    if len(df) < 50:
        return None

    price = tick["ask"]   # use ask as reference; SL/TP calc same either side

    # ── Check if an active target needs a DCA entry ───────────────────────────
    active = tgt.get(symbol)

    if active:
        # Check if TP has been hit
        if active.tp_hit(price):
            print(f"  [{symbol}] TP hit at {active.tp:.2f} — clearing target")
            tgt.clear(symbol)
            return None

        # Check if trend is still valid for existing target
        trend = ind.trend_direction(df)
        active_trend = "bull" if active.direction == "bull" else "bear"
        if trend != active.direction:
            print(f"  [{symbol}] Trend reversed — clearing target")
            tgt.clear(symbol)
            return None

        # Fire a DCA entry if price has pulled back
        if active.needs_dca(price) and not active.is_full():
            entry = price
            if active.direction == "bull":
                sl = entry - config.SL_POINTS
                tp = active.tp
            else:
                sl = entry + config.SL_POINTS
                tp = active.tp

            tgt.add_dca_entry(symbol, entry)
            lots = _lot_size(risk_manager.risk_amount_usd())

            return Signal(
                symbol    = symbol,
                action    = "BUY" if active.direction == "bull" else "SELL",
                entry     = round(entry, 2),
                sl        = round(sl, 2),
                tp        = round(tp, 2),
                lots      = lots,
                rr        = _rr(entry, sl, tp),
                pattern   = "DCA Entry",
                entry_num = active.entry_count,
                tp_points = round(abs(tp - entry), 2),
            )
        return None

    # ── No active target — look for a fresh signal ────────────────────────────
    trend = ind.trend_direction(df)
    rsi   = ind.rsi_value(df)

    if trend == "flat":
        print(f"  [{symbol}] No signal — trend flat | RSI {rsi:.1f} | Price {price:.2f}")
        return None
    if trend == "bull" and rsi > config.RSI_OB:
        print(f"  [{symbol}] No signal — RSI overbought {rsi:.1f}")
        return None
    if trend == "bear" and rsi < config.RSI_OS:
        print(f"  [{symbol}] No signal — RSI oversold {rsi:.1f}")
        return None

    pattern = pa.bullish_pattern(df) if trend == "bull" else pa.bearish_pattern(df)
    macd_ok = ind.macd_bullish(df)   if trend == "bull" else ind.macd_bearish(df)
    rsi_ok  = (rsi < 50) if trend == "bear" else (rsi > 50)

    if pattern is None and not macd_ok and not rsi_ok:
        print(f"  [{symbol}] No signal — {trend} trend, no confirmation | RSI {rsi:.1f}")
        return None
    if pattern is None:
        pattern = "MACD Cross" if macd_ok else "RSI Momentum"

    # ── Find S/R TP target ────────────────────────────────────────────────────
    levels = pa.all_levels(df)
    tp = pa.find_tp(price, trend, levels)
    if tp is None:
        print(f"  [{symbol}] No signal — {trend} {pattern} but no S/R level found | Price {price:.2f}")
        return None

    entry = price
    sl    = (entry - config.SL_POINTS) if trend == "bull" else (entry + config.SL_POINTS)

    lots = _lot_size(risk_manager.risk_amount_usd())
    sig  = Signal(
        symbol    = symbol,
        action    = "BUY" if trend == "bull" else "SELL",
        entry     = round(entry, 2),
        sl        = round(sl, 2),
        tp        = round(tp, 2),
        lots      = lots,
        rr        = _rr(entry, sl, tp),
        pattern   = pattern,
        entry_num = 1,
        tp_points = round(abs(tp - entry), 2),
    )

    tgt.set_target(symbol, trend, tp, entry)
    return sig
