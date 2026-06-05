//+------------------------------------------------------------------+
//| SignalBot.mq5                                                    |
//| Auto-trading EA — mirrors the Railway signal bot logic in MT5    |
//| No Python needed — runs entirely inside MetaTrader 5             |
//+------------------------------------------------------------------+
#property copyright "GC4C Signal Bot"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>

//── Inputs ──────────────────────────────────────────────────────────
input string   TelegramToken    = "8660365489:AAETZxHhTc-OB8ne19LS4o3Jn5z0LvhXyMo";
input string   TelegramChatId   = "5515778237";
input int      PollSeconds      = 300;    // check every 5 minutes
input double   LotSize          = 0.10;   // starting lot size
input int      SlPoints         = 7;      // fixed stop loss in points
input int      RsiPeriod        = 14;
input double   RsiOverbought    = 75.0;
input double   RsiOversold      = 20.0;
input int      EmaFast          = 10;
input int      EmaSlow          = 20;
input int      RoundNumberStep  = 25;     // gold clusters every 25 pts
input int      TpBuffer         = 2;      // close TP 2pts before S/R
input bool     AutoExecute      = true;   // set false to just send signals without trading

//── Symbols to watch ────────────────────────────────────────────────
string Symbols[] = {"XAUUSD.s", "XAUUSD.QTR"};

//── State ────────────────────────────────────────────────────────────
CTrade trade;
string lastSignal[];   // last signal direction per symbol

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(20250605);
   trade.SetDeviationInPoints(20);
   trade.SetTypeFilling(ORDER_FILLING_IOC);

   ArrayResize(lastSignal, ArraySize(Symbols));
   for(int i = 0; i < ArraySize(Symbols); i++) lastSignal[i] = "";

   EventSetTimer(PollSeconds);
   Print("[SignalBot] Started — checking every ", PollSeconds, "s");

   string mode = AutoExecute ? "AUTO-EXECUTE ON" : "Notify only";
   SendTelegram("✅ <b>MT5 Signal Bot Active</b>\n"
      + "Account: " + AccountInfoString(ACCOUNT_NAME) + "\n"
      + "Balance: $" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + "\n"
      + "Watching: XAUUSD.s, XAUUSD.QTR\n"
      + "Mode: " + mode);

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
}

//+------------------------------------------------------------------+
void OnTimer()
{
   for(int i = 0; i < ArraySize(Symbols); i++)
      CheckSymbol(Symbols[i], i);
}

