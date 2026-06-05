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

# ── Risk ──────────────────────────────────────────────────────────────────────
ACCOUNT_BALANCE     = float(os.environ.get("ACCOUNT_BALANCE", "10000"))
MIN_LOT             = 0.01
MAX_LOT             = 5.0

# Variable lot sizing by signal strength (matches friend's 0.1-0.5 sizing)
LOT_TIER_1          = 0.10    # 1 confirmation  (RSI only)
LOT_TIER_2          = 0.20    # 2 confirmations (RSI + pattern OR MACD)
LOT_TIER_3          = 0.30    # 3 confirmations (RSI + pattern + MACD)

# ── SL/TP settings ────────────────────────────────────────────────────────────
SL_POINTS           = 7       # tight SL matching friend's actual losses (5-7 pts)
TP_BUFFER           = 2       # place TP 2 pts before the S/R level
ROUND_NUMBER_STEP   = 25      # gold clusters around every 25 points

# ── Multi-entry (DCA) settings ────────────────────────────────────────────────
MAX_ENTRIES         = 3       # max entries toward same target
ENTRY_SEPARATION    = 5       # min points of pullback before adding next entry
TARGET_EXPIRY_HOURS = 24      # drop a target if not hit within 24 hours

# ── Indicators ────────────────────────────────────────────────────────────────
EMA_FAST    = 10
EMA_SLOW    = 20
RSI_PERIOD  = 14
RSI_OB      = 70
RSI_OS      = 30
ATR_PERIOD  = 14

# ── News filter ───────────────────────────────────────────────────────────────
NEWS_PAUSE_MINUTES = 30
NEWS_CURRENCIES    = ["USD", "XAU"]

# ── Engine ────────────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 300   # 5 minutes — fast enough to catch pyramid entries
CANDLES_NEEDED        = 200
