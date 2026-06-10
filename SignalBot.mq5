//+------------------------------------------------------------------+
//| SignalBot.mq5 — Full Strategy EA  v3.1                           |
//|   EMA 10/20 trend  |  RSI filter  |  Candle + MACD confirmation  |
//|   S/R ENTRY filter |  Structure SL  |  S/R TP targeting          |
//|   Risk % lot sizing  |  DCA pyramid x3  |  News filter            |
//+------------------------------------------------------------------+
#property copyright "GC4C Signal Bot"
#property version   "3.10"
#property strict

#include <Trade\Trade.mqh>

//── Inputs ──────────────────────────────────────────────────────────
input string TelegramToken   = "8660365489:AAETZxHhTc-OB8ne19LS4o3Jn5z0LvhXyMo";
input string TelegramChatId  = "5515778237";
input int    PollSeconds     = 300;

input double RiskPct1  = 0.25;
input double RiskPct2  = 0.40;
input double RiskPct3  = 0.50;

input int    EntryLevelTol    = 5;
input int    SlBuffer         = 3;
input int    MinSlPoints      = 8;
input int    BreakEvenPts     = 8;   // pts in profit before SL moves to entry
input int    MinLevelTouches  = 2;   // level must be tested this many times to be valid
input int    LevelTouchTol    = 3;   // pts tolerance when counting level touches
input int    CooldownAfterWin  = 5;  // mins cooldown after a winning trade
input int    CooldownAfterLoss = 15; // mins cooldown after a losing trade

input int    SlPoints    = 12;
input int    TpBuffer    = 2;
input int    RoundNumStep = 25;

input int    MaxEntries    = 3;
input int    EntrySep      = 8;
input int    TargetExpiryH = 24;

input int    EmaFast   = 10;
input int    EmaSlow   = 20;
input int    RsiPeriod = 14;
input double RsiOB     = 75.0;
input double RsiOS     = 20.0;

input int    NewsPauseMin      = 30;
input int    CBConsecLosses    = 2;   // consecutive losses before circuit breaker
input int    CBPauseMinutes    = 45;  // minutes to pause after trigger
input bool   AutoExecute  = true;
input bool   UseH4Bias    = true;  // daily bias — only trade in H4 trend direction

input string Symbol1 = "XAUUSD";
input string Symbol2 = "";

//── Symbols ──────────────────────────────────────────────────────────
#define NUM_SYMBOLS 2
string Symbols[NUM_SYMBOLS];

//── Cached indicator handles (created once in OnInit) ────────────────
int g_emaFast[NUM_SYMBOLS];
int g_emaSlow[NUM_SYMBOLS];
int g_rsi[NUM_SYMBOLS];
int g_macd[NUM_SYMBOLS];
int g_h4EmaFast[NUM_SYMBOLS];
int g_h4EmaSlow[NUM_SYMBOLS];

//── State ─────────────────────────────────────────────────────────────
string StateKey(int idx, string field) { return "SB_" + IntegerToString(idx) + "_" + field; }
void   SetState(int idx, string f, double v) { GlobalVariableSet(StateKey(idx,f), v); }
double GetState(int idx, string f)           { return GlobalVariableGet(StateKey(idx,f)); }
void   ClearState(int idx)
{
   GlobalVariableDel(StateKey(idx,"active"));
   GlobalVariableDel(StateKey(idx,"dir"));
   GlobalVariableDel(StateKey(idx,"tp"));
   GlobalVariableDel(StateKey(idx,"last_entry"));
   GlobalVariableDel(StateKey(idx,"entries"));
   GlobalVariableDel(StateKey(idx,"created"));
}

//── Circuit breaker state ─────────────────────────────────────────────
int      g_consecLosses  = 0;
datetime g_pauseUntil    = 0;
datetime g_lastClosedAt  = 0;
bool     g_lastWasWin    = false;

//── News cache ────────────────────────────────────────────────────────
string   newsCache   = "";
datetime newsFetched = 0;
#define  NEWS_CACHE_SEC 10800

//── Trade object ──────────────────────────────────────────────────────
CTrade trade;