//+------------------------------------------------------------------+
void CheckSymbol(string symbol, int idx)
{
   // Ensure symbol is in Market Watch
   if(!SymbolSelect(symbol, true)) return;

   // ── Fetch bars ─────────────────────────────────────────────────
   MqlRates bars[];
   int count = ArrayCopyRates(bars, symbol, PERIOD_M15);
   if(count < 50) return;
   ArraySetAsSeries(bars, true);   // bars[0] = newest

   // ── Trend: EMA fast vs slow on last closed bar (index 1) ───────
   double emaF = GetEMA(symbol, PERIOD_M15, EmaFast, 1);
   double emaS = GetEMA(symbol, PERIOD_M15, EmaSlow, 1);
   if(emaF == 0 || emaS == 0) return;

   string trend = "flat";
   if(emaF > emaS) trend = "bull";
   if(emaF < emaS) trend = "bear";
   if(trend == "flat") return;

   // ── RSI filter ─────────────────────────────────────────────────
   double rsi = GetRSI(symbol, PERIOD_M15, RsiPeriod, 1);
   if(trend == "bull" && rsi > RsiOverbought) return;
   if(trend == "bear" && rsi < RsiOversold)   return;

   // ── Confirmation: candle pattern OR RSI momentum ───────────────
   bool patternOk = false;
   string patternName = "";

   if(trend == "bull")
   {
      if(IsBullishEngulfing(bars))  { patternOk = true; patternName = "Bullish Engulfing"; }
      if(IsBullishPinBar(bars))     { patternOk = true; patternName = "Bullish Pin Bar"; }
      if(!patternOk && rsi > 50)    { patternOk = true; patternName = "RSI Momentum"; }
   }
   else
   {
      if(IsBearishEngulfing(bars))  { patternOk = true; patternName = "Bearish Engulfing"; }
      if(IsBearishPinBar(bars))     { patternOk = true; patternName = "Bearish Pin Bar"; }
      if(!patternOk && rsi < 50)    { patternOk = true; patternName = "RSI Momentum"; }
   }

   if(!patternOk) return;

   // ── Current price ───────────────────────────────────────────────
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick)) return;
   double price = (trend == "bull") ? tick.ask : tick.bid;

   // ── Find TP from nearest S/R level ─────────────────────────────
   double tp = FindTP(symbol, price, trend, bars);
   if(tp == 0) return;

   // ── SL and direction ───────────────────────────────────────────
   double sl     = (trend == "bull") ? price - SlPoints : price + SlPoints;
   string action = (trend == "bull") ? "BUY" : "SELL";

   // ── Dedup: don't repeat same signal ────────────────────────────
   if(lastSignal[idx] == action) return;
   lastSignal[idx] = action;

   double tpPts = MathAbs(tp - price);
   double rr    = (SlPoints > 0) ? tpPts / SlPoints : 0;
   double winUsd  = LotSize * tpPts * 100;
   double lossUsd = LotSize * SlPoints * 100;

   Print("[Signal] ", action, " ", symbol,
         " | Price:", DoubleToString(price,2),
         " TP:", DoubleToString(tp,2),
         " SL:", DoubleToString(sl,2),
         " Lots:", LotSize,
         " Pattern:", patternName);

   // ── Send Telegram signal ────────────────────────────────────────
   string emoji = (action == "BUY") ? "🟢" : "🔴";
   string msg   = emoji + " <b>" + action + " — " + symbol + "</b>\n"
      + "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
      + "Entry:  <b>" + DoubleToString(price, 2) + "</b>\n"
      + "TP:     <b>" + DoubleToString(tp, 2) + "</b>  (+" + DoubleToString(tpPts,1) + " pts)\n"
      + "SL:     <b>" + DoubleToString(sl, 2) + "</b>  (-" + IntegerToString(SlPoints) + " pts)\n"
      + "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
      + "Lots:   <b>" + DoubleToString(LotSize,2) + "</b>\n"
      + "Win:    ~$" + DoubleToString(winUsd,0) + "  |  Loss: ~$" + DoubleToString(lossUsd,0) + "\n"
      + "R:R     1:" + DoubleToString(rr, 2) + "\n"
      + "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
      + "Signal: " + patternName + "\n"
      + "RSI:    " + DoubleToString(rsi,1);
   SendTelegram(msg);

   // ── Execute trade ───────────────────────────────────────────────
   if(!AutoExecute) return;

   bool ok;
   if(action == "BUY")
      ok = trade.Buy(LotSize, symbol, tick.ask, sl, tp, "signal-bot");
   else
      ok = trade.Sell(LotSize, symbol, tick.bid, sl, tp, "signal-bot");

   if(ok)
   {
      string confirm = "✅ <b>AUTO-EXECUTED</b>\n"
         + action + " " + symbol + "\n"
         + "Filled @ " + DoubleToString((action=="BUY") ? tick.ask : tick.bid, 2)
         + "  Ticket: #" + IntegerToString((int)trade.ResultOrder());
      Print(confirm);
      SendTelegram(confirm);
   }
   else
   {
      string err = "⚠️ Execution failed: " + IntegerToString(trade.ResultRetcode())
         + " — " + trade.ResultComment();
      Print(err);
      SendTelegram(err);
   }
}

//+------------------------------------------------------------------+
//── Indicators ───────────────────────────────────────────────────────
//+------------------------------------------------------------------+
double GetEMA(string sym, ENUM_TIMEFRAMES tf, int period, int shift)
{
   int handle = iMA(sym, tf, period, 0, MODE_EMA, PRICE_CLOSE);
   if(handle == INVALID_HANDLE) return 0;
   double buf[];
   ArraySetAsSeries(buf, true);
   if(CopyBuffer(handle, 0, shift, 1, buf) != 1) return 0;
   IndicatorRelease(handle);
   return buf[0];
}

double GetRSI(string sym, ENUM_TIMEFRAMES tf, int period, int shift)
{
   int handle = iRSI(sym, tf, period, PRICE_CLOSE);
   if(handle == INVALID_HANDLE) return 50;
   double buf[];
   ArraySetAsSeries(buf, true);
   if(CopyBuffer(handle, 0, shift, 1, buf) != 1) return 50;
   IndicatorRelease(handle);
   return buf[0];
}

