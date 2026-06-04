"""
Central configuration — secrets are read from environment variables.
Set these in Railway dashboard, never hardcode them here.
"""
import os

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Twelve Data ───────────────────────────────────────────────────────────────
TWELVE_DATA_KEY  = os.environ.get("TWELVE_DATA_KEY", "")

# ── Symbols to watch ──────────────────────────────────────────────────────────
SYMBOLS = ["XAUUSD.s", "XAUUSD.QTR"]

# ── Timeframes ────────────────────────────────────────────────────────────────
PRIMARY_TF = "M15"
TREND_TF   = "H1"

# ── Risk management (FTMO $10k rules) ─────────────────────────────────────────
ACCOUNT_BALANCE      = float(os.environ.get("ACCOUNT_BALANCE", "10000"))
RISK_PER_TRADE_PCT   = 1.0
DAILY_LOSS_LIMIT_PCT = 4.5
MAX_DRAWDOWN_PCT     = 9.0
MIN_LOT              = 0.01
MAX_LOT              = 5.0

# ── Signal logic ──────────────────────────────────────────────────────────────
EMA_FAST      = 20
EMA_SLOW      = 50
RSI_PERIOD    = 14
RSI_OB        = 70
RSI_OS        = 30
ATR_PERIOD    = 14
ATR_SL_MULT   = 1.5
ATR_TP1_MULT  = 2.0
ATR_TP2_MULT  = 3.5

# ── News filter ───────────────────────────────────────────────────────────────
NEWS_PAUSE_MINUTES = 30
NEWS_CURRENCIES    = ["USD", "XAU"]

# ── Engine ────────────────────────────────────────────────────────────────────
# 900s = 15 min, aligns with M15 candle close — keeps Twelve Data usage under free tier limit
POLL_INTERVAL_SECONDS = 900
CANDLES_NEEDED        = 200
