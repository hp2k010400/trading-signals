//+------------------------------------------------------------------+
//| SignalBot.mq5 — Full Strategy EA                                 |
//| EMA 10/20 trend  |  RSI filter  |  Candle + MACD confirmation   |
//| Variable lot sizing  |  S/R TP targeting  |  DCA pyramid x3     |
//| News filter (ForexFactory)  |  Telegram notifications           |
//| v3: single symbol, SL cooldown, DCA SL fix, consecutive SL cap  |
//+------------------------------------------------------------------+
#property copyright "GC4C Signal Bot"
#property version   "3.00"
#property strict

#include <Trade\Trade.mqh>

//── Inputs ──────────────────────────────────────────────────────────
input string TelegramToken   = "8660365489:AAETZxHhTc-OB8ne19LS4o3Jn5z0LvhXyMo";
input string TelegramChatId  = "5515778237";
input int    PollSeconds     = 300;

// Risk % of account per trade (scales automatically with balance)
input double RiskPct1  = 0.25;   // 1 confirmation — conservative
input double RiskPct2  = 0.40;   // 2 confirmations
input double RiskPct3  = 0.50;   // 3 confirmations — highest conviction

input int    SlPoints       = 7;
input int    TpBuffer       = 2;
input int    RoundNumStep   = 25;

input int    MaxEntries     = 3;
input int    EntrySep       = 5;
input int    TargetExpiryH  = 24;

input int    EmaFast    = 10;
input int    EmaSlow    = 20;
input int    RsiPeriod  = 14;
input double RsiOB      = 75.0;
input double RsiOS      = 20.0;

input int    NewsPauseMin     = 30;
input int    SlCooldownMin    = 60;   // re-entry cooldown after SL (minutes)
input int    MaxConsecutiveSL = 3;    // pause after this many SLs in a row
input int    SlPauseHours     = 4;    // how long to pause after hitting the limit

input bool   AutoExecute = true;

input string Symbol1 = "XAUUSD.s";

//── Symbol ───────────────────────────────────────────────────────────
#define NUM_SYMBOLS 1
string Symbols[NUM_SYMBOLS];

//── Per-symbol state (Global Variables persist between timer calls) ──
string StateKey(int idx, string field) { return "SB_" + IntegerToString(idx) + "_" + field; }
void   SetState(int idx, string f, double v) { GlobalVariableSet(StateKey(idx,f), v); }
double GetState(int idx, string f)           { return GlobalVariableGet(StateKey(idx,f)); }
void   ClearState(int idx)
{
   GlobalVariableDel(StateKey(idx,"active"));
   GlobalVariableDel(StateKey(idx,"dir"));
   GlobalVariableDel(StateKey(idx,"tp"));
   GlobalVariableDel(StateKey(idx,"first_entry"));
   GlobalVariableDel(StateKey(idx,"last_entry"));
   GlobalVariableDel(StateKey(idx,"entries"));
   GlobalVariableDel(StateKey(idx,"created"));
}

//── Risk / cooldown state (also in Global Variables) ─────────────────
string CooldownKey(int idx) { return "SB_" + IntegerToString(idx) + "_sl_time"; }
string SlStreakKey()         { return "SB_sl_streak"; }
string PauseUntilKey()      { return "SB_pause_until"; }

void RecordSL(int idx)
{
   GlobalVariableSet(CooldownKey(idx), (double)TimeCurrent());
   double streak = GlobalVariableGet(SlStreakKey()) + 1;
   GlobalVariableSet(SlStreakKey(), streak);
   if((int)streak >= MaxConsecutiveSL)
   {
      double pauseUntil = (double)(TimeCurrent() + SlPauseHours * 3600);
      GlobalVariableSet(PauseUntilKey(), pauseUntil);
      Print("[Risk] ", (int)streak, " consecutive SLs — paused for ", SlPauseHours, "h");
      SendTelegram("⛔ <b>Trading Paused</b>\n"
         + IntegerToString((int)streak) + " consecutive SLs hit.\n"
         + "Resuming in " + IntegerToString(SlPauseHours) + " hours.");
   }
}

void RecordTP()
{
   GlobalVariableSet(SlStreakKey(), 0);
}

