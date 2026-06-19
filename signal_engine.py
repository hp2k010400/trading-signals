"""
signal_engine.py — Detects signals for all five strategies.

Strategies (all use yfinance H1 data — no API key needed):
  1. London Breakout   EURUSD, GBPUSD   07:00–10:00 UTC   daily
  2. DAX ORB           GER40            09:00–12:00 UTC   daily
  3. NAS100 US Open    NAS100           14:00–16:00 UTC   daily
  4. DAX H4 EMA        GER40            08:00–16:00 UTC   1-2×/month
  5. Oil H4 EMA        USOil            14:00–21:00 UTC   1×/month

Each strategy fires at most once per day per instrument.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, date
import pandas as pd
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

import config
import risk_manager


# ── Signal ─────────────────────────────────────────────────────────────────────

@dataclass
class Signal:
    strategy:       str
    symbol:         str           # MT5 symbol name
    action:         str           # "BUY" or "SELL"
    entry:          float
    sl:             float
    tp:             float         # = trail_activate (used by auto_trader.py)
    trail_activate: float         # move SL to BE when price hits this
    trail_distance: float         # then trail SL this many pts behind price
    lots:           float         # calculated lot size
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


# ── Data ───────────────────────────────────────────────────────────────────────

def _h1(yf_symbol: str, days: int = 30) -> pd.DataFrame | None:
    try:
        df = yf.download(yf_symbol, interval="1h", period=f"{days}d",
                         auto_adjust=True, progress=False)
        if df is None or len(df) < 10:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        df = df.dropna()
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        else:
            df.index = df.index.tz_convert('UTC')
        return df
    except Exception as e:
        print(f"  [data] {yf_symbol}: {e}")
        return None


def _today() -> pd.Timestamp:
    n = datetime.now(timezone.utc)
    return pd.Timestamp(n.year, n.month, n.day, tz='UTC')


def _make_signal(strategy, mt5_sym, action, entry, sl, trail_act, trail_dist) -> Signal:
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

    for yf_sym, mt5_sym, pip in [
        ("EURUSD=X", config.MT5_SYMBOLS["EURUSD"], 0.0001),
        ("GBPUSD=X", config.MT5_SYMBOLS["GBPUSD"], 0.0001),
    ]:
        key = f"LB_{mt5_sym}"
        if _fired_today(key):
            continue

        df = _h1(yf_sym)
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

        hi_seen = london['high'].max()
        lo_seen = london['low'].min()
        buf     = rng * 0.15

        if hi_seen > a_hi:
            entry = a_hi
            sl    = a_lo - buf
            sig   = _make_signal("London Breakout", mt5_sym, "BUY",
                                 entry, sl, entry + abs(entry - sl), rng)
            sig.note = f"Asian range {pips:.0f} pips | trail {rng/pip:.0f} pips after +1R"
            _mark(key); sigs.append(sig)

        elif lo_seen < a_lo:
            entry = a_lo
            sl    = a_hi + buf
            sig   = _make_signal("London Breakout", mt5_sym, "SELL",
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

    df = _h1("^GDAXI")
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
    mt5   = config.MT5_SYMBOLS["DAX"]

    if since['high'].max() > hi:
        sig = _make_signal("DAX ORB", mt5, "BUY", hi, lo, hi + (hi - lo), trail)
        sig.note = f"ORB {rng:.0f}pts | trail {trail:.0f}pts after +1R"
        _mark(key); return [sig]

    if since['low'].min() < lo:
        sig = _make_signal("DAX ORB", mt5, "SELL", lo, hi, lo - (hi - lo), trail)
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

    df = _h1("NQ=F")
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
    mt5   = config.MT5_SYMBOLS["NAS100"]

    if since['high'].max() > hi:
        sig = _make_signal("NAS100 Open", mt5, "BUY", hi, lo, hi + (hi - lo), trail)
        sig.note = f"Pre-mkt range {rng:.0f}pts | trail {trail:.0f}pts after +1R"
        _mark(key); return [sig]

    if since['low'].min() < lo:
        sig = _make_signal("NAS100 Open", mt5, "SELL", lo, hi, lo - (hi - lo), trail)
        sig.note = f"Pre-mkt range {rng:.0f}pts | trail {trail:.0f}pts after +1R"
        _mark(key); return [sig]

    return []


# ── 4+5. H4 EMA (DAX, OIL) ────────────────────────────────────────────────────

def _h4_ema(now: datetime) -> list[Signal]:
    sigs = []
    for yf_sym, mt5_sym, name, s_start, s_end in [
        ("^GDAXI", config.MT5_SYMBOLS["DAX"], "DAX", 8,  16),
        ("CL=F",   config.MT5_SYMBOLS["OIL"], "Oil", 14, 21),
    ]:
        if not (s_start <= now.hour < s_end):
            continue
        try:
            raw = yf.download(yf_sym, interval="1h", period="60d",
                              auto_adjust=True, progress=False)
            if raw is None or len(raw) < 50:
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            raw.columns = [c.lower() for c in raw.columns]
            raw = raw.dropna()
            if raw.index.tz is None:
                raw.index = raw.index.tz_localize('UTC')

            df = raw.resample('4h').agg(
                {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}
            ).dropna()
            if len(df) < 30:
                continue

            df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
            df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
            hi, lo, cl  = df['high'], df['low'], df['close']
            tr  = pd.concat([hi-lo, (hi-cl.shift()).abs(), (lo-cl.shift()).abs()], axis=1).max(axis=1)
            df['atr'] = tr.ewm(com=13, adjust=False).mean()
            dmp  = ((hi-hi.shift()) > (lo.shift()-lo)).astype(float) * (hi-hi.shift()).clip(0)
            dmm  = ((lo.shift()-lo) > (hi-hi.shift())).astype(float) * (lo.shift()-lo).clip(0)
            as_  = tr.ewm(com=13, adjust=False).mean()
            dip  = 100 * dmp.ewm(com=13, adjust=False).mean() / as_
            dim  = 100 * dmm.ewm(com=13, adjust=False).mean() / as_
            df['adx'] = (100*(dip-dim).abs()/(dip+dim).replace(0,1)).fillna(0).ewm(com=13,adjust=False).mean()

            bar, prev = df.iloc[-2], df.iloc[-3]
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
                sig = _make_signal("H4 EMA", mt5_sym, "BUY",
                                   entry, sl, entry + (entry - sl), atr * 0.75)
            else:
                sl  = entry + 1.5 * atr
                sig = _make_signal("H4 EMA", mt5_sym, "SELL",
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
    """Used by auto_trader.py — returns first matching signal for this symbol."""
    allowed, msg = risk_manager.is_trading_allowed()
    if not allowed:
        print(f"  [Risk] {msg}")
        return None
    cooled, msg = risk_manager.in_sl_cooldown(mt5_symbol)
    if cooled:
        print(f"  [Cooldown] {msg}")
        return None
    for sig in get_all_signals():
        if sig.symbol == mt5_symbol:
            return sig
    return None