//+------------------------------------------------------------------+
int OnInit()
{
   Symbols[0] = Symbol1;
   Symbols[1] = Symbol2;

   trade.SetExpertMagicNumber(20250605);
   trade.SetDeviationInPoints(20);
   trade.SetTypeFilling(ORDER_FILLING_IOC);

   // Create indicator handles once — reused every poll
   for(int i = 0; i < NUM_SYMBOLS; i++)
   {
      g_emaFast[i] = INVALID_HANDLE;
      g_emaSlow[i] = INVALID_HANDLE;
      g_rsi[i]     = INVALID_HANDLE;
      g_macd[i]    = INVALID_HANDLE;
      if(StringLen(Symbols[i]) > 0)
      {
         g_emaFast[i]   = iMA(Symbols[i],  PERIOD_M15, EmaFast,   0, MODE_EMA, PRICE_CLOSE);
         g_emaSlow[i]   = iMA(Symbols[i],  PERIOD_M15, EmaSlow,   0, MODE_EMA, PRICE_CLOSE);
         g_rsi[i]       = iRSI(Symbols[i], PERIOD_M15, RsiPeriod, PRICE_CLOSE);
         g_macd[i]      = iMACD(Symbols[i],PERIOD_M15, 12, 26, 9, PRICE_CLOSE);
         g_h4EmaFast[i] = iMA(Symbols[i],  PERIOD_H4,  EmaFast,   0, MODE_EMA, PRICE_CLOSE);
         g_h4EmaSlow[i] = iMA(Symbols[i],  PERIOD_H4,  EmaSlow,   0, MODE_EMA, PRICE_CLOSE);
         Print("[SignalBot v3.1] Handles for ", Symbols[i],
               " EMA:", g_emaFast[i], "/", g_emaSlow[i],
               " RSI:", g_rsi[i], " MACD:", g_macd[i],
               " H4:", g_h4EmaFast[i], "/", g_h4EmaSlow[i]);
      }
   }

   // Restore circuit breaker state from today's deal history
   g_consecLosses = 0;
   if(HistorySelect(TimeCurrent()-86400, TimeCurrent()))
   {
      for(int d = HistoryDealsTotal()-1; d >= 0; d--)
      {
         ulong tk = HistoryDealGetTicket(d);
         if(HistoryDealGetInteger(tk, DEAL_MAGIC) != 20250605) continue;
         if(HistoryDealGetInteger(tk, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
         double p = HistoryDealGetDouble(tk, DEAL_PROFIT);
         if(p < 0) g_consecLosses++;
         else      break;
      }
   }
   if(g_consecLosses >= CBConsecLosses)
   {
      g_pauseUntil = TimeCurrent() + CBPauseMinutes * 60;
      Print("[CB] Startup: ",g_consecLosses," consecutive losses — pausing until ",TimeToString(g_pauseUntil));
   }
   else Print("[CB] Startup: ",g_consecLosses," consecutive losses — OK");

   EventSetTimer(PollSeconds);
   Print("[SignalBot v3.1] Started");
   SendTelegram("✅ <b>MT5 Signal Bot v3.1 Active</b>\n"
      + "Account: " + AccountInfoString(ACCOUNT_NAME) + "\n"
      + "Balance: $" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + "\n"
      + "Watching: " + Symbol1 + (StringLen(Symbol2)>0 ? ", "+Symbol2 : "") + "\n"
      + "S/R entry filter ✓  Structure SL ✓  DCA pyramid ✓  News filter ✓");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   for(int i = 0; i < NUM_SYMBOLS; i++)
   {
      if(g_emaFast[i] != INVALID_HANDLE) IndicatorRelease(g_emaFast[i]);
      if(g_emaSlow[i] != INVALID_HANDLE) IndicatorRelease(g_emaSlow[i]);
      if(g_rsi[i]     != INVALID_HANDLE) IndicatorRelease(g_rsi[i]);
      if(g_macd[i]       != INVALID_HANDLE) IndicatorRelease(g_macd[i]);
      if(g_h4EmaFast[i]  != INVALID_HANDLE) IndicatorRelease(g_h4EmaFast[i]);
      if(g_h4EmaSlow[i]  != INVALID_HANDLE) IndicatorRelease(g_h4EmaSlow[i]);
   }
}

void ManageBreakeven()
{
   for(int p = PositionsTotal()-1; p >= 0; p--)
   {
      ulong ticket = PositionGetTicket(p);
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != 20250605) continue;
      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double curSL = PositionGetDouble(POSITION_SL);
      double curTP = PositionGetDouble(POSITION_TP);
      long   pType = PositionGetInteger(POSITION_TYPE);
      string sym   = PositionGetString(POSITION_SYMBOL);
      MqlTick tick;
      if(!SymbolInfoTick(sym, tick)) continue;
      if(pType == POSITION_TYPE_SELL)
      {
         if(tick.bid <= entry - BreakEvenPts && curSL > entry)
         {
            if(trade.PositionModify(ticket, entry, curTP))
            {
               Print("[BE] SELL breakeven locked @ ",DoubleToString(entry,2)," #",ticket);
               SendTelegram("🔒 <b>Breakeven Set — "+sym+"</b>\nSL moved to entry "+DoubleToString(entry,2));
            }
         }
      }
      else if(pType == POSITION_TYPE_BUY)
      {
         if(tick.ask >= entry + BreakEvenPts && curSL < entry)
         {
            if(trade.PositionModify(ticket, entry, curTP))
            {
               Print("[BE] BUY breakeven locked @ ",DoubleToString(entry,2)," #",ticket);
               SendTelegram("🔒 <b>Breakeven Set — "+sym+"</b>\nSL moved to entry "+DoubleToString(entry,2));
            }
         }
      }
   }
}

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC)  != 20250605)   return;
   if(HistoryDealGetInteger(trans.deal, DEAL_ENTRY)  != DEAL_ENTRY_OUT) return;
   double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT);
   string sym    = HistoryDealGetString(trans.deal, DEAL_SYMBOL);
   g_lastClosedAt = TimeCurrent();
   g_lastWasWin   = (profit >= 0);
   if(profit < 0)
   {
      g_consecLosses++;
      Print("[CB] Consecutive losses: ", g_consecLosses);
      if(g_consecLosses >= CBConsecLosses && g_pauseUntil <= TimeCurrent())
      {
         g_pauseUntil = TimeCurrent() + CBPauseMinutes * 60;
         Print("[CB] Triggered — pausing until ", TimeToString(g_pauseUntil));
         SendTelegram("⛔ <b>Circuit Breaker — "+sym+"</b>\n"
            +IntegerToString(g_consecLosses)+" consecutive losses.\n"
            +"Pausing "+IntegerToString(CBPauseMinutes)+" mins — resumes "
            +TimeToString(g_pauseUntil, TIME_MINUTES));
      }
   }
   else { g_consecLosses = 0; }
}