bool IsTradingPaused()
{
   double pauseUntil = GlobalVariableGet(PauseUntilKey());
   if((datetime)pauseUntil > TimeCurrent())
   {
      int minsLeft = (int)((pauseUntil - (double)TimeCurrent()) / 60);
      Print("[Risk] Trading paused — ", minsLeft, " min remaining");
      return true;
   }
   return false;
}

bool InSlCooldown(int idx)
{
   double lastSl = GlobalVariableGet(CooldownKey(idx));
   if(lastSl == 0) return false;
   int elapsedMin = (int)((TimeCurrent() - (datetime)lastSl) / 60);
   if(elapsedMin < SlCooldownMin)
   {
      Print("[Cooldown] ", Symbols[idx], " — ", SlCooldownMin - elapsedMin, " min remaining");
      return true;
   }
   return false;
}

//── Lot sizing ───────────────────────────────────────────────────────
double CalcLots(string sym, double riskPct)
{
   double balance    = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskMoney  = balance * riskPct / 100.0;

   double tickVal    = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double tickSize   = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   if(tickVal <= 0 || tickSize <= 0) return 0.01;

   double riskPerLot = (SlPoints / tickSize) * tickVal;
   if(riskPerLot <= 0) return 0.01;

   double lots    = riskMoney / riskPerLot;
   double lotStep = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   lots = MathFloor(lots / lotStep) * lotStep;

   double minLot = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   return MathMax(minLot, MathMin(lots, maxLot));
}

//── News cache ────────────────────────────────────────────────────────
string   newsCache    = "";
datetime newsFetched  = 0;
#define  NEWS_CACHE_SEC 10800

//── Trade object ──────────────────────────────────────────────────────
CTrade trade;

//+------------------------------------------------------------------+
int OnInit()
{
   Symbols[0] = Symbol1;

   trade.SetExpertMagicNumber(20250605);
   trade.SetDeviationInPoints(20);
   trade.SetTypeFilling(ORDER_FILLING_IOC);

   EventSetTimer(PollSeconds);
   Print("[SignalBot v3] Started — ", Symbol1);

   SendTelegram("✅ <b>MT5 Signal Bot v3 Active</b>\n"
      + "Account: " + AccountInfoString(ACCOUNT_NAME) + "\n"
      + "Balance: $" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + "\n"
      + "Watching: " + Symbol1 + "\n"
      + "SL cooldown: " + IntegerToString(SlCooldownMin) + " min ✓\n"
      + "Consecutive SL cap: " + IntegerToString(MaxConsecutiveSL) + " → " + IntegerToString(SlPauseHours) + "h pause ✓\n"
      + "DCA SL anchored to first entry ✓");

   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); }

void OnTimer()
{
   if(IsTradingPaused()) return;

   bool newsBlocked; string newsMsg;
   CheckNews(newsBlocked, newsMsg);
   if(newsBlocked) { Print("[News] Paused: ", newsMsg); return; }

   for(int i = 0; i < NUM_SYMBOLS; i++)
      ProcessSymbol(Symbols[i], i);
}

