import time
import traceback
from datetime import datetime, timezone

import requests

import signal_engine
import range_engine
import telegram_bot
import news_filter
import risk_manager
import targets as tgt
import data_client
import config


# ── Telegram helper (direct — doesn't rely on telegram_bot for range signals) ──
_TG_API = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"

def _send(text: str):
    try:
        requests.post(_TG_API, json={
            "chat_id":    config.TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        }, timeout=5)
    except Exception:
        pass


def _send_range_signal(sig: range_engine.RangeSignal):
    emoji = "🟡" if sig.action == "BUY" else "🟠"
    _send(
        f"{emoji} <b>RANGE {sig.action} — {sig.symbol}</b>\n"
        f"{'━' * 26}\n"
        f"Entry:  <b>{sig.entry:.2f}</b>\n"
        f"TP:     <b>{sig.tp:.2f}</b>  (+{sig.tp_pts:.1f}pts)\n"
        f"SL:     <b>{sig.sl:.2f}</b>  (-{sig.sl_pts:.1f}pts)\n"
        f"{'━' * 26}\n"
        f"Range:  {sig.range_low:.2f} — {sig.range_high:.2f}  ({sig.range_width:.1f}pts)\n"
        f"Lots:   <b>{sig.lots:.2f}</b>  R:R 1:{sig.rr:.2f}\n"
        f"Signal: {sig.pattern}  RSI check ✓\n"
        f"H4 ADX: {sig.adx:.1f} (range mode ✓)\n"
        f"⚠️ Pre-NY close at 12:45 UTC if still open"
    )


def _check_exits():
    """Notify if any active trend target has hit TP or SL since last poll."""
    for symbol in list(config.SYMBOLS):
        active = tgt.get(symbol)
        if active is None:
            continue
        try:
            tick = data_client.get_tick(symbol)
            price = tick["ask"]
            if active.tp_hit(price):
                telegram_bot.send_tp_hit(symbol, active.tp)
                tgt.clear(symbol)
                risk_manager.record_tp()
            elif active.sl_hit(price):
                telegram_bot.send_sl_hit(symbol, active.sl_level, active.entry_count)
                tgt.clear(symbol)
                risk_manager.record_sl(symbol)
        except Exception:
            pass


def _market_open() -> bool:
    """Gold trades Sun 21:00 UTC → Fri 21:00 UTC. Closed all Saturday."""
    now = datetime.now(timezone.utc)
    wd  = now.weekday()   # 0=Mon … 5=Sat, 6=Sun
    if wd == 5:
        return False                        # Saturday — always closed
    if wd == 6 and now.hour < 21:
        return False                        # Sunday before 9pm UTC — not yet open
    if wd == 4 and now.hour >= 21:
        return False                        # Friday after 9pm UTC — closed for weekend
    return True


# ── Deduplication for range signals — don't fire same direction twice in a row ─
_last_range: dict[str, str] = {}

def _is_new_range(symbol: str, action: str) -> bool:
    if _last_range.get(symbol) == action:
        return False
    _last_range[symbol] = action
    return True

def _reset_range(symbol: str):
    _last_range[symbol] = ""


def run():
    telegram_bot.send_startup()
    print(f"[Bot] Started — polling every {config.POLL_INTERVAL_SECONDS}s")
    print(f"[Bot] Trend bot: H4 ADX > 25 | Range bot: H4 ADX < {config.RANGE_ADX_MAX}")

    while True:
        try:
            now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

            if not _market_open():
                print(f"[{now}] Market closed — weekend")
                time.sleep(config.POLL_INTERVAL_SECONDS)
                continue

            blocked, news_msg = news_filter.is_news_window()
            if blocked:
                print(f"[{now}] News window: {news_msg}")
                time.sleep(config.POLL_INTERVAL_SECONDS)
                continue

            allowed, risk_msg = risk_manager.is_trading_allowed()
            if not allowed:
                print(f"[{now}] Risk blocked: {risk_msg}")
                if not getattr(main, '_cb_notified', False):
                    telegram_bot.send_risk_warning(risk_msg)
                    main._cb_notified = True
                time.sleep(60)
                continue
            main._cb_notified = False  # reset when trading resumes

            _check_exits()

            for symbol in config.SYMBOLS:
                print(f"[{now}] Checking {symbol}...")

                # ── Trend signal ─────────────────────────────────────────────
                sig = signal_engine.evaluate(symbol)
                if sig:
                    label = f"Entry {sig.entry_num}" if sig.entry_num > 1 else "Signal"
                    print(f"  >> TREND {label}: {sig.action} {symbol} | Entry {sig.entry:.2f} | TP {sig.tp:.2f}")
                    telegram_bot.send_signal(sig)

                # ── Range signal ──────────────────────────────────────────────
                rsig = range_engine.evaluate(symbol)
                if rsig and _is_new_range(symbol, rsig.action):
                    print(f"  >> RANGE: {rsig.action} {symbol} | Entry {rsig.entry:.2f} | Range {rsig.range_low:.2f}-{rsig.range_high:.2f}")
                    _send_range_signal(rsig)
                elif rsig is None:
                    _reset_range(symbol)

        except KeyboardInterrupt:
            print("\n[Bot] Stopped.")
            break
        except Exception:
            print(f"[Bot] Error:\n{traceback.format_exc()}")

        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
