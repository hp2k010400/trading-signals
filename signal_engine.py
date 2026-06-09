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
    symbol:        str
    action:        str          # "BUY" | "SELL"
    entry:         float
    sl:            float
    tp:            float
    lots:          float
    rr:            float
    pattern:       str
    entry_num:     int          # 1 = first entry, 2/3 = pyramid
    confirmations: int          # 1-3 — drives lot size
    early_exit:    float        # suggested early cut price
    tp_points:   float
    sl_points:   float = config.SL_POINTS


def _lot_size(symbol: str, confirmations: int) -> float:
    if confirmations >= 3:
        risk_pct = config.RISK_PCT_TIER_3
    elif confirmations == 2:
        risk_pct = config.RISK_PCT_TIER_2
    else:
        risk_pct = config.RISK_PCT_TIER_1
    risk_usd = config.ACCOUNT_BALANCE * (risk_pct / 100)
    return data_client.calc_lot_size(symbol, config.SL_POINTS, risk_usd)


def _early_exit(entry: float, action: str) -> float:
    if action == "BUY":
        return round(entry - config.EARLY_EXIT_POINTS, 2)
    return round(entry + config.EARLY_EXIT_POINTS, 2)


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

    cooled, cool_msg = risk_manager.in_sl_cooldown(symbol)
    if cooled:
        print(f"  [{symbol}] Cooldown: {cool_msg}")
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
        # Check if trend is still valid — if reversed, stop adding DCA entries
        # but leave the target in place so _check_exits() can still fire TP/SL notifications
        trend = ind.trend_direction(df)
        if trend != active.direction:
            print(f"  [{symbol}] Trend reversed — holding target for exit detection, no new entries")
            return None

        # Fire a DCA entry only if price pulled back AND there's still meaningful room to TP
        room_to_tp = abs(active.tp - price)
        if not active.counter_trend and active.needs_dca(price) and not active.is_full() and room_to_tp >= config.SL_POINTS:
            entry = price
            if active.direction == "bull":
                sl = entry - config.SL_POINTS
                tp = active.tp
            else:
                sl = entry + config.SL_POINTS
                tp = active.tp

            tgt.add_dca_entry(symbol, entry)
            action = "BUY" if active.direction == "bull" else "SELL"
            lots   = _lot_size(symbol, 2)   # pyramid entries always tier 2

            return Signal(
                symbol        = symbol,
                action        = action,
                entry         = round(entry, 2),
                sl            = round(sl, 2),
                tp            = round(tp, 2),
                lots          = lots,
                rr            = _rr(entry, sl, tp),
                pattern       = "Pyramid Entry",
                entry_num     = active.entry_count,
                tp_points     = round(abs(tp - entry), 2),
                confirmations = 2,
                early_exit    = _early_exit(round(entry, 2), action),
            )
        return None

    # ── No active target — look for a fresh signal ────────────────────────────
    trend = ind.trend_direction(df)
    rsi   = ind.rsi_value(df)

    if trend == "flat":
        print(f"  [{symbol}] No signal — trend flat | RSI {rsi:.1f} | Price {price:.2f}")
        return None

    # H1 trend filter — counter-trend = tier 1 only, no DCA
    counter_trend = False
    if config.USE_H1_FILTER:
        try:
            df_h1 = data_client.get_bars(symbol, "H1", 50)
            df_h1 = ind.enrich(df_h1)
            h1_trend = ind.trend_direction(df_h1)
            if h1_trend != "flat" and h1_trend != trend:
                counter_trend = True
                print(f"  [{symbol}] H1 counter-trend — M15:{trend} H1:{h1_trend} — tier 1 only, no DCA")
        except Exception:
            pass

    # ADX filter
    if config.USE_ADX_FILTER:
        adx = ind.adx_value(df)
        if adx > 0 and adx < config.ADX_MIN:
            print(f"  [{symbol}] ADX {adx:.1f} < {config.ADX_MIN} — ranging, skip")
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

    # Count confirmations → drives lot size
    confirmations = sum([bool(pattern), macd_ok, rsi_ok])
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

    action = "BUY" if trend == "bull" else "SELL"
    lots   = _lot_size(symbol, 1 if counter_trend else confirmations)
    sig    = Signal(
        symbol        = symbol,
        action        = action,
        entry         = round(entry, 2),
        sl            = round(sl, 2),
        tp            = round(tp, 2),
        lots          = lots,
        rr            = _rr(entry, sl, tp),
        pattern       = pattern,
        entry_num     = 1,
        tp_points     = round(abs(tp - entry), 2),
        confirmations = confirmations,
        early_exit    = _early_exit(round(entry, 2), action),
    )

    tgt.set_target(symbol, trend, tp, entry, counter_trend=counter_trend)
    return sig