//+------------------------------------------------------------------+
//── Main per-symbol logic ────────────────────────────────────────────
//+------------------------------------------------------------------+
void ProcessSymbol(string sym, int idx)
{
   if(!SymbolSelect(sym, true)) return;

   MqlTick tick;
   if(!SymbolInfoTick(sym, tick)) return;
   double price = tick.bid;

   // ── Active target ─────────────────────────────────────────────
   if(GetState(idx, "active") == 1)
   {
      double tp       = GetState(idx, "tp");
      double dir      = GetState(idx, "dir");
      double created  = GetState(idx, "created");
      double entries  = GetState(idx, "entries");
      double lastEnt  = GetState(idx, "last_entry");
      double firstEnt = GetState(idx, "first_entry");   // SL anchor — never changes

      // Expire old target
      if((double)TimeCurrent() - created > TargetExpiryH * 3600)
      {
         Print("[", sym, "] Target expired");
         ClearState(idx);
         return;
      }

      // TP hit
      bool tpHit = (dir == 1 && price >= tp) || (dir == -1 && price <= tp);
      if(tpHit)
      {
         Print("[", sym, "] TP hit at ", DoubleToString(tp,2));
         SendTelegram("✅ <b>TP HIT — " + sym + "</b>\n"
            + "Target " + DoubleToString(tp,2) + " reached — all entries closed!");
         RecordTP();
         ClearState(idx);
         return;
      }

      // SL hit — anchored to FIRST entry (not last DCA entry)
      double sl  = (dir == 1) ? firstEnt - SlPoints : firstEnt + SlPoints;
      bool slHit = (dir == 1 && price <= sl) || (dir == -1 && price >= sl);
      if(slHit)
      {
         Print("[", sym, "] SL hit at ", DoubleToString(sl,2),
               " (first entry anchor: ", DoubleToString(firstEnt,2), ")");
         SendTelegram("🛑 <b>SL HIT — " + sym + "</b>\n"
            + "Stop " + DoubleToString(sl,2) + " triggered — "
            + IntegerToString((int)entries) + " entr"
            + ((int)entries == 1 ? "y" : "ies") + " closed at loss.");
         RecordSL(idx);
         ClearState(idx);
         return;
      }

      // Trend still valid?
      double emaF = GetEMA(sym, EmaFast, 1);
      double emaS = GetEMA(sym, EmaSlow, 1);
      if(emaF == 0 || emaS == 0) return;
      double curDir = (emaF > emaS) ? 1 : (emaF < emaS) ? -1 : 0;
      if(curDir != dir)
      {
         Print("[", sym, "] Trend reversed — clearing target");
         ClearState(idx);
         return;
      }

      // DCA: price moved EntrySep pts further in direction AND room to TP remains
      bool movedEnough = (dir == 1) ? price >= lastEnt + EntrySep
                                    : price <= lastEnt - EntrySep;
      double roomToTp  = MathAbs(tp - price);
      bool   hasSep    = movedEnough && (roomToTp >= SlPoints) && (entries < MaxEntries);

      if(hasSep)
      {
         double exPrc  = (dir == 1) ? tick.ask : tick.bid;
         double dcaSl  = (dir == 1) ? exPrc - SlPoints : exPrc + SlPoints;
         string action = (dir == 1) ? "BUY" : "SELL";
         double tpPts  = MathAbs(tp - exPrc);
         double dcaLots = CalcLots(sym, RiskPct2);
         double winUsd = dcaLots * tpPts * 100;
         double losUsd = dcaLots * SlPoints * 100;

         Print("[", sym, "] DCA entry ", (int)(entries+1), " @ ", DoubleToString(exPrc,2));
         SetState(idx, "last_entry", price);
         SetState(idx, "entries", entries + 1);

         string emoji = (dir == 1) ? "🟢" : "🔴";
         SendTelegram(emoji + " <b>" + action + " — " + sym
            + "  [DCA Entry " + IntegerToString((int)(entries+1))
            + "/" + IntegerToString(MaxEntries) + "]</b>\n"
            + "Entry: <b>" + DoubleToString(exPrc,2) + "</b>\n"
            + "TP: <b>" + DoubleToString(tp,2) + "</b>   (+" + DoubleToString(tpPts,1) + " pts)\n"
            + "SL: <b>" + DoubleToString(dcaSl,2) + "</b>   (-" + IntegerToString(SlPoints) + " pts)\n"
            + "Lots: <b>" + DoubleToString(dcaLots,2) + "</b> ⭐⭐\n"
            + "Win: ~$" + DoubleToString(winUsd,0) + "  |  Loss: ~$" + DoubleToString(losUsd,0) + "\n"
            + "Signal: Pyramid Entry\nNews: Clear ✅");

         if(AutoExecute)
         {
            bool ok = (dir == 1) ? trade.Buy(dcaLots, sym, exPrc, dcaSl, tp, "signal-bot-dca")
                                 : trade.Sell(dcaLots, sym, exPrc, dcaSl, tp, "signal-bot-dca");
            if(!ok)
               SendTelegram("⚠️ DCA execution failed — " + sym
                  + ": " + IntegerToString(trade.ResultRetcode()));
         }
      }
      return;
   }

   // ── Cooldown check before looking for fresh signal ────────────
   if(InSlCooldown(idx)) return;

   // ── Fresh signal ──────────────────────────────────────────────
   MqlRates bars[];
   if(CopyRates(sym, PERIOD_M15, 0, 200, bars) < 50) return;
   ArraySetAsSeries(bars, true);

   double emaF = GetEMA(sym, EmaFast, 1);
   double emaS = GetEMA(sym, EmaSlow, 1);
   if(emaF == 0 || emaS == 0) return;

   string trend = "flat";
   if(emaF > emaS) trend = "bull";
   if(emaF < emaS) trend = "bear";
   if(trend == "flat") return;

   double rsi = GetRSI(sym, RsiPeriod, 1);
   if(trend == "bull" && rsi > RsiOB) { Print("[",sym,"] RSI overbought ",DoubleToString(rsi,1)); return; }
   if(trend == "bear" && rsi < RsiOS) { Print("[",sym,"] RSI oversold ",DoubleToString(rsi,1));   return; }

   bool   candleOk = false; string patternName = "";
   bool   macdOk   = CheckMACD(sym, trend);
   bool   rsiOk    = (trend == "bull") ? rsi > 50 : rsi < 50;

   if(trend == "bull")
   {
      if(IsBullishEngulfing(bars)) { candleOk = true; patternName = "Bullish Engulfing"; }
      if(IsBullishPinBar(bars))    { candleOk = true; patternName = "Bullish Pin Bar";   }
   }
   else
   {
      if(IsBearishEngulfing(bars)) { candleOk = true; patternName = "Bearish Engulfing"; }
      if(IsBearishPinBar(bars))    { candleOk = true; patternName = "Bearish Pin Bar";   }
   }

   if(!candleOk && !macdOk && !rsiOk)
   {
      Print("[",sym,"] No confirmation — ",trend," | RSI ",DoubleToString(rsi,1));
      return;
   }

   int    confs    = (candleOk?1:0) + (macdOk?1:0) + (rsiOk?1:0);
   double riskPct  = (confs >= 3) ? RiskPct3 : (confs == 2) ? RiskPct2 : RiskPct1;
   double lots     = CalcLots(sym, riskPct);
   string stars    = "";
   for(int s=0; s<confs; s++) stars += "⭐";
   if(!candleOk) patternName = macdOk ? "MACD Cross" : "RSI Momentum";

   double tp = FindTP(sym, price, trend, bars);
   if(tp == 0) { Print("[",sym,"] No S/R level found — skip"); return; }

   double exPrc  = (trend == "bull") ? tick.ask : tick.bid;
   double sl     = (trend == "bull") ? exPrc - SlPoints : exPrc + SlPoints;
   string action = (trend == "bull") ? "BUY" : "SELL";
   double dir    = (trend == "bull") ? 1 : -1;
   double tpPts  = MathAbs(tp - exPrc);
   double rr     = (SlPoints > 0) ? tpPts / SlPoints : 0;
   double winUsd = lots * tpPts * 100;
   double losUsd = lots * SlPoints * 100;

   Print("[",sym,"] ",action," | Entry:",DoubleToString(exPrc,2),
         " TP:",DoubleToString(tp,2)," SL:",DoubleToString(sl,2),
         " Lots:",DoubleToString(lots,2)," Pattern:",patternName);

   // Store — first_entry is the permanent SL anchor for this target
   SetState(idx, "active",      1);
   SetState(idx, "dir",         dir);
   SetState(idx, "tp",          tp);
   SetState(idx, "first_entry", exPrc);
   SetState(idx, "last_entry",  exPrc);
   SetState(idx, "entries",     1);
   SetState(idx, "created",     (double)TimeCurrent());

   string emoji = (action == "BUY") ? "🟢" : "🔴";
   SendTelegram(emoji + " <b>" + action + " — " + sym + "</b>\n"
      + "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
      + "Entry:  <b>" + DoubleToString(exPrc,2) + "</b>\n"
      + "TP:     <b>" + DoubleToString(tp,2) + "</b>  (+" + DoubleToString(tpPts,1) + " pts)\n"
      + "SL:     <b>" + DoubleToString(sl,2) + "</b>  (-" + IntegerToString(SlPoints) + " pts)\n"
      + "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
      + "Lots:   <b>" + DoubleToString(lots,2) + "</b>  " + stars + "\n"
      + "Win:    ~$" + DoubleToString(winUsd,0) + "  |  Loss: ~$" + DoubleToString(losUsd,0) + "\n"
      + "R:R     1:" + DoubleToString(rr,2) + "\n"
      + "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
      + "Signal: " + patternName + "\n"
      + "RSI:    " + DoubleToString(rsi,1) + "\n"
      + "News:   Clear ✅");

   if(!AutoExecute) return;

   bool ok = (action == "BUY") ? trade.Buy(lots, sym, tick.ask, sl, tp, "signal-bot")
                                : trade.Sell(lots, sym, tick.bid, sl, tp, "signal-bot");
   if(ok)
      SendTelegram("✅ <b>AUTO-EXECUTED</b>\n"
         + action + " " + sym + " @ " + DoubleToString(exPrc,2)
         + "\nTicket: #" + IntegerToString((int)trade.ResultOrder()));
   else
      SendTelegram("⚠️ Execution failed: " + IntegerToString(trade.ResultRetcode())
         + " — " + trade.ResultComment());
}

