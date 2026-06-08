import time
import config

_sl_streak:   int   = 0
_pause_until: float = 0.0
_sl_times:    dict  = {}   # symbol -> timestamp of last SL hit


def record_sl(symbol: str):
    """Call when an SL is hit. Increments streak and may trigger a pause."""
    global _sl_streak, _pause_until
    _sl_times[symbol] = time.time()
    _sl_streak += 1
    if _sl_streak >= config.MAX_CONSECUTIVE_SL:
        _pause_until = time.time() + config.SL_PAUSE_HOURS * 3600
        print(f"[Risk] {_sl_streak} consecutive SLs — trading paused for {config.SL_PAUSE_HOURS}h")


def record_tp():
    """Call when a TP is hit. Resets the consecutive SL streak."""
    global _sl_streak
    _sl_streak = 0


def in_sl_cooldown(symbol: str) -> tuple[bool, str]:
    """Returns (True, msg) if this symbol is still in its post-SL cooldown window."""
    t = _sl_times.get(symbol, 0)
    elapsed_minutes = (time.time() - t) / 60
    if elapsed_minutes < config.SL_COOLDOWN_MINUTES:
        remaining = int(config.SL_COOLDOWN_MINUTES - elapsed_minutes)
        return True, f"SL cooldown — {remaining} min remaining"
    return False, ""


def is_trading_allowed() -> tuple[bool, str]:
    """Returns (False, reason) if trading is paused due to consecutive SL limit."""
    if time.time() < _pause_until:
        mins_left = int((_pause_until - time.time()) / 60)
        return False, f"{config.MAX_CONSECUTIVE_SL} consecutive SLs hit — paused for {mins_left} more minutes"
    return True, ""


def risk_amount_usd() -> float:
    return config.ACCOUNT_BALANCE * (config.RISK_PER_ENTRY_PCT / 100)