void OnTimer()
{
   Print("[v3.1] Timer fired at ", TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS));
   ManageBreakeven();
   if(g_pauseUntil > TimeCurrent())
   {
      Print("[CB] Paused until ", TimeToString(g_pauseUntil, TIME_MINUTES));
      return;
   }
   bool newsBlocked; string newsMsg;
   CheckNews(newsBlocked, newsMsg);
   Print("[v3.1] News done — blocked:", newsBlocked);
   if(newsBlocked) { Print("[News] Paused: ", newsMsg); return; }
   for(int i = 0; i < NUM_SYMBOLS; i++)
      if(StringLen(Symbols[i]) > 0) ProcessSymbol(Symbols[i], i);
}

//── Indicator helpers (use cached handles) ────────────────────────────
double GetEMA(int idx, bool fast, int shift)
{
   int h = fast ? g_emaFast[idx] : g_emaSlow[idx];
   if(h == INVALID_HANDLE) return 0;
   double b[]; ArraySetAsSeries(b, true);
   if(CopyBuffer(h, 0, shift, 1, b) < 1) return 0;
   return b[0];
}

double GetRSI(int idx, int shift)
{
   if(g_rsi[idx] == INVALID_HANDLE) return 50;
   double b[]; ArraySetAsSeries(b, true);
   if(CopyBuffer(g_rsi[idx], 0, shift, 1, b) < 1) return 50;
   return b[0];
}

