"""
FTMO risk management.
Without a live MT5 connection we can't read account equity in real time.
Lot sizing is still FTMO-safe — monitor your FTMO dashboard manually and
pause the bot if you approach the daily/max drawdown limits.
"""
import config


def is_trading_allowed() -> tuple[bool, str]:
    return True, ""


def risk_amount_usd() -> float:
    return config.ACCOUNT_BALANCE * (config.RISK_PER_TRADE_PCT / 100)
