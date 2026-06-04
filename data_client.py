"""
Data client using yfinance — free, no API key, real-time gold prices.
Gold spot: GC=F (futures, trades like spot for our purposes)
"""
import yfinance as yf
import pandas as pd
import config

_SYMBOL_MAP = {
    "XAUUSD.s":   "GC=F",
    "XAUUSD.QTR": "GC=F",
    "XAUUSD":     "GC=F",
}

_TF_MAP = {
    "M5":  "5m",
    "M15": "15m",
    "M30": "30m",
    "H1":  "60m",
    "H4":  "4h",
    "D1":  "1d",
}

# yfinance period needed per interval to get enough bars
_PERIOD_MAP = {
    "5m":  "5d",
    "15m": "60d",
    "30m": "60d",
    "60m": "60d",
    "4h":  "60d",
    "1d":  "1y",
}


def get_bars(symbol: str, timeframe: str, count: int = config.CANDLES_NEEDED) -> pd.DataFrame:
    ticker = _SYMBOL_MAP.get(symbol, "GC=F")
    tf     = _TF_MAP.get(timeframe, "15m")
    period = _PERIOD_MAP.get(tf, "60d")

    df = yf.download(ticker, period=period, interval=tf, progress=False, auto_adjust=True)

    if df is None or len(df) == 0:
        raise RuntimeError(f"No data from yfinance for {symbol} {timeframe}")

    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    df = df[["open", "high", "low", "close"]].dropna()
    df.index = pd.to_datetime(df.index)

    return df.tail(count)


def get_tick(symbol: str) -> dict:
    ticker = _SYMBOL_MAP.get(symbol, "GC=F")
    t = yf.Ticker(ticker)
    price = t.fast_info.get("last_price") or t.fast_info.get("lastPrice")
    if price is None:
        # fallback: use last close from recent data
        df = yf.download(ticker, period="1d", interval="1m", progress=False, auto_adjust=True)
        price = float(df["Close"].iloc[-1])
    return {"ask": float(price), "bid": float(price)}


def calc_lot_size(symbol: str, sl_points: float, risk_usd: float) -> float:
    if config.FIXED_LOT is not None:
        return config.FIXED_LOT
    if sl_points <= 0:
        return config.MIN_LOT
    risk_per_lot = sl_points * 100
    lot = risk_usd / risk_per_lot
    lot = round(round(lot / 0.01) * 0.01, 2)
    return max(config.MIN_LOT, min(config.MAX_LOT, lot))
