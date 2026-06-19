"""
signal_engine.py — Detects signals for all five strategies using real-time MT5 data.

Strategies:
  1. London Breakout   EURUSD, GBPUSD   07:00–10:00 UTC   daily
  2. DAX ORB           GER40            09:00–12:00 UTC   daily
  3. NAS100 US Open    NAS100           14:00–16:00 UTC   daily
  4. DAX H4 EMA        GER40            08:00–16:00 UTC   1-2×/month
  5. Oil H4 EMA        USOil            14:00–21:00 UTC   1×/month

Uses MT5 directly — no yfinance lag. MT5 must be open and logged in.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, date
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

import config
import risk_manager
import mt5_client


# ── Signal ─────────────────────────────────────────────────────────────────────

@dataclass
class Signal:
    strategy:       str
    symbol:         str           # MT5 symbol name
    action:         str           # "BUY" or "SELL"
    entry:          float
    sl:             float
    tp:             float         # trail_activate — used by auto_trader.py
    trail_activate: float         # move SL to BE when price hits this
    trail_distance: float         # then trail SL this many pts behind price
    lots:           float
    note:           str = ""
    sl_points:      float = field(init=False)
    risk_gbp:       float = field(init=False)

    def __post_init__(self):
        self.sl_points = round(abs(self.entry - self.sl), 5)
        self.risk_gbp  = risk_manager.risk_gbp(self.strategy)


# ── Deduplication (one signal per strategy per instrument per day) ─────────────

_fired: dict[str, date] = {}

def _fired_today(key: str) -> bool:
    return _fired.get(key) == datetime.now(timezone.utc).date()

def _mark(key: str):
    _fired[key] = datetime.now(timezone.utc).date()


# ── Data — MT5 real-time, zero lag ────────────────────────────────────────────

def _h1(mt5_symbol: str, count: int = 100) -> pd.DataFrame | None:
    try:
        df = mt5_client.get_bars(mt5_symbol, "H1", count)
        if df is None or len(df) < 10:
            return None
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        return df
    except Exception as e:
        print(f"  [MT5] {mt5_symbol} H1: {e}")
        return None


def _h4(mt5_symbol: str, count: int = 60) -> pd.DataFrame | None:
    try:
        df = mt5_client.get_bars(mt5_symbol, "H4", count)
        if df is None or len(df) < 10:
            return None
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        return df
    except Exception as e:
        print(f"  [MT5] {mt5_symbol} H4: {e}")
        return None


def _today() -> pd.Timestamp:
    n = datetime.now(timezone.utc)
    return pd.Timestamp(n.year, n.month, n.day, tz='UTC')


def _make(strategy, mt5_sym, action, entry, sl, trail_act, trail_dist) -> Signal:
    lots = risk_manager.calc_lots(mt5_sym, abs(entry - sl), strategy)
    return Signal(
        strategy=strategy, symbol=mt5_sym, action=action,
        entry=round(entry, 5), sl=round(sl, 5),
        tp=round(trail_act, 5), trail_activate=round(trail_act, 5),
        trail_distance=round(trail_dist, 5), lots=lots,
    )


# ── 1. LONDON BREAKOUT ─────────────────────────────────────────────────────────

def _london_breakout(now: datetime) -> list[Signal]:
    if not (7 <= now.hour < 10):
        return []

    day  = _today()
    prev = day - pd.Timedelta(days=1)
    sigs = []

    for mt5_sym, pip in [
        (config.MT5_SYMBOLS["EURUSD"], 0.0001),
        (config.MT5_SYMBOLS["GBPUSD"], 0.0001),
    ]:
        key = f"LB_{mt5_sym}"
        if _fired_today(key):
            continue

        df = _h1(mt5_sym)
        if df is None:
            continue

        asian = df[
            (df.index >= prev + pd.Timedelta(hours=22)) &
            (df.index <  day  + pd.Timedelta(hours=7))
        ]
        if len(asian) < 4:
            continue

        a_hi, a_lo = asian['high'].max(), asian['low'].min()
        rng  = a_hi - a_lo
        pips = rng / pip

        if not (10 <= pips <= 100):
            continue

        london = df[
            (df.index >= day + pd.Timedelta(hours=7)) &
            (df.index <= day + pd.Timedelta(hours=now.hour))
        ]
        if len(london) == 0:
            continue

        buf = rng * 0.15

        if london['high'].max() > a_hi:
            entry = a_hi
            sl    = a_lo - buf
            sig   = _make("London Breakout", mt5_sym, "BUY",
                          entry, sl, entry + abs(entry - sl), rng)
            sig.note = f"Asian range {pips:.0f} pips | trail {rng/pip:.0f} pips after +1R"
            _mark(key); sigs.append(sig)

        elif london['low'].min() < a_lo:
            entry = a_lo
            sl    = a_hi + buf
            sig   = _make("London Breakout", mt5_sym, "SELL",
                          entry, sl, entry - abs(sl - entry), rng)
            sig.note = f"Asian range {pips:.0f} pips | trail {rng/pip:.0f} pips after +1R"
            _mark(key); sigs.append(sig)

    return sigs


# ── 2. DAX OPENING RANGE BREAKOUT ─────────────────────────────────────────────

def _dax_orb(now: datetime) -> list[Signal]:
    if not (9 <= now.hour < 12):
        return []
    key = "DAX_ORB"
    if _fired_today(key):
        return []

    mt5_sym = config.MT5_SYMBOLS["DAX"]
    df = _h1(mt5_sym)
    if df is None:
        return []

    day   = _today()
    orb_t = day + pd.Timedelta(hours=8)
    rows  = df[df.index == orb_t]
    if len(rows) == 0:
        return []

    orb = rows.iloc[0]
    hi, lo, rng = orb['high'], orb['low'], orb['high'] - orb['low']
    if not (30 <= rng <= 300):
        return []

    since = df[
        (df.index >= day + pd.Timedelta(hours=9)) &
        (df.index <= day + pd.Timedelta(hours=now.hour))
    ]
    if len(since) == 0:
        return []

    trail = rng * 0.5

    if since['high'].max() > hi:
        sig = _make("DAX ORB", mt5_sym, "BUY", hi, lo, hi + (hi - lo), trail)
        sig.note = f"ORB {rng:.0f}pts | trail {trail:.0f}pts after +1R"
        _mark(key); return [sig]

    if since['low'].min() < lo:
        sig = _make("DAX ORB", mt5_sym, "SELL", lo, hi, lo - (hi - lo), trail)
        sig.note = f"ORB {rng:.0f}pts | trail {trail:.0f}pts after +1R"
        _mark(key); return [sig]

    return []


# ── 3. NAS100 US OPEN ──────────────────────────────────────────────────────────

def _nas100_open(now: datetime) -> list[Signal]:
    if not (14 <= now.hour < 16):
        return []
    key = "NAS_OPEN"
    if _fired_today(key):
        return []

    mt5_sym = config.MT5_SYMBOLS["NAS100"]
    df = _h1(mt5_sym)
    if df is None:
        return []

    day   = _today()
    ref_t = day + pd.Timedelta(hours=13)
    rows  = df[df.index == ref_t]
    if len(rows) == 0:
        return []

    ref = rows.iloc[0]
    hi, lo, rng = ref['high'], ref['low'], ref['high'] - ref['low']
    if not (50 <= rng <= 1500):
        return []

    since = df[
        (df.index >= day + pd.Timedelta(hours=14)) &
        (df.index <= day + pd.Timedelta(hours=now.hour))
    ]
    if len(since) == 0:
        return []

    trail = rng * 0.5

    if since['high'].max() > hi:
        sig = _make("NAS100 Open", mt5_sym, "BUY", hi, lo, hi + (hi - lo), trail)
        sig.note = f"Pre-mkt range {rng:.0f}pts | trail {trail:.0f}pts after +1R"
        _mark(key); return [sig]

    if since['low'].min() < lo:
        sig = _make("NAS100 Open", mt5_sym, "SELL", lo, hi, lo - (hi - lo), trail)
        sig.note = f"Pre-mkt range {rng:.0f}pts | trail {trail:.0f}pts after +1R"
        _mark(key); return [sig]

    return []


# ── 4+5. H4 EMA (DAX, OIL) ────────────────────────────────────────────────────

def _h4_ema(now: datetime) -> list[Signal]:
    sigs = []
    for mt5_sym, name, s_start, s_end in [
        (config.MT5_SYMBOLS["DAX"], "DAX", 8,  16),
        (config.MT5_SYMBOLS["OIL"], "Oil", 14, 21),
    ]:
        if not (s_start <= now.hour < s_end):
            continue

        df = _h4(mt5_sym)
        if df is None or len(df) < 30:
            continue

        try:
            df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
            df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
            hi, lo, cl  = df['high'], df['low'], df['close']
            tr  = pd.concat([hi-lo, (hi-cl.shift()).abs(), (lo-cl.shift()).abs()], axis=1).max(axis=1)
            df['atr'] = tr.ewm(com=13, adjust=False).mean()
            dmp  = ((hi-hi.shift()) > (lo.shift()-lo)).astype(float) * (hi-hi.shift()).clip(0)
            dmm  = ((lo.shift()-lo) > (hi-hi.shift())).astype(float) * (lo.shift()-lo).clip(0)
            atr_s = tr.ewm(com=13, adjust=False).mean()
            dip  = 100 * dmp.ewm(com=13, adjust=False).mean() / atr_s
            dim  = 100 * dmm.ewm(com=13, adjust=False).mean() / atr_s
            df['adx'] = (100*(dip-dim).abs()/(dip+dim).replace(0,1)).fillna(0).ewm(com=13, adjust=False).mean()

            bar, prev = df.iloc[-2], df.iloc[-3]   # last COMPLETED H4 bar
            if bar['adx'] < 25:
                continue

            bull = bar['ema10'] > bar['ema20'] and prev['ema10'] <= prev['ema20']
            bear = bar['ema10'] < bar['ema20'] and prev['ema10'] >= prev['ema20']
            if not bull and not bear:
                continue

            key = f"H4_{name}_{df.index[-2].date().isoformat()}"
            if _fired_today(key):
                continue

            entry, atr = bar['close'], bar['atr']
            if bull:
                sl  = entry - 1.5 * atr
                sig = _make("H4 EMA", mt5_sym, "BUY",
                            entry, sl, entry + (entry - sl), atr * 0.75)
            else:
                sl  = entry + 1.5 * atr
                sig = _make("H4 EMA", mt5_sym, "SELL",
                            entry, sl, entry - (sl - entry), atr * 0.75)
            sig.note = f"{name} EMA 10/20 {'bull' if bull else 'bear'} cross | ADX {bar['adx']:.0f}"
            _mark(key); sigs.append(sig)

        except Exception as e:
            print(f"  [H4 EMA] {name}: {e}")

    return sigs


# ── Public API ─────────────────────────────────────────────────────────────────

def get_all_signals() -> list[Signal]:
    now = datetime.now(timezone.utc)
    return (
        _london_breakout(now) +
        _dax_orb(now) +
        _nas100_open(now) +
        _h4_ema(now)
    )


def evaluate(mt5_symbol: str) -> Signal | None:
    """Used by auto_trader.py."""
    allowed, msg = risk_manager.is_trading_allowed()
    if not allowed:
        print(f"  [Risk] {msg}"); return None
    cooled, msg = risk_manager.in_sl_cooldown(mt5_symbol)
    if cooled:
        print(f"  [Cooldown] {msg}"); return None
    for sig in get_all_signals():
        if sig.symbol == mt5_symbol:
            return sig
    return None