bool CheckMACD(int idx, string trend)
{
   if(g_macd[idx] == INVALID_HANDLE) return false;
   double hist[]; ArraySetAsSeries(hist, true);
   if(CopyBuffer(g_macd[idx], 2, 1, 3, hist) < 3) return false;
   if(trend == "bull") return (hist[0] > 0 && hist[1] <= 0);
   else                return (hist[0] < 0 && hist[1] >= 0);
}

//── Lot sizing ────────────────────────────────────────────────────────
double CalcLots(int confs, double slDist)
{
   double pct     = (confs >= 3) ? RiskPct3 : (confs == 2) ? RiskPct2 : RiskPct1;
   double riskAmt = AccountInfoDouble(ACCOUNT_BALANCE) * (pct / 100.0);
   if(slDist <= 0) return 0.01;
   double lots = riskAmt / (slDist * 100.0);
   lots = MathRound(lots / 0.01) * 0.01;
   return MathMax(0.01, MathMin(5.0, lots));
}

//── Level strength — count how many times price has tested a level ────
int LevelStrength(double level, string trend, MqlRates &bars[])
{
   int touches = 0;
   int lookback = MathMin(100, ArraySize(bars));
   for(int i = 1; i < lookback; i++)
   {
      if(trend == "bear")
      {
         if(MathAbs(bars[i].high - level) <= LevelTouchTol) touches++;
      }
      else
      {
         if(MathAbs(bars[i].low - level) <= LevelTouchTol) touches++;
      }
   }
   return touches;
}

//── S/R entry level finder ────────────────────────────────────────────
double FindEntryLevel(string sym, double price, MqlRates &bars[])
{
   double best = 0, bestDist = EntryLevelTol + 1;

   MqlRates daily[];
   if(CopyRates(sym, PERIOD_D1, 0, 5, daily) >= 2)
   {
      ArraySetAsSeries(daily, true);
      double H=daily[1].high, L=daily[1].low, C=daily[1].close;
      double PP=(H+L+C)/3.0;
      double lvls[]={PP,2*PP-L,2*PP-H,PP+(H-L),PP-(H-L),H+2*(PP-L),L-2*(H-PP)};
      for(int i=0;i<ArraySize(lvls);i++)
      { double d=MathAbs(price-lvls[i]); if(d<=EntryLevelTol&&d<bestDist){bestDist=d;best=lvls[i];} }
   }

   double base=MathRound(price/RoundNumStep)*RoundNumStep;
   for(int i=-8;i<=8;i++)
   { double lvl=base+RoundNumStep*i; double d=MathAbs(price-lvl); if(d<=EntryLevelTol&&d<bestDist){bestDist=d;best=lvl;} }

   for(int i=5;i<45;i++)
   {
      bool isH=true, isL=true;
      for(int j=i-5;j<=i+5;j++)
      {
         if(j==i||j<0||j>=ArraySize(bars)) continue;
         if(bars[j].high>=bars[i].high) isH=false;
         if(bars[j].low <=bars[i].low)  isL=false;
      }
      if(isH){double d=MathAbs(price-bars[i].high);if(d<=EntryLevelTol&&d<bestDist){bestDist=d;best=bars[i].high;}}
      if(isL){double d=MathAbs(price-bars[i].low); if(d<=EntryLevelTol&&d<bestDist){bestDist=d;best=bars[i].low;}}
   }
   return best;
}

