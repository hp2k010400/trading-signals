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
            elif active.sl_hit(price):
                telegram_bot.send_sl_hit(symbol, active.sl_level, active.entry_count)
                tgt.clear(symbol)
        except Exception:
            pass


def run():
    telegram_bot.send_startup()
    print(f"[Bot] Started — polling every {config.POLL_INTERVAL_SECONDS}s")

    while True:
        try:
            now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

            blocked, news_msg = news_filter.is_news_window()
            if blocked:
                print(f"[{now}] News window: {news_msg}")
                time.sleep(config.POLL_INTERVAL_SECONDS)
                continue

            allowed, risk_msg = risk_manager.is_trading_allowed()
            if not allowed:
                print(f"[{now}] Risk blocked: {risk_msg}")
                telegram_bot.send_risk_warning(risk_msg)
                time.sleep(60)
                continue

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
