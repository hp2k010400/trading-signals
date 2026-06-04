"""
Core signal logic. A signal requires ALL of the following:
  - Trend alignment  : EMA fast/slow agree on direction (primary TF)
  - Trend filter     : H1 EMA agrees (higher timeframe confirmation)
  - Momentum         : RSI not in overbought/oversold territory
  - MACD cross       : histogram confirms direction (or candle pattern replaces this)
  - Price action     : bullish/bearish candle pattern on last closed candle
  - News clear       : no high-impact event within pause window
"""
from dataclasses import dataclass
import config
import indicators as ind
import price_action as pa
import news_filter
import risk_manager
import data_client


@dataclass
class Signal:
    symbol:   str
    action:   str
    entry:    float
    sl:       float
    tp1:      float
    tp2:      float
    lots:     float
    atr:      float
    rr1:      float
    rr2:      float
    pattern:  str
    trend:    str
    h1_trend: str


def _rr(entry, sl, tp) -> float:
    risk   = abs(entry - sl)
    reward = abs(tp - entry)
    return round(reward / risk, 2) if risk > 0 else 0


def evaluate(symbol: str) -> Signal | None:
    blocked, news_msg = news_filter.is_news_window()
    if blocked:
        print(f"  [{symbol}] News window — {news_msg}")
        return None

    allowed, risk_msg = risk_manager.is_trading_allowed()
    if not allowed:
        print(f"  [{symbol}] Risk blocked — {risk_msg}")
        return None

    try:
        df_primary = ind.enrich(data_client.get_bars(symbol, config.PRIMARY_TF))
        df_trend   = ind.enrich(data_client.get_bars(symbol, config.TREND_TF))
    except Exception as e:
        print(f"  [{symbol}] Data error: {e}")
        return None

    if len(df_primary) < 50 or len(df_trend) < 50:
        return None

    trend    = ind.trend_direction(df_primary)
    h1_trend = ind.trend_direction(df_trend)
    rsi      = ind.rsi_value(df_primary)
    atr      = ind.atr_value(df_primary)

    if trend == "flat" or h1_trend == "flat" or trend != h1_trend:
        return None

    pattern = pa.bullish_pattern(df_primary) if trend == "bull" else pa.bearish_pattern(df_primary)
    macd_ok = ind.macd_bullish(df_primary) if trend == "bull" else ind.macd_bearish(df_primary)

    if pattern is None and not macd_ok:
        return None

    if pattern is None:
        pattern = "MACD Cross"

    if trend == "bull" and rsi > config.RSI_OB:
        return None
    if trend == "bear" and rsi < config.RSI_OS:
        return None

    tick  = data_client.get_tick(symbol)
    entry = tick["ask"] if trend == "bull" else tick["bid"]

    if trend == "bull":
        sl  = entry - atr * config.ATR_SL_MULT
        tp1 = entry + atr * config.ATR_TP1_MULT
        tp2 = entry + atr * config.ATR_TP2_MULT
    else:
        sl  = entry + atr * config.ATR_SL_MULT
        tp1 = entry - atr * config.ATR_TP1_MULT
        tp2 = entry - atr * config.ATR_TP2_MULT

    lots = data_client.calc_lot_size(symbol, abs(entry - sl), risk_manager.risk_amount_usd())

    return Signal(
        symbol   = symbol,
        action   = "BUY" if trend == "bull" else "SELL",
        entry    = round(entry, 2),
        sl       = round(sl, 2),
        tp1      = round(tp1, 2),
        tp2      = round(tp2, 2),
        lots     = lots,
        atr      = round(atr, 2),
        rr1      = _rr(entry, sl, tp1),
        rr2      = _rr(entry, sl, tp2),
        pattern  = pattern,
        trend    = "Bullish" if trend == "bull" else "Bearish",
        h1_trend = "Bullish" if h1_trend == "bull" else "Bearish",
    )
