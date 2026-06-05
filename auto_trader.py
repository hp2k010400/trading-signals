"""
auto_trader.py — runs LOCALLY on your laptop where MT5 is installed.
Finds signals using the same logic as the Railway bot, then executes
the trade automatically via MT5 without waiting for a Telegram tap.

Requirements:
    pip install MetaTrader5 pandas pandas-ta requests numpy yfinance

Run: python auto_trader.py
MT5 must be open and logged into your FTMO account first.
"""
import time
import traceback
from datetime import datetime, timezone

import MetaTrader5 as mt5
import requests

import signal_engine
import news_filter
import risk_manager
import config

# ── Telegram confirmation ──────────────────────────────────────────────────────
_API = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"

def _telegram(text: str):
    try:
        requests.post(_API, json={
            "chat_id":    config.TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        }, timeout=5)
    except Exception:
        pass

# ── MT5 connection ─────────────────────────────────────────────────────────────
def connect_mt5():
    if not mt5.initialize():
        raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
    info = mt5.account_info()
    print(f"[MT5] Connected — {info.name} | Server: {info.server} | Balance: ${info.balance:,.2f}")

# ── Trade execution ────────────────────────────────────────────────────────────
def execute(sig) -> str:
    symbol = sig.symbol

    # Make sure the symbol is available
    mt5.symbol_select(symbol, True)

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return f"No tick for {symbol} — check symbol name in MT5 Market Watch"

    order_type = mt5.ORDER_TYPE_BUY if sig.action == "BUY" else mt5.ORDER_TYPE_SELL
    price      = tick.ask if sig.action == "BUY" else tick.bid

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       float(sig.lots),
        "type":         order_type,
        "price":        price,
        "sl":           float(sig.sl),
        "tp":           float(sig.tp),
        "deviation":    20,          # max price slippage in points
        "magic":        20250605,    # EA magic number to identify our trades
        "comment":      "signal-bot",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)

    if result is None:
        return f"order_send returned None — {mt5.last_error()}"
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return f"Order rejected (code {result.retcode}): {result.comment}"

    return f"OK ticket=#{result.order} price={price:.2f}"


# ── Deduplication — don't fire the same signal direction twice in a row ────────
_last_signal: dict[str, str] = {}

def _is_new(symbol: str, action: str) -> bool:
    if _last_signal.get(symbol) == action:
        return False
    _last_signal[symbol] = action
    return True

def _reset(symbol: str):
    _last_signal[symbol] = ""


# ── Main loop ──────────────────────────────────────────────────────────────────
def run():
    connect_mt5()
    info = mt5.account_info()

    _telegram(
        f"🤖 <b>Auto-Trader Started (local)</b>\n"
        f"Account: {info.name}\n"
        f"Balance: ${info.balance:,.2f}\n"
        f"Watching: {', '.join(config.SYMBOLS)}\n"
        f"Risk: {config.RISK_PER_ENTRY_PCT}% per trade — trades will execute automatically"
    )
    print(f"[Bot] Running — polling every {config.POLL_INTERVAL_SECONDS}s")

    while True:
        try:
            now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

            blocked, news_msg = news_filter.is_news_window()
            if blocked:
                print(f"[{now}] News window: {news_msg}")
                time.sleep(config.POLL_INTERVAL_SECONDS)
                continue

            for symbol in config.SYMBOLS:
                print(f"[{now}] Checking {symbol}...")
                sig = signal_engine.evaluate(symbol)

                if sig and _is_new(symbol, sig.action):
                    print(f"  >> SIGNAL: {sig.action} {symbol} | Entry {sig.entry:.2f} | TP {sig.tp:.2f} | SL {sig.sl:.2f} | Lots {sig.lots}")
                    outcome = execute(sig)
                    print(f"  >> EXECUTE: {outcome}")

                    if outcome.startswith("OK"):
                        _telegram(
                            f"{'🟢' if sig.action == 'BUY' else '🔴'} <b>AUTO-EXECUTED — {symbol}</b>\n"
                            f"{'━' * 26}\n"
                            f"{sig.action} executed at market\n"
                            f"TP: <b>{sig.tp:.2f}</b>  |  SL: <b>{sig.sl:.2f}</b>\n"
                            f"Lots: <b>{sig.lots}</b>  |  {outcome}"
                        )
                    else:
                        _telegram(f"⚠️ <b>Execution failed — {symbol}</b>\n{outcome}")

                elif sig is None:
                    _reset(symbol)

        except KeyboardInterrupt:
            print("\n[Bot] Stopped.")
            mt5.shutdown()
            break
        except Exception:
            print(f"[Bot] Error:\n{traceback.format_exc()}")

        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
