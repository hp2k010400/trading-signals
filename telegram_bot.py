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

    if sig.entry_num == 1:
        header = f"<b>{direction} — {sig.symbol}</b>"
    else:
        header = f"<b>{direction} — {sig.symbol}  [DCA Entry {sig.entry_num}/3]</b>"

    loss_usd  = round(sig.lots * config.SL_POINTS * 100, 0)
    win_usd   = round(sig.lots * sig.tp_points * 100, 0)
    stars     = "⭐" * sig.confirmations

    msg = (
        f"{header}\n"
        f"{'━' * 28}\n"
        f"Entry:  <b>{sig.entry:.2f}</b>\n"
        f"TP:     <b>{sig.tp:.2f}</b>   (+{sig.tp_points:.1f} pts)\n"
        f"SL:     <b>{sig.sl:.2f}</b>   (-{sig.sl_points} pts)\n"
        f"{'━' * 28}\n"
        f"Lots:   <b>{sig.lots}</b>   {stars}\n"
        f"Win:    ~${win_usd:.0f}  |  Loss: ~${loss_usd:.0f}\n"
        f"R:R     1:{sig.rr}\n"
        f"{'━' * 28}\n"
        f"Signal: {sig.pattern}\n"
        f"News:   Clear ✅"
    )
    _send(msg)


def send_tp_hit(symbol: str, tp: float):
    _send(f"✅ <b>TP HIT — {symbol}</b>\nTarget {tp:.2f} reached — close all entries!")


def send_news_warning(msg: str):
    _send(f"⚠️ <b>News Pause</b>\n{msg}\nSignals paused ±{config.NEWS_PAUSE_MINUTES} min")


def send_risk_warning(msg: str):
    _send(f"🚨 <b>FTMO Risk Limit</b>\n{msg}\nTrading paused.")


def send_startup():
    symbols = ", ".join(config.SYMBOLS)
    _send(
        f"✅ <b>Signal Bot Started</b>\n"
        f"Watching: {symbols}\n"
        f"Strategy: S/R targeting | Fixed 15pt SL | Up to 3 DCA entries\n"
        f"Risk: {config.RISK_PER_ENTRY_PCT}% per entry | ${config.ACCOUNT_BALANCE:,.0f} account"
    )
