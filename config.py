import os

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Twelve Data ───────────────────────────────────────────────────────────────
TWELVE_DATA_KEY  = os.environ.get("TWELVE_DATA_KEY", "")

# ── Symbols ───────────────────────────────────────────────────────────────────
SYMBOLS = ["XAUUSD.s", "XAUUSD.QTR"]

# ── Timeframes ────────────────────────────────────────────────────────────────
PRIMARY_TF = "M15"
TREND_TF   = "H1"

# ── Risk ──────────────────────────────────────────────────────────────────────
ACCOUNT_BALANCE     = float(os.environ.get("ACCOUNT_BALANCE", "10000"))
RISK_PER_ENTRY_PCT  = 0.5     # used only if FIXED_LOT is None
FIXED_LOT           = 0.1     # set to None to use RISK_PER_ENTRY_PCT calculation
MIN_LOT             = 0.01
MAX_LOT             = 5.0

# ── Fixed SL/TP (reverse-engineered from screenshots) ─────────────────────────
SL_POINTS           = 15      # fixed 15 points stop loss
TP_BUFFER           = 2       # place TP 2 pts before the S/R level
ROUND_NUMBER_STEP   = 25      # gold clusters around every 25 points

# ── Multi-entry (DCA) settings ────────────────────────────────────────────────
MAX_ENTRIES         = 3       # max entries toward same target
ENTRY_SEPARATION    = 5       # min points of pullback before adding next entry
TARGET_EXPIRY_HOURS = 24      # drop a target if not hit within 24 hours

# ── Indicators ────────────────────────────────────────────────────────────────
EMA_FAST    = 20
EMA_SLOW    = 50
RSI_PERIOD  = 14
RSI_OB      = 70
RSI_OS      = 30
ATR_PERIOD  = 14

# ── News filter ───────────────────────────────────────────────────────────────
NEWS_PAUSE_MINUTES = 30
NEWS_CURRENCIES    = ["USD", "XAU"]

# ── Engine ────────────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 900
CANDLES_NEEDED        = 200