//── Main per-symbol logic ─────────────────────────────────────────────
void ProcessSymbol(string sym, int idx)
{
   if(!SymbolSelect(sym, true)) { Print("[",sym,"] SymbolSelect failed"); return; }
   MqlTick tick;
   if(!SymbolInfoTick(sym, tick)) { Print("[",sym,"] SymbolInfoTick failed"); return; }
   double price = tick.bid;

   // Clear stale state when MT5 has already closed the position
   if(GetState(idx, "active") == 1)
   {
      bool hasPos = false;
      for(int p=0; p<PositionsTotal(); p++)
      {
         PositionGetTicket(p);
         if(PositionGetString(POSITION_SYMBOL)==sym && PositionGetInteger(POSITION_MAGIC)==20250605)
         { hasPos=true; break; }
      }
      if(!hasPos) { Print("[",sym,"] No open position — clearing stale target"); ClearState(idx); }
   }

   // Active target management
   if(GetState(idx, "active") == 1)
   {
      double tp      = GetState(idx,"tp");
      double dir     = GetState(idx,"dir");
      double created = GetState(idx,"created");
      double entries = GetState(idx,"entries");
      double lastEnt = GetState(idx,"last_entry");

      if((double)TimeCurrent()-created > TargetExpiryH*3600)
      { Print("[",sym,"] Target expired"); ClearState(idx); return; }

      bool tpHit=(dir==1&&price>=tp)||(dir==-1&&price<=tp);
      if(tpHit)
      {
         Print("[",sym,"] TP hit at ",DoubleToString(tp,2));
         SendTelegram("✅ <b>TP HIT — "+sym+"</b>\nTarget "+DoubleToString(tp,2)+" reached!");
         ClearState(idx); return;
      }

      double emaF=GetEMA(idx,true,1), emaS=GetEMA(idx,false,1);
      if(emaF==0||emaS==0) return;
      double curDir=(emaF>emaS)?1:(emaF<emaS)?-1:0;
      if(curDir!=dir) { Print("[",sym,"] Trend reversed — holding for exit, no new entries"); return; }

      bool movedEnough=(dir==1)?price>=lastEnt+EntrySep:price<=lastEnt-EntrySep;
      double roomToTp=MathAbs(tp-price);
      if(movedEnough&&roomToTp>=SlPoints&&entries<MaxEntries)
      {
         double sl=(dir==1)?price-SlPoints:price+SlPoints;
         double exPrc=(dir==1)?tick.ask:tick.bid;
         string action=(dir==1)?"BUY":"SELL";
         double dcaLots=CalcLots(2,SlPoints);
         Print("[",sym,"] DCA entry ",(int)(entries+1)," @ ",DoubleToString(exPrc,2));
         SetState(idx,"last_entry",price); SetState(idx,"entries",entries+1);
         if(AutoExecute)
         {
            bool ok=(dir==1)?trade.Buy(dcaLots,sym,exPrc,sl,tp,"signal-bot-dca")
                            :trade.Sell(dcaLots,sym,exPrc,sl,tp,"signal-bot-dca");
            string emoji=(dir==1)?"🟢":"🔴";
            if(ok) SendTelegram(emoji+" <b>"+action+" — "+sym+"  [DCA Entry "
               +IntegerToString((int)(entries+1))+"/"+IntegerToString(MaxEntries)+"]</b>\n"
               +"Entry: <b>"+DoubleToString(exPrc,2)+"</b>\n"
               +"TP: <b>"+DoubleToString(tp,2)+"</b>  SL: <b>"+DoubleToString(sl,2)+"</b>\n"
               +"Lots: <b>"+DoubleToString(dcaLots,2)+"</b>  Ticket: #"+IntegerToString((int)trade.ResultOrder()));
            else SendTelegram("⚠️ DCA failed — "+sym+": "+IntegerToString(trade.ResultRetcode()));
         }
      }
      return;
   }

   // Fresh signal
   MqlRates bars[];
   if(CopyRates(sym,PERIOD_M15,0,200,bars)<50) { Print("[",sym,"] Not enough bars"); return; }
   ArraySetAsSeries(bars,true);

   double emaF=GetEMA(idx,true,1), emaS=GetEMA(idx,false,1);
   if(emaF==0||emaS==0) { Print("[",sym,"] EMA unavailable"); return; }

   string trend="flat";
   if(emaF>emaS) trend="bull";
   if(emaF<emaS) trend="bear";
   if(trend=="flat") { Print("[",sym,"] Trend flat — skip"); return; }

   // H4 daily bias — hard block on counter-trend signals
   if(UseH4Bias && g_h4EmaFast[idx]!=INVALID_HANDLE && g_h4EmaSlow[idx]!=INVALID_HANDLE)
   {
      double h4F=0,h4S=0;
      double bF[],bS[]; ArraySetAsSeries(bF,true); ArraySetAsSeries(bS,true);
      if(CopyBuffer(g_h4EmaFast[idx],0,1,1,bF)>=1) h4F=bF[0];
      if(CopyBuffer(g_h4EmaSlow[idx],0,1,1,bS)>=1) h4S=bS[0];
      if(h4F>0 && h4S>0)
      {
         string h4Trend=(h4F>h4S)?"bull":"bear";
         if(h4Trend!=trend)
         { Print("[",sym,"] H4 bias ",h4Trend," — skipping ",trend," signal"); return; }
      }
   }

   double rsi=GetRSI(idx,1);
   if(trend=="bull"&&rsi>RsiOB) { Print("[",sym,"] RSI overbought ",DoubleToString(rsi,1)); return; }
   if(trend=="bear"&&rsi<RsiOS) { Print("[",sym,"] RSI oversold ",DoubleToString(rsi,1)); return; }

   bool candleOk=false; string patternName="";
   bool macdOk=CheckMACD(idx,trend);
   bool rsiOk=(trend=="bull")?rsi>50:rsi<50;
   if(trend=="bull"){if(IsBullishEngulfing(bars)){candleOk=true;patternName="Bullish Engulfing";}if(IsBullishPinBar(bars)){candleOk=true;patternName="Bullish Pin Bar";}}
   else             {if(IsBearishEngulfing(bars)){candleOk=true;patternName="Bearish Engulfing";}if(IsBearishPinBar(bars)){candleOk=true;patternName="Bearish Pin Bar";}}

   if(!candleOk&&!macdOk&&!rsiOk) { Print("[",sym,"] No confirmation — ",trend," | RSI ",DoubleToString(rsi,1)); return; }

   int    confs=(candleOk?1:0)+(macdOk?1:0)+(rsiOk?1:0);
   string stars=""; for(int s=0;s<confs;s++) stars+="⭐";
   if(!candleOk) patternName=macdOk?"MACD Cross":"RSI Momentum";

   // Signal cooldown — 5 mins after win, 15 mins after loss
   if(g_lastClosedAt > 0)
   {
      int cooldown = g_lastWasWin ? CooldownAfterWin*60 : CooldownAfterLoss*60;
      int elapsed  = (int)(TimeCurrent() - g_lastClosedAt);
      if(elapsed < cooldown)
      {
         Print("[",sym,"] Cooldown (",g_lastWasWin?"win":"loss",") — ",
               IntegerToString((cooldown-elapsed)/60)," mins remaining");
         return;
      }
   }

   double entryLevel=FindEntryLevel(sym,price,bars);
   if(entryLevel==0) { Print("[",sym,"] Price not near any S/R level — skip | Price ",DoubleToString(price,2)); return; }

   // Level strength — only enter on levels tested 2+ times
   int lvlStrength=LevelStrength(entryLevel,trend,bars);
   if(lvlStrength < MinLevelTouches)
   {
      Print("[",sym,"] Level ",DoubleToString(entryLevel,2)," too weak (",lvlStrength," touch) — skip");
      return;
   }
   Print("[",sym,"] Level ",DoubleToString(entryLevel,2)," strength: ",lvlStrength," touches ✓");

   double exPrc=(trend=="bull")?tick.ask:tick.bid;
   double structSl=(trend=="bull")?entryLevel-SlBuffer:entryLevel+SlBuffer;
   double slDist=MathAbs(exPrc-structSl);
   if(slDist<MinSlPoints) slDist=MinSlPoints;
   double sl=(trend=="bull")?exPrc-slDist:exPrc+slDist;

   double tp=FindTP(sym,price,trend,bars,slDist+TpBuffer);
   if(tp==0) { Print("[",sym,"] No TP level found — skip | Price ",DoubleToString(price,2)); return; }

   string action=(trend=="bull")?"BUY":"SELL";
   double dir=(trend=="bull")?1.0:-1.0;
   double lots=CalcLots(confs,slDist);
   double tpPts=MathAbs(tp-exPrc);
   double rr=(slDist>0)?tpPts/slDist:0;

   Print("[",sym,"] ",action," | Entry:",DoubleToString(exPrc,2),
         " TP:",DoubleToString(tp,2)," SL:",DoubleToString(sl,2),
         " Dist:",DoubleToString(slDist,1)," Level:",DoubleToString(entryLevel,2),
         " Lots:",DoubleToString(lots,2)," ",patternName);

   SetState(idx,"active",1); SetState(idx,"dir",dir); SetState(idx,"tp",tp);
   SetState(idx,"last_entry",price); SetState(idx,"entries",1); SetState(idx,"created",(double)TimeCurrent());

   string emoji=(action=="BUY")?"🟢":"🔴";
   SendTelegram(emoji+" <b>"+action+" — "+sym+"</b>\n"
      +"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
      +"Entry:  <b>"+DoubleToString(exPrc,2)+"</b>\n"
      +"Level:  <b>"+DoubleToString(entryLevel,2)+"</b>\n"
      +"TP:     <b>"+DoubleToString(tp,2)+"</b>  (+"+DoubleToString(tpPts,1)+" pts)\n"
      +"SL:     <b>"+DoubleToString(sl,2)+"</b>  (-"+DoubleToString(slDist,1)+" pts)\n"
      +"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
      +"Lots:   <b>"+DoubleToString(lots,2)+"</b>  "+stars+"\n"
      +"Win:    ~$"+DoubleToString(lots*tpPts*100,0)+"  |  Loss: ~$"+DoubleToString(lots*slDist*100,0)+"\n"
      +"R:R     1:"+DoubleToString(rr,2)+"\n"
      +"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
      +"Signal: "+patternName+"\n"
      +"RSI:    "+DoubleToString(rsi,1)+"\n"
      +"News:   Clear ✅");

   if(!AutoExecute) return;
   bool ok=(action=="BUY")?trade.Buy(lots,sym,tick.ask,sl,tp,"signal-bot")
                          :trade.Sell(lots,sym,tick.bid,sl,tp,"signal-bot");
   if(ok) SendTelegram("✅ <b>AUTO-EXECUTED</b>\n"+action+" "+sym+" @ "+DoubleToString(exPrc,2)+"\nTicket: #"+IntegerToString((int)trade.ResultOrder()));
   else   SendTelegram("⚠️ Execution failed: "+IntegerToString(trade.ResultRetcode())+" — "+trade.ResultComment());
}

