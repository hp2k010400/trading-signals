import config


def is_trading_allowed() -> tuple[bool, str]:
    return True, ""


def risk_amount_usd() -> float:
    return config.ACCOUNT_BALANCE * (config.RISK_PER_ENTRY_PCT / 100)
