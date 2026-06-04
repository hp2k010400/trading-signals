import requests
import config
from signal_engine import Signal

_API = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"


def _send(text: str):
    try:
        resp = requests.post(_API, json={
            "chat_id":    config.TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        }, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[Telegram] Send failed: {e}")


def send_signal(sig: Signal):
    direction = "🟢 BUY" if sig.action == "BUY" else "🔴 SELL"
    pips_sl   = abs(sig.entry - sig.sl)
    pips_tp1  = abs(sig.tp1  - sig.entry)
    pips_tp2  = abs(sig.tp2  - sig.entry)

    msg = (
        f"<b>{direction} — {sig.symbol}</b>\n"
        f"{'━' * 28}\n"
        f"Entry:   <b>{sig.entry:.2f}</b>\n"
        f"TP1:     <b>{sig.tp1:.2f}</b>  (+{pips_tp1:.2f})\n"
        f"TP2:     <b>{sig.tp2:.2f}</b>  (+{pips_tp2:.2f})\n"
        f"SL:      <b>{sig.sl:.2f}</b>   (-{pips_sl:.2f})\n"
        f"{'━' * 28}\n"
        f"Lots:    <b>{sig.lots}</b>  (1% risk)\n"
        f"R:R      TP1 1:{sig.rr1}  |  TP2 1:{sig.rr2}\n"
        f"{'━' * 28}\n"
        f"Pattern: {sig.pattern}\n"
        f"Trend:   {sig.trend} (M15 + H1)\n"
        f"ATR:     {sig.atr}\n"
        f"News:    Clear ✅"
    )
    _send(msg)


def send_news_warning(msg: str):
    _send(f"⚠️ <b>News Pause Active</b>\n{msg}\nSignals paused ±{config.NEWS_PAUSE_MINUTES} min")


def send_risk_warning(msg: str):
    _send(f"🚨 <b>FTMO Risk Limit</b>\n{msg}\nTrading paused for today.")


def send_startup():
    symbols = ", ".join(config.SYMBOLS)
    _send(
        f"✅ <b>Signal Bot Started</b>\n"
        f"Watching: {symbols}\n"
        f"Timeframe: {config.PRIMARY_TF} (filter: {config.TREND_TF})\n"
        f"Risk: {config.RISK_PER_TRADE_PCT}% per trade | ${config.ACCOUNT_BALANCE:,} account"
    )
