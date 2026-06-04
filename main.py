"""
Entry point. Runs on Railway as a background worker.
"""
import time
import traceback
from datetime import datetime, timezone

import signal_engine
import telegram_bot
import news_filter
import risk_manager
import config

_last_signal: dict[str, str] = {}


def _should_send(symbol: str, action: str) -> bool:
    prev = _last_signal.get(symbol)
    if prev == action:
        return False
    _last_signal[symbol] = action
    return True


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

            for symbol in config.SYMBOLS:
                print(f"[{now}] Checking {symbol}...")
                sig = signal_engine.evaluate(symbol)
                if sig and _should_send(symbol, sig.action):
                    print(f"  >> SIGNAL: {sig.action} {symbol} | Entry {sig.entry} | Lots {sig.lots}")
                    telegram_bot.send_signal(sig)
                else:
                    if sig is None:
                        _last_signal[symbol] = ""

        except KeyboardInterrupt:
            print("\n[Bot] Stopped.")
            break
        except Exception:
            print(f"[Bot] Error:\n{traceback.format_exc()}")

        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