//── S/R TP finder ─────────────────────────────────────────────────────
double FindTP(string sym,double price,string trend,MqlRates &bars[],double minDist=0)
{
   if(minDist==0) minDist=SlPoints+TpBuffer;
   double best=0;
   MqlRates daily[];
   if(CopyRates(sym,PERIOD_D1,0,5,daily)>=2)
   {
      ArraySetAsSeries(daily,true);
      double H=daily[1].high,L=daily[1].low,C=daily[1].close,PP=(H+L+C)/3.0;
      double lvls[]={PP,2*PP-L,2*PP-H,PP+(H-L),PP-(H-L),H+2*(PP-L),L-2*(H-PP)};
      for(int i=0;i<ArraySize(lvls);i++) EvalLevel(lvls[i],price,trend,minDist,best);
   }
   double base=MathRound(price/RoundNumStep)*RoundNumStep;
   for(int i=-8;i<=8;i++) EvalLevel(base+RoundNumStep*i,price,trend,minDist,best);
   for(int i=5;i<45;i++)
   {
      bool isH=true,isL=true;
      for(int j=i-5;j<=i+5;j++){if(j==i||j<0||j>=ArraySize(bars))continue;if(bars[j].high>=bars[i].high)isH=false;if(bars[j].low<=bars[i].low)isL=false;}
      if(isH) EvalLevel(bars[i].high,price,trend,minDist,best);
      if(isL) EvalLevel(bars[i].low, price,trend,minDist,best);
   }
   return best;
}

