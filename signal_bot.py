"""
signal_bot.py — Runs 24/7 on Railway. Sends Telegram alerts when signals fire.
You execute the trade manually on MT5 — no automation needed.

Signals sent:
  07:00–10:00 UTC  London Breakout  (EURUSD, GBPUSD)
  09:00–12:00 UTC  DAX ORB          (GER40)
  14:00–16:00 UTC  NAS100 Open      (NAS100)
  Throughout day   H4 EMA           (DAX, Oil — rare but high edge)

Deploy:
  Railway → connect GitHub repo → set env vars → deploy
  Env vars: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, ACCOUNT_BALANCE

Run locally:
  python signal_bot.py
"""

import time
import traceback
from datetime import datetime, timezone

import requests

import config
import signal_engine
import news_filter


# ── Telegram ───────────────────────────────────────────────────────────────────

def _send(text: str):
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        print(f"[Telegram] No credentials — would have sent:\n{text}\n")
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id":    config.TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        }, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"[Telegram] Send failed: {e}")


# ── Signal formatting ──────────────────────────────────────────────────────────

def _format(sig: signal_engine.Signal) -> str:
    emoji  = "🟢" if sig.action == "BUY" else "🔴"
    arrow  = "▲" if sig.action == "BUY" else "▼"
    now    = datetime.now(timezone.utc).strftime("%H:%M UTC")

    return (
        f"{emoji} <b>{sig.strategy} — {sig.action}</b>\n"
        f"<b>{sig.symbol_mt5}</b>\n"
        f"{'━'*28}\n"
        f"{arrow} Entry:   <b>{sig.entry:.2f}</b>\n"
        f"🛑 SL:      <b>{sig.sl:.2f}</b>  ({sig.sl_points:.2f} pts)\n"
        f"{'━'*28}\n"
        f"🎯 Trail stop:\n"
        f"   Once price hits <b>{sig.trail_activate:.2f}</b> → move SL to breakeven\n"
        f"   Then trail by <b>{sig.trail_distance:.2f}</b> pts behind price\n"
        f"{'━'*28}\n"
        f"💰 Risk: £<b>{sig.risk_gbp:,.0f}</b> ({sig.risk_pct*100:.1f}% of balance)\n"
        f"📝 {sig.note}\n"
        f"⏰ {now}"
    )


def _format_breakeven(sig: signal_engine.Signal) -> str:
    return (
        f"⚡ <b>MOVE SL TO BREAKEVEN</b>\n"
        f"{sig.symbol_mt5} {sig.action} — price hit +1R\n"
        f"Move SL to <b>{sig.entry:.2f}</b> now\n"
        f"Then trail by <b>{sig.trail_distance:.2f}</b> pts"
    )


# ── Daily schedule announcement ────────────────────────────────────────────────

_last_daily_msg: str = ""

def _send_daily_schedule(now: datetime):
    global _last_daily_msg
    today = now.strftime("%A %d %b")
    if _last_daily_msg == today:
        return
    _last_daily_msg = today

    _send(
        f"📅 <b>Signal Bot — {today}</b>\n"
        f"{'━'*28}\n"
        f"⏰ 07:00 UTC  London Breakout (EURUSD, GBPUSD)\n"
        f"⏰ 09:00 UTC  DAX ORB (GER40)\n"
        f"⏰ 14:00 UTC  NAS100 Open\n"
        f"⏰ All day     H4 EMA alerts (DAX, Oil — rare)\n"
        f"{'━'*28}\n"
        f"Balance: £{config.ACCOUNT_BALANCE:,.0f}"
    )


# ── Main loop ──────────────────────────────────────────────────────────────────

def run():
    print("[Bot] Starting signal bot...")

    _send(
        f"🤖 <b>Signal Bot Online</b>\n"
        f"{'━'*28}\n"
        f"Balance:    £{config.ACCOUNT_BALANCE:,.0f}\n"
        f"Strategies: London Breakout | DAX ORB | NAS100 Open | H4 EMA\n"
        f"Polling:    every {config.POLL_INTERVAL_SECONDS}s\n"
        f"Daily schedule message at 06:55 UTC"
    )

    print(f"[Bot] Running — polling every {config.POLL_INTERVAL_SECONDS}s")

    while True:
        try:
            now = datetime.now(timezone.utc)

            # Daily schedule at 06:55 UTC
            if now.hour == 6 and now.minute >= 55:
                _send_daily_schedule(now)

            # Skip signal detection during high-impact news
            blocked, news_msg = news_filter.is_news_window()
            if blocked:
                print(f"[{now.strftime('%H:%M')}] News block: {news_msg}")
                time.sleep(config.POLL_INTERVAL_SECONDS)
                continue

            # Only check during active strategy windows (saves API calls)
            active = (
                (7  <= now.hour < 10) or   # London Breakout
                (9  <= now.hour < 12) or   # DAX ORB
                (8  <= now.hour < 16) or   # H4 EMA (DAX session)
                (14 <= now.hour < 21)      # NAS100 + Oil H4
            )

            if not active:
                time.sleep(config.POLL_INTERVAL_SECONDS)
                continue

            signals = signal_engine.get_all_signals()

            for sig in signals:
                print(f"[{now.strftime('%H:%M')}] SIGNAL: {sig.strategy} {sig.action} {sig.symbol_mt5} @ {sig.entry:.2f}")
                _send(_format(sig))

            if not signals:
                print(f"[{now.strftime('%H:%M')}] No signals")

        except KeyboardInterrupt:
            print("\n[Bot] Stopped by user.")
            break
        except Exception:
            err = traceback.format_exc()
            print(f"[Bot] Error:\n{err}")
            _send(f"⚠️ <b>Bot error</b>\n<code>{err[:500]}</code>")

        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