//+------------------------------------------------------------------+
//── Candlestick patterns (use index 1 = last closed candle) ──────────
//+------------------------------------------------------------------+
bool IsBullishEngulfing(MqlRates &b[])
{
   return (b[2].close < b[2].open &&   // prev bearish
           b[1].close > b[1].open &&   // curr bullish
           b[1].open  < b[2].close &&
           b[1].close > b[2].open);
}

bool IsBearishEngulfing(MqlRates &b[])
{
   return (b[2].close > b[2].open &&
           b[1].close < b[1].open &&
           b[1].open  > b[2].close &&
           b[1].close < b[2].open);
}

bool IsBullishPinBar(MqlRates &b[])
{
   double rng   = b[1].high - b[1].low;
   if(rng == 0) return false;
   double body  = MathAbs(b[1].close - b[1].open);
   double lower = MathMin(b[1].open, b[1].close) - b[1].low;
   return (lower >= rng * 0.6 && body <= rng * 0.3);
}

bool IsBearishPinBar(MqlRates &b[])
{
   double rng   = b[1].high - b[1].low;
   if(rng == 0) return false;
   double body  = MathAbs(b[1].close - b[1].open);
   double upper = b[1].high - MathMax(b[1].open, b[1].close);
   return (upper >= rng * 0.6 && body <= rng * 0.3);
}

//+------------------------------------------------------------------+
//── S/R levels → TP target ───────────────────────────────────────────
//+------------------------------------------------------------------+
double FindTP(string symbol, double price, string trend, MqlRates &bars[])
{
   double minDist = SlPoints + TpBuffer;
   double best    = 0;

   // Daily pivot from yesterday
   MqlRates daily[];
   if(ArrayCopyRates(daily, symbol, PERIOD_D1) >= 2)
   {
      ArraySetAsSeries(daily, true);
      double H = daily[1].high, L = daily[1].low, C = daily[1].close;
      double PP = (H + L + C) / 3.0;
      double levels[] = {PP, 2*PP-L, 2*PP-H, PP+(H-L), PP-(H-L)};

      for(int i = 0; i < ArraySize(levels); i++)
      {
         double lvl = levels[i];
         if(trend == "bull" && lvl > price + minDist)
         {
            double candidate = lvl - TpBuffer;
            if(best == 0 || candidate < best) best = candidate;
         }
         if(trend == "bear" && lvl < price - minDist)
         {
            double candidate = lvl + TpBuffer;
            if(best == 0 || candidate > best) best = candidate;
         }
      }
   }

   // Round number levels
   double step = RoundNumberStep;
   double base = MathRound(price / step) * step;
   for(int i = -6; i <= 6; i++)
   {
      double lvl = base + step * i;
      if(trend == "bull" && lvl > price + minDist)
      {
         double candidate = lvl - TpBuffer;
         if(best == 0 || candidate < best) best = candidate;
      }
      if(trend == "bear" && lvl < price - minDist)
      {
         double candidate = lvl + TpBuffer;
         if(best == 0 || candidate > best) best = candidate;
      }
   }

   return best;
}

//+------------------------------------------------------------------+
//── Telegram ─────────────────────────────────────────────────────────
//+------------------------------------------------------------------+
void SendTelegram(string text)
{
   string url  = "https://api.telegram.org/bot" + TelegramToken + "/sendMessage";
   string body = "{\"chat_id\":\"" + TelegramChatId
               + "\",\"text\":\"" + EscapeJson(text)
               + "\",\"parse_mode\":\"HTML\"}";

   char   postArr[], resultArr[];
   string headers    = "Content-Type: application/json\r\n";
   string resHeaders = "";

   StringToCharArray(body, postArr, 0, StringLen(body));
   ArrayResize(postArr, ArraySize(postArr) - 1);

   int res = WebRequest("POST", url, headers, 8000, postArr, resultArr, resHeaders);
   if(res < 0)
      Print("[Telegram] Error ", GetLastError(),
            " — add https://api.telegram.org to Tools > Options > Expert Advisors > Allow WebRequests");
}

string EscapeJson(string s)
{
   StringReplace(s, "\\", "\\\\");
   StringReplace(s, "\"", "\\\"");
   StringReplace(s, "\n", "\\n");
   return s;
}
//+------------------------------------------------------------------+