void EvalLevel(double lvl,double price,string trend,double minDist,double &best)
{
   if(trend=="bull"&&lvl>price+minDist){double c=lvl-TpBuffer;if(best==0||c<best)best=c;}
   if(trend=="bear"&&lvl<price-minDist){double c=lvl+TpBuffer;if(best==0||c>best)best=c;}
}

//── News filter ───────────────────────────────────────────────────────
void CheckNews(bool &blocked,string &msg)
{
   blocked=false; msg="";
   if(newsCache==""||( TimeCurrent()-newsFetched)>NEWS_CACHE_SEC)
   {
      char post[],result[]; string hdrs="",resHdrs="";
      int r=WebRequest("GET","https://nfs.faireconomy.media/ff_calendar_thisweek.json",hdrs,10000,post,result,resHdrs);
      if(r>0){newsCache=CharArrayToString(result);newsFetched=TimeCurrent();}
      else{Print("[News] Fetch failed (",GetLastError(),") — skipping");return;}
   }
   datetime now=TimeCurrent(); int pause=NewsPauseMin*60,pos=0;
   while(true)
   {
      int imp=StringFind(newsCache,"\"High\"",pos); if(imp<0)break;
      int cS=StringFind(newsCache,"\"country\":",MathMax(0,imp-200)); if(cS<0||cS>imp){pos=imp+1;continue;}
      string country=ExtractJsonStr(newsCache,cS); if(country!="USD"&&country!="XAU"){pos=imp+1;continue;}
      int dS=StringFind(newsCache,"\"date\":",MathMax(0,imp-200)); if(dS<0||dS>imp){pos=imp+1;continue;}
      datetime evTime=StringToTime(StringSubstr(ExtractJsonStr(newsCache,dS),0,19));
      if(MathAbs((double)(now-evTime))<=pause)
      {
         int tS=StringFind(newsCache,"\"title\":",MathMax(0,imp-300));
         msg=country+": "+((tS>=0&&tS<imp)?ExtractJsonStr(newsCache,tS):"High-impact event");
         blocked=true; return;
      }
      pos=imp+1;
   }
}

