"""
Replaces mt5_client.py. Pulls live XAUUSD data from Twelve Data REST API.
Both XAUUSD.s and XAUUSD.QTR map to XAU/USD spot (futures not on free tier).
"""
import requests
import pandas as pd
import config

_BASE = "https://api.twelvedata.com"

_SYMBOL_MAP = {
    "XAUUSD.s":   "XAU/USD",
    "XAUUSD.QTR": "XAU/USD",
}

_TF_MAP = {
    "M5":  "5min",
    "M15": "15min",
    "M30": "30min",
    "H1":  "1h",
    "H4":  "4h",
    "D1":  "1day",
}


def get_bars(symbol: str, timeframe: str, count: int = config.CANDLES_NEEDED) -> pd.DataFrame:
    td_symbol = _SYMBOL_MAP.get(symbol, symbol)
    tf = _TF_MAP.get(timeframe, timeframe)

    resp = requests.get(f"{_BASE}/time_series", params={
        "symbol":     td_symbol,
        "interval":   tf,
        "outputsize": count,
        "apikey":     config.TWELVE_DATA_KEY,
        "format":     "JSON",
    }, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") == "error":
        raise RuntimeError(f"Twelve Data: {data.get('message')}")

    values = data.get("values", [])
    if not values:
        raise RuntimeError(f"No data for {symbol} {timeframe}")

    df = pd.DataFrame(values)
    df = df.rename(columns={"datetime": "time"})
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time")
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col])

    return df.iloc[::-1]   # Twelve Data returns newest-first; reverse to chronological


def get_tick(symbol: str) -> dict:
    td_symbol = _SYMBOL_MAP.get(symbol, symbol)
    resp = requests.get(f"{_BASE}/price", params={
        "symbol": td_symbol,
        "apikey": config.TWELVE_DATA_KEY,
    }, timeout=10)
    resp.raise_for_status()
    price = float(resp.json()["price"])
    return {"ask": price, "bid": price}


def calc_lot_size(symbol: str, sl_points: float, risk_usd: float) -> float:
    """
    XAUUSD: 1 standard lot = 100 oz.
    A $1 price move = $100 per lot, so risk_per_lot = sl_points * 100.
    """
    if sl_points <= 0:
        return config.MIN_LOT
    risk_per_lot = sl_points * 100
    lot = round(risk_usd / risk_per_lot, 2)
    return max(config.MIN_LOT, min(config.MAX_LOT, lot))
