import pandas as pd
import pandas_ta as ta
import config


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add all indicator columns to a OHLC dataframe in-place."""
    df = df.copy()

    # Trend EMAs
    df["ema_fast"] = ta.ema(df["close"], length=config.EMA_FAST)
    df["ema_slow"] = ta.ema(df["close"], length=config.EMA_SLOW)

    # Momentum
    df["rsi"] = ta.rsi(df["close"], length=config.RSI_PERIOD)

    # Volatility — used for dynamic TP/SL sizing
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=config.ATR_PERIOD)

    # MACD — extra confirmation
    macd = ta.macd(df["close"])
    if macd is not None:
        df["macd"]        = macd.iloc[:, 0]
        df["macd_signal"] = macd.iloc[:, 1]
        df["macd_hist"]   = macd.iloc[:, 2]

    return df


def trend_direction(df: pd.DataFrame) -> str:
    """'bull', 'bear', or 'flat' based on last closed candle."""
    row = df.iloc[-2]   # -1 is the forming candle; -2 is the last closed
    if pd.isna(row["ema_fast"]) or pd.isna(row["ema_slow"]):
        return "flat"
    if row["ema_fast"] > row["ema_slow"]:
        return "bull"
    if row["ema_fast"] < row["ema_slow"]:
        return "bear"
    return "flat"


def rsi_value(df: pd.DataFrame) -> float:
    return float(df["rsi"].iloc[-2])


def atr_value(df: pd.DataFrame) -> float:
    return float(df["atr"].iloc[-2])


def macd_bullish(df: pd.DataFrame) -> bool:
    """MACD histogram turned positive (crossed up)."""
    if "macd_hist" not in df.columns:
        return False
    h = df["macd_hist"]
    return float(h.iloc[-2]) > 0 and float(h.iloc[-3]) <= 0


def macd_bearish(df: pd.DataFrame) -> bool:
    """MACD histogram turned negative (crossed down)."""
    if "macd_hist" not in df.columns:
        return False
    h = df["macd_hist"]
    return float(h.iloc[-2]) < 0 and float(h.iloc[-3]) >= 0


def adx_value(df: pd.DataFrame) -> float:
    result = ta.adx(df["high"], df["low"], df["close"], length=config.ADX_PERIOD)
    if result is None or result.empty:
        return 0.0
    col = [c for c in result.columns if c.startswith("ADX_")]
    if not col:
        return 0.0
    val = result[col[0]].iloc[-2]
    return float(val) if not pd.isna(val) else 0.0
