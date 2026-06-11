import time
import traceback
from datetime import datetime, timezone

import signal_engine
import telegram_bot
import news_filter
import risk_manager
import targets as tgt
import data_client
import config


def _check_exits():
    """Notify if any active target has hit TP or SL since last poll."""
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


def run():
    telegram_bot.send_startup()
    print(f"[Bot] Started — polling every {config.POLL_INTERVAL_SECONDS}s")

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
                sig = signal_engine.evaluate(symbol)
                if sig:
                    label = f"Entry {sig.entry_num}" if sig.entry_num > 1 else "Signal"
                    print(f"  >> {label}: {sig.action} {symbol} | Entry {sig.entry:.2f} | TP {sig.tp:.2f} | Lots {sig.lots}")
                    telegram_bot.send_signal(sig)

        except KeyboardInterrupt:
            print("\n[Bot] Stopped.")
            break
        except Exception:
            print(f"[Bot] Error:\n{traceback.format_exc()}")

        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
