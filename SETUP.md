# Trading Signal Bot — Setup Guide

## Prerequisites
- Python 3.11+ installed (Windows)
- MetaTrader 5 installed and logged into your FTMO account
- A Telegram account

---

## Step 1 — Install dependencies

Open a terminal in this folder and run:

```
pip install -r requirements.txt
```

> **Note:** `MetaTrader5` package only works on Windows.

---

## Step 2 — Create your Telegram bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot` and follow the prompts — you'll get a **bot token** like `7123456789:AAFxxxxxxxx`
3. Start a chat with your new bot (search its username, press Start)
4. To get your **chat ID**: message `@userinfobot` in Telegram → it replies with your ID

---

## Step 3 — Configure

Open `config.py` and fill in:

```python
TELEGRAM_TOKEN   = "7123456789:AAFxxxxxxxx"   # your bot token
TELEGRAM_CHAT_ID = "123456789"                # your chat ID (as a string)
```

If your FTMO MT5 is already open and logged in, leave the MT5 login fields as `None`.
If you want the bot to log in automatically, fill in:

```python
MT5_LOGIN    = 12345678       # your MT5 account number
MT5_PASSWORD = "yourpassword"
MT5_SERVER   = "FTMO-Live4"   # exact server name from MT5
```

---

## Step 4 — Verify your symbol names

In MT5, open the Market Watch panel and check the exact names of the symbols.
They may differ from `XAUUSD.s` and `XAUUSD.QTR` depending on your broker config.
Update `SYMBOLS` in `config.py` to match exactly.

---

## Step 5 — Run the bot

Make sure MT5 is open and logged in, then:

```
python main.py
```

You'll get a Telegram message confirming the bot started.
Signals arrive as formatted messages like:

```
🟢 BUY — XAUUSD.s
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Entry:   2341.50
TP1:     2348.90  (+7.40)
TP2:     2354.45  (+12.95)
SL:      2337.40  (-4.10)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Lots:    0.10  (1% risk)
R:R      TP1 1:1.8  |  TP2 1:3.2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pattern: Bullish Pin Bar
Trend:   Bullish (M15 + H1)
ATR:     4.93
News:    Clear ✅
```

---

## Risk rules baked in

| Rule | Limit | Default setting |
|------|-------|-----------------|
| Risk per trade | 1% of balance | $100 on $10k |
| Daily loss pause | 4.5% of balance | $450 on $10k |
| Max drawdown pause | 9% of balance | $900 on $10k |
| News pause | ±30 min around high-impact USD/XAU events | automatic |

All limits are set slightly inside FTMO's official thresholds to give a buffer.

---

## Keeping it running

The bot needs to run while MT5 is open. Simplest approach:
- Leave it running in a terminal window while you're at your PC
- Or set up Task Scheduler to start `python main.py` at login

---

## Disclaimer

This is a technical analysis tool. No signal system has a guaranteed win rate.
Always check signals manually before placing trades on a funded account.