//+------------------------------------------------------------------+
//── News filter (ForexFactory) ───────────────────────────────────────
//+------------------------------------------------------------------+
void CheckNews(bool &blocked, string &msg)
{
   blocked = false; msg = "";
   if(newsCache == "" || (TimeCurrent() - newsFetched) > NEWS_CACHE_SEC)
   {
      char post[], result[];
      string hdrs = "", resHdrs = "";
      int r = WebRequest("GET",
         "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
         hdrs, 10000, post, result, resHdrs);
      if(r > 0) { newsCache = CharArrayToString(result); newsFetched = TimeCurrent(); }
      else { Print("[News] Fetch failed (", GetLastError(), ") — skipping filter"); return; }
   }

   datetime now   = TimeCurrent();
   int      pause = NewsPauseMin * 60;
   int      pos   = 0;

   while(true)
   {
      int imp = StringFind(newsCache, "\"High\"", pos);
      if(imp < 0) break;
      int cStart = StringFind(newsCache, "\"country\":", MathMax(0, imp-200));
      if(cStart < 0 || cStart > imp) { pos = imp+1; continue; }
      string country = ExtractJsonStr(newsCache, cStart);
      if(country != "USD" && country != "XAU") { pos = imp+1; continue; }
      int dStart = StringFind(newsCache, "\"date\":", MathMax(0, imp-200));
      if(dStart < 0 || dStart > imp) { pos = imp+1; continue; }
      string dateStr = ExtractJsonStr(newsCache, dStart);
      datetime evTime = StringToTime(StringSubstr(dateStr, 0, 19));
      if(MathAbs((double)(now - evTime)) <= pause)
      {
         int tStart = StringFind(newsCache, "\"title\":", MathMax(0, imp-300));
         string title = (tStart >= 0 && tStart < imp) ? ExtractJsonStr(newsCache, tStart) : "High-impact event";
         msg = country + ": " + title; blocked = true; return;
      }
      pos = imp + 1;
   }
}

