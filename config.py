import os

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Twelve Data ───────────────────────────────────────────────────────────────
TWELVE_DATA_KEY  = os.environ.get("TWELVE_DATA_KEY", "")

# ── Symbols ───────────────────────────────────────────────────────────────────
SYMBOLS = ["XAUUSD"]

# ── Timeframes ────────────────────────────────────────────────────────────────
PRIMARY_TF = "M15"

# ── Risk ──────────────────────────────────────────────────────────────────────
ACCOUNT_BALANCE     = float(os.environ.get("ACCOUNT_BALANCE", "10000"))
MIN_LOT             = 0.01
MAX_LOT             = 5.0
FIXED_LOT           = None   # set to a float to override % sizing

# Risk % of account per trade — scales automatically with balance
RISK_PCT_TIER_1     = 0.25    # 1 confirmation  (RSI only)
RISK_PCT_TIER_2     = 0.40    # 2 confirmations (RSI + pattern OR MACD)
RISK_PCT_TIER_3     = 0.50    # 3 confirmations (RSI + pattern + MACD)

# ── SL/TP settings ────────────────────────────────────────────────────────────
SL_POINTS           = 12      # fallback/DCA SL — fresh entries use structure-based SL
TP_BUFFER           = 2       # place TP 2 pts before the S/R level
ENTRY_LEVEL_TOLERANCE = 5    # pts — price must be within this of an S/R level to qualify
SL_BUFFER           = 3       # pts beyond the entry level where SL is placed
MIN_SL_POINTS       = 8       # minimum SL distance regardless of level placement
ROUND_NUMBER_STEP   = 25      # gold clusters around every 25 points

# ── Multi-entry (DCA) settings ────────────────────────────────────────────────
MAX_ENTRIES         = 3       # max entries toward same target
ENTRY_SEPARATION    = 8       # min points of pullback before adding next entry
TARGET_EXPIRY_HOURS = 24      # drop a target if not hit within 24 hours

# ── Indicators ────────────────────────────────────────────────────────────────
EMA_FAST    = 10
EMA_SLOW    = 20
RSI_PERIOD  = 14
RSI_OB      = 75
RSI_OS      = 20
ATR_PERIOD       = 14
EARLY_EXIT_POINTS = 5
ADX_PERIOD       = 14

# ── Trend filters ─────────────────────────────────────────────────────────────
USE_H1_FILTER  = True    # only trade M15 signals in the H1 trend direction
USE_ADX_FILTER = True    # skip signals when ADX < ADX_MIN (ranging market)
ADX_MIN        = 20.0    # below this = ranging, no trade

# ── News filter ───────────────────────────────────────────────────────────────
NEWS_PAUSE_MINUTES = 30
NEWS_CURRENCIES    = ["USD", "XAU"]

# ── Re-entry cooldown ─────────────────────────────────────────────────────────
SL_COOLDOWN_MINUTES = 60   # after an SL, don't re-enter same symbol for this long

# ── Daily loss protection ─────────────────────────────────────────────────────
MAX_CONSECUTIVE_SL  = 3    # pause after this many SLs in a row
SL_PAUSE_HOURS      = 4    # how long to pause trading after hitting the streak limit

# ── Risk ──────────────────────────────────────────────────────────────────────
RISK_PER_ENTRY_PCT  = 1.0  # % of account risked per trade (informational)

# ── Engine ────────────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 300   # 5 minutes — fast enough to catch pyramid entries
CANDLES_NEEDED        = 200
