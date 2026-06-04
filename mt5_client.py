import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import config

_TF_MAP = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}


def connect():
    kwargs = {}
    if config.MT5_LOGIN:
        kwargs = dict(login=config.MT5_LOGIN, password=config.MT5_PASSWORD, server=config.MT5_SERVER)
    if not mt5.initialize(**kwargs):
        raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
    info = mt5.account_info()
    print(f"[MT5] Connected — {info.name} | {info.server} | Balance: {info.balance}")


def disconnect():
    mt5.shutdown()


def get_bars(symbol: str, timeframe: str, count: int = config.CANDLES_NEEDED) -> pd.DataFrame:
    tf = _TF_MAP.get(timeframe)
    if tf is None:
        raise ValueError(f"Unknown timeframe: {timeframe}")
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No data for {symbol} {timeframe}: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)
    return df


def get_tick(symbol: str) -> mt5.Tick:
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"No tick for {symbol}")
    return tick


def get_symbol_info(symbol: str) -> mt5.SymbolInfo:
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"Symbol not found: {symbol}")
    return info


def calc_lot_size(symbol: str, sl_points: float, risk_usd: float) -> float:
    """Return lot size rounded to broker's lot step."""
    info = get_symbol_info(symbol)
    if info.trade_tick_size == 0:
        return config.MIN_LOT
    sl_ticks    = sl_points / info.trade_tick_size
    risk_per_lot = sl_ticks * info.trade_tick_value
    if risk_per_lot <= 0:
        return config.MIN_LOT
    lot = risk_usd / risk_per_lot
    step = info.volume_step
    lot  = round(round(lot / step) * step, 8)
    return max(config.MIN_LOT, min(config.MAX_LOT, lot))