string ExtractJsonStr(string json, int keyPos)
{
   int q1 = StringFind(json, "\"", keyPos + 10);
   if(q1 < 0) return "";
   q1++;
   string val = "";
   for(int i = q1; i < StringLen(json); i++)
   {
      string c = StringSubstr(json, i, 1);
      if(c == "\\") { i++; continue; }
      if(c == "\"") break;
      val += c;
   }
   return val;
}

//+------------------------------------------------------------------+
//── Indicators ───────────────────────────────────────────────────────
//+------------------------------------------------------------------+
double GetEMA(string sym, int period, int shift)
{
   int h = iMA(sym, PERIOD_M15, period, 0, MODE_EMA, PRICE_CLOSE);
   if(h == INVALID_HANDLE) return 0;
   double b[]; ArraySetAsSeries(b, true);
   CopyBuffer(h, 0, shift, 1, b);
   IndicatorRelease(h);
   return b[0];
}

double GetRSI(string sym, int period, int shift)
{
   int h = iRSI(sym, PERIOD_M15, period, PRICE_CLOSE);
   if(h == INVALID_HANDLE) return 50;
   double b[]; ArraySetAsSeries(b, true);
   CopyBuffer(h, 0, shift, 1, b);
   IndicatorRelease(h);
   return b[0];
}

