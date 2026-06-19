"""
risk_manager.py — Position sizing and risk gates.
"""
import time
import config

# ── Simple risk gates (FTMO protection) ───────────────────────────────────────

_sl_streak:   int   = 0
_pause_until: float = 0.0
_sl_times:    dict  = {}


def record_sl(symbol: str):
    global _sl_streak, _pause_until
    _sl_times[symbol] = time.time()
    _sl_streak += 1
    if _sl_streak >= config.MAX_CONSECUTIVE_SL:
        _pause_until = time.time() + config.SL_PAUSE_HOURS * 3600
        print(f"[Risk] {_sl_streak} consecutive SLs — pausing {config.SL_PAUSE_HOURS}h")


def record_tp():
    global _sl_streak
    _sl_streak = 0


def in_sl_cooldown(symbol: str) -> tuple[bool, str]:
    t = _sl_times.get(symbol, 0)
    elapsed = (time.time() - t) / 60
    if elapsed < config.SL_COOLDOWN_MINUTES:
        rem = int(config.SL_COOLDOWN_MINUTES - elapsed)
        return True, f"SL cooldown — {rem} min remaining"
    return False, ""


def is_trading_allowed() -> tuple[bool, str]:
    if time.time() < _pause_until:
        mins = int((_pause_until - time.time()) / 60)
        return False, f"Paused after {config.MAX_CONSECUTIVE_SL} SLs — {mins} min left"
    return True, ""


# ── Position sizing ────────────────────────────────────────────────────────────

def risk_gbp(strategy: str, balance: float = None) -> float:
    bal = balance or config.ACCOUNT_BALANCE
    pct = config.RISK.get(strategy, config.RISK_PER_ENTRY_PCT / 100)
    return bal * pct


# Approximate £ value per 1-point move per 1 standard lot
# Adjust if your broker uses different contract sizes
TICK_VALUE = {
    "EURUSD":     7.50,
    "GBPUSD":     7.50,
    "GER40.cash": 10.00,
    "NAS100.cash": 2.00,
    "USOil.cash": 10.00,
}


def calc_lots(mt5_symbol: str, sl_points: float, strategy: str,
              balance: float = None) -> float:
    if sl_points <= 0:
        return config.MIN_LOT
    tick_val = TICK_VALUE.get(mt5_symbol, 10.0)
    risk     = risk_gbp(strategy, balance)
    lots     = risk / (sl_points * tick_val)
    lots     = round(round(lots / 0.01) * 0.01, 2)
    return max(config.MIN_LOT, min(config.MAX_LOT, lots))


def risk_amount_usd() -> float:
    """Legacy — used by some old bot code."""
    return config.ACCOUNT_BALANCE * (config.RISK_PER_ENTRY_PCT / 100)
