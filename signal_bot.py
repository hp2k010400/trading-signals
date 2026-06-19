"""
signal_bot.py — Runs locally on your Windows machine where MT5 is installed.
Uses real-time MT5 prices (zero lag). Sends Telegram alerts when signals fire.
You then execute the trade on MT5 manually in ~30 seconds.

Requirements:
  MT5 open and logged into your FTMO account before running.

Run:
  python signal_bot.py

Signal windows (UTC):
  07:00–10:00  London Breakout (EURUSD, GBPUSD)
  09:00–12:00  DAX ORB (GER40)
  14:00–16:00  NAS100 Open
  All day      H4 EMA alerts (DAX, Oil — rare, ~2-3/month)
"""

import time
import traceback
from datetime import datetime, timezone

import requests
import MetaTrader5 as mt5

import config
import signal_engine
import mt5_client
import news_filter


# ── Telegram ───────────────────────────────────────────────────────────────────

def _send(text: str):
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        print(f"[Telegram] No credentials set.\n{text}\n")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        ).raise_for_status()
    except Exception as e:
        print(f"[Telegram] Failed: {e}")


# ── Signal formatting ──────────────────────────────────────────────────────────

def _format(sig: signal_engine.Signal) -> str:
    emoji = "🟢" if sig.action == "BUY" else "🔴"
    arrow = "▲" if sig.action == "BUY" else "▼"
    now   = datetime.now(timezone.utc).strftime("%H:%M UTC")
    return (
        f"{emoji} <b>{sig.strategy} — {sig.action}</b>\n"
        f"<b>{sig.symbol}</b>\n"
        f"{'━'*28}\n"
        f"{arrow} Entry:  <b>{sig.entry:.2f}</b>\n"
        f"🛑 SL:     <b>{sig.sl:.2f}</b>  ({sig.sl_points:.2f} pts)\n"
        f"{'━'*28}\n"
        f"🎯 Trail stop:\n"
        f"   Move SL to BE when price hits <b>{sig.trail_activate:.2f}</b>\n"
        f"   Then trail <b>{sig.trail_distance:.2f}</b> pts behind price\n"
        f"{'━'*28}\n"
        f"💰 Risk: £<b>{sig.risk_gbp:,.0f}</b> ({sig.risk_pct*100:.1f}%)\n"
        f"📊 Lots: <b>{sig.lots}</b>\n"
        f"📝 {sig.note}\n"
        f"⏰ {now}"
    )


# ── MT5 connection with auto-reconnect ────────────────────────────────────────

def _connect_mt5() -> bool:
    try:
        mt5_client.connect()
        info = mt5.account_info()
        print(f"[MT5] {info.name} | {info.server} | Balance: £{info.balance:,.2f}")
        return True
    except Exception as e:
        print(f"[MT5] Connection failed: {e}")
        return False


# ── Daily schedule message ─────────────────────────────────────────────────────

_last_schedule: str = ""

def _daily_schedule(now: datetime):
    global _last_schedule
    today = now.strftime("%A %d %b")
    if _last_schedule == today:
        return
    _last_schedule = today
    _send(
        f"📅 <b>Signal Bot — {today}</b>\n"
        f"{'━'*28}\n"
        f"⏰ 07:00 UTC — London Breakout (EURUSD, GBPUSD)\n"
        f"⏰ 09:00 UTC — DAX ORB (GER40)\n"
        f"⏰ 14:00 UTC — NAS100 Open\n"
        f"⏰ All day   — H4 EMA (DAX, Oil — rare)\n"
        f"{'━'*28}\n"
        f"Balance: £{config.ACCOUNT_BALANCE:,.0f} | Using real-time MT5 data"
    )


# ── Main loop ──────────────────────────────────────────────────────────────────

def run():
    print("[Bot] Connecting to MT5...")
    if not _connect_mt5():
        print("[Bot] Could not connect to MT5. Make sure MT5 is open and logged in.")
        return

    _send(
        f"🤖 <b>Signal Bot Online</b>\n"
        f"{'━'*28}\n"
        f"Data:       Real-time MT5 (zero lag)\n"
        f"Balance:    £{config.ACCOUNT_BALANCE:,.0f}\n"
        f"Strategies: London Breakout | DAX ORB | NAS100 Open | H4 EMA\n"
        f"Polling:    every {config.POLL_INTERVAL_SECONDS}s"
    )

    print(f"[Bot] Running — polling every {config.POLL_INTERVAL_SECONDS}s. Ctrl+C to stop.")

    while True:
        try:
            now = datetime.now(timezone.utc)

            # Daily schedule at 06:55 UTC
            if now.hour == 6 and now.minute >= 55:
                _daily_schedule(now)

            # Skip during news
            blocked, news_msg = news_filter.is_news_window()
            if blocked:
                print(f"[{now.strftime('%H:%M')}] News: {news_msg}")
                time.sleep(config.POLL_INTERVAL_SECONDS)
                continue

            # Only poll during active windows to reduce MT5 calls
            active = (
                (7  <= now.hour < 12) or   # London Breakout + DAX ORB
                (8  <= now.hour < 16) or   # H4 EMA DAX session
                (14 <= now.hour < 21)      # NAS100 + Oil H4
            )
            if not active:
                time.sleep(config.POLL_INTERVAL_SECONDS)
                continue

            signals = signal_engine.get_all_signals()

            for sig in signals:
                print(f"[{now.strftime('%H:%M')}] SIGNAL: {sig.strategy} {sig.action} "
                      f"{sig.symbol} @ {sig.entry:.2f} | SL {sig.sl:.2f} | Lots {sig.lots}")
                _send(_format(sig))

            if not signals:
                print(f"[{now.strftime('%H:%M')}] No signals")

        except KeyboardInterrupt:
            print("\n[Bot] Stopped.")
            mt5.shutdown()
            break
        except Exception:
            err = traceback.format_exc()
            print(f"[Bot] Error:\n{err}")
            # Try to reconnect MT5 if it dropped
            if "MT5" in err or "MetaTrader" in err:
                print("[Bot] Attempting MT5 reconnect...")
                _connect_mt5()

        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