string ExtractJsonStr(string json,int keyPos)
{
   int q1=StringFind(json,"\"",keyPos+10); if(q1<0)return ""; q1++;
   string val="";
   for(int i=q1;i<StringLen(json);i++){string c=StringSubstr(json,i,1);if(c=="\\"){i++;continue;}if(c=="\"")break;val+=c;}
   return val;
}

//── Candlestick patterns ──────────────────────────────────────────────
bool IsBullishEngulfing(MqlRates &b[]){return(b[2].close<b[2].open&&b[1].close>b[1].open&&b[1].open<b[2].close&&b[1].close>b[2].open);}
bool IsBearishEngulfing(MqlRates &b[]){return(b[2].close>b[2].open&&b[1].close<b[1].open&&b[1].open>b[2].close&&b[1].close<b[2].open);}
bool IsBullishPinBar(MqlRates &b[]){double r=b[1].high-b[1].low;if(r==0)return false;return(MathMin(b[1].open,b[1].close)-b[1].low>=r*0.6&&MathAbs(b[1].close-b[1].open)<=r*0.3);}
bool IsBearishPinBar(MqlRates &b[]){double r=b[1].high-b[1].low;if(r==0)return false;return(b[1].high-MathMax(b[1].open,b[1].close)>=r*0.6&&MathAbs(b[1].close-b[1].open)<=r*0.3);}

//── Telegram ──────────────────────────────────────────────────────────
void SendTelegram(string text)
{
   string url="https://api.telegram.org/bot"+TelegramToken+"/sendMessage";
   string body="{\"chat_id\":\""+TelegramChatId+"\",\"text\":\""+EscapeJson(text)+"\",\"parse_mode\":\"HTML\"}";
   char post[],result[]; string hdrs="Content-Type: application/json\r\n",resHdrs="";
   StringToCharArray(body,post,0,StringLen(body)); ArrayResize(post,ArraySize(post)-1);
   int r=WebRequest("POST",url,hdrs,8000,post,result,resHdrs);
   if(r<0) Print("[Telegram] Error ",GetLastError()," — check Tools>Options>Expert Advisors>Allow WebRequests");
}

string EscapeJson(string s){StringReplace(s,"\\","\\\\");StringReplace(s,"\"","\\\"");StringReplace(s,"\n","\\n");return s;}
//+------------------------------------------------------------------+