bool CheckMACD(string sym, string trend)
{
   int h = iMACD(sym, PERIOD_M15, 12, 26, 9, PRICE_CLOSE);
   if(h == INVALID_HANDLE) return false;
   double hist[]; ArraySetAsSeries(hist, true);
   if(CopyBuffer(h, 2, 1, 3, hist) < 3) { IndicatorRelease(h); return false; }
   IndicatorRelease(h);
   if(trend == "bull") return (hist[0] > 0 && hist[1] <= 0);
   else                return (hist[0] < 0 && hist[1] >= 0);
}

//+------------------------------------------------------------------+
//── Candlestick patterns ─────────────────────────────────────────────
//+------------------------------------------------------------------+
bool IsBullishEngulfing(MqlRates &b[])
{
   return (b[2].close < b[2].open && b[1].close > b[1].open &&
           b[1].open < b[2].close && b[1].close > b[2].open);
}
bool IsBearishEngulfing(MqlRates &b[])
{
   return (b[2].close > b[2].open && b[1].close < b[1].open &&
           b[1].open > b[2].close && b[1].close < b[2].open);
}
bool IsBullishPinBar(MqlRates &b[])
{
   double rng = b[1].high - b[1].low; if(rng == 0) return false;
   double body = MathAbs(b[1].close - b[1].open);
   double lower = MathMin(b[1].open, b[1].close) - b[1].low;
   return (lower >= rng * 0.6 && body <= rng * 0.3);
}
bool IsBearishPinBar(MqlRates &b[])
{
   double rng = b[1].high - b[1].low; if(rng == 0) return false;
   double body = MathAbs(b[1].close - b[1].open);
   double upper = b[1].high - MathMax(b[1].open, b[1].close);
   return (upper >= rng * 0.6 && body <= rng * 0.3);
}

//+------------------------------------------------------------------+
//── S/R TP finder ────────────────────────────────────────────────────
//+------------------------------------------------------------------+
double FindTP(string sym, double price, string trend, MqlRates &bars[])
{
   double minDist = SlPoints + TpBuffer;
   double best    = 0;

   MqlRates daily[];
   if(CopyRates(sym, PERIOD_D1, 0, 5, daily) >= 2)
   {
      ArraySetAsSeries(daily, true);
      double H=daily[1].high, L=daily[1].low, C=daily[1].close;
      double PP = (H+L+C)/3.0;
      double lvls[] = {PP, 2*PP-L, 2*PP-H, PP+(H-L), PP-(H-L), H+2*(PP-L), L-2*(H-PP)};
      for(int i=0; i<ArraySize(lvls); i++) EvalLevel(lvls[i], price, trend, minDist, best);
   }

   double base = MathRound(price / RoundNumStep) * RoundNumStep;
   for(int i=-8; i<=8; i++) EvalLevel(base + RoundNumStep*i, price, trend, minDist, best);

   for(int i=5; i<45; i++)
   {
      bool isSwingH = true, isSwingL = true;
      for(int j=i-5; j<=i+5; j++)
      {
         if(j==i || j<0 || j>=ArraySize(bars)) continue;
         if(bars[j].high >= bars[i].high) isSwingH = false;
         if(bars[j].low  <= bars[i].low)  isSwingL = false;
      }
      if(isSwingH) EvalLevel(bars[i].high, price, trend, minDist, best);
      if(isSwingL) EvalLevel(bars[i].low,  price, trend, minDist, best);
   }

   return best;
}

void EvalLevel(double lvl, double price, string trend, double minDist, double &best)
{
   if(trend == "bull" && lvl > price + minDist)
   {
      double cand = lvl - TpBuffer;
      if(best == 0 || cand < best) best = cand;
   }
   if(trend == "bear" && lvl < price - minDist)
   {
      double cand = lvl + TpBuffer;
      if(best == 0 || cand > best) best = cand;
   }
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
   char   post[], result[];
   string hdrs = "Content-Type: application/json\r\n", resHdrs = "";
   StringToCharArray(body, post, 0, StringLen(body));
   ArrayResize(post, ArraySize(post)-1);
   int r = WebRequest("POST", url, hdrs, 8000, post, result, resHdrs);
   if(r < 0)
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
