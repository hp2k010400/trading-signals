import os

# ── Telegram ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Account ────────────────────────────────────────────────────────────────────
ACCOUNT_BALANCE = float(os.environ.get("ACCOUNT_BALANCE", "70000"))

# ── MT5 login (local auto_trader.py only — NOT used on Railway) ───────────────
MT5_LOGIN    = int(os.environ.get("MT5_LOGIN", "0")) or None
MT5_PASSWORD = os.environ.get("MT5_PASSWORD", "")
MT5_SERVER   = os.environ.get("MT5_SERVER", "")

# ── Risk per strategy (% of balance) ──────────────────────────────────────────
RISK = {
    "London Breakout": 0.004,    # 0.4% — EURUSD/GBPUSD are correlated, keep low
    "DAX ORB":         0.0075,   # 0.75%
    "NAS100 Open":     0.0075,   # 0.75%
    "H4 EMA":          0.0075,   # 0.75%
}
RISK_PER_ENTRY_PCT = 0.75        # default % — used by auto_trader.py

# ── MT5 symbol names — check these match YOUR broker's Market Watch exactly ───
# Common alternatives shown as comments
MT5_SYMBOLS = {
    "EURUSD":  "EURUSD",
    "GBPUSD":  "GBPUSD",
    "DAX":     "GER40.cash",    # also: DE40, GER40, DAX40
    "NAS100":  "NAS100.cash",   # also: US100, NAS100, NQ100
    "OIL":     "USOil.cash",    # also: WTI, OIL, CL, XTIUSD
}
SYMBOLS = list(MT5_SYMBOLS.values())

# ── Bot behaviour ──────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 60
CANDLES_NEEDED        = 100

# ── News filter ────────────────────────────────────────────────────────────────
NEWS_PAUSE_MINUTES = 15
NEWS_CURRENCIES    = ["USD", "EUR", "GBP"]

# ── Position sizing ────────────────────────────────────────────────────────────
FIXED_LOT = None
MIN_LOT   = 0.01
MAX_LOT   = 10.0

# ── FTMO safety thresholds (bot pauses if these are breached) ─────────────────
FTMO_DAILY_LOSS_LIMIT = ACCOUNT_BALANCE * 0.045   # 4.5% (hard limit is 5%)
FTMO_TOTAL_DD_LIMIT   = ACCOUNT_BALANCE * 0.09    # 9%   (hard limit is 10%)

# ── Legacy Gold bot fields (kept so old imports don't break) ──────────────────
MAX_CONSECUTIVE_SL  = 3
SL_PAUSE_HOURS      = 4
SL_COOLDOWN_MINUTES = 60
