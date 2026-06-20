//+------------------------------------------------------------------+
//| 5StratBot / SignalBotEA.mq5                                      |
//| Attach to ANY chart. Runs in background, checks every 60s.       |
//|                                                                   |
//| STRATEGIES:                                                       |
//|  1.  London Breakout  EURUSD, GBPUSD   07:00-10:00 UTC (skip Tue)|
//|  2.  DAX ORB          GER40            09:00-12:00 UTC           |
//|  3.  NAS100 Open      US100.cash       14:00-16:00 UTC (Tue-Fri) |
//|  4.  NatGas Open      XNGUSD           14:00-16:00 UTC           |
//|  5.  DAX H4 EMA       GER40            08:00-16:00 UTC           |
//|  6.  Oil H4 EMA       USOIL.cash       14:00-21:00 UTC           |
//|  7.  UK100 H4 EMA     UK100.cash       08:00-16:00 UTC           |
//|  8.  EURCHF H4 EMA    EURCHF           08:00-17:00 UTC           |
//|  9.  GBPJPY H4 EMA    GBPJPY           00:00-21:00 UTC           |
//|  10. USDCHF H4 EMA    USDCHF           08:00-17:00 UTC           |
//|  11. NatGas H1 EMA    XNGUSD           14:00-21:00 UTC (fallback)|
//|                                                                   |
//| TRAIL: ORB/LB strategies = 0.2R  |  H4 EMA strategies = 0.3R    |
//| (Optimised via backtest_optimise2.py — 2yr sweep across all strats)|
//+------------------------------------------------------------------+
#property copyright "GC4C Signal Bot"
#property version   "2.10"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

CTrade        trade;
CPositionInfo pos;

//--- Symbol inputs (verify names match YOUR broker's Market Watch)
input string  Sym_EURUSD = "EURUSD";
input string  Sym_GBPUSD = "GBPUSD";
input string  Sym_DAX    = "GER40.cash";
input string  Sym_NAS100 = "US100.cash";
input string  Sym_OIL    = "USOIL.cash";
input string  Sym_NATGAS = "XNGUSD";        // Natural Gas — check your broker
input string  Sym_UK100  = "UK100.cash";    // FTSE 100
input string  Sym_EURCHF = "EURCHF";
input string  Sym_GBPJPY = "GBPJPY";
input string  Sym_USDCHF = "USDCHF";

//--- Risk per trade (% of account balance)
input double  Risk_LB   = 0.4;    // London Breakout
input double  Risk_ORB  = 0.75;   // DAX ORB
input double  Risk_NAS  = 0.75;   // NAS100 Open
input double  Risk_NG   = 0.75;   // NatGas Open
input double  Risk_H4   = 0.75;   // All H4 EMA strategies

// Trail multipliers — optimised via backtest sweep
// ORB/LB peak at 0.2R, H4 EMA peak at 0.3R (small sample, conservative)
input double  Trail_ORB = 0.2;    // London Breakout + all ORB strategies
input double  Trail_H4  = 0.3;    // H4 EMA trend strategies

input int     Magic = 20250619;

//--- Daily fired flags
bool lb_eur_fired, lb_gbp_fired, dax_orb_fired, nas_fired, ng_fired, ng_h1_fired;
bool h4_dax_fired, h4_oil_fired, h4_uk100_fired, h4_eurchf_fired;
bool h4_gbpjpy_fired, h4_usdchf_fired;
datetime last_reset = 0;

//--- Best-price tracker for trailing stops
struct TrailData { ulong ticket; double best; };
TrailData g_trails[100];
int       g_trail_n = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(Magic);
   trade.SetDeviationInPoints(20);
   EventSetTimer(60);
   Print("5StratBot v2.10 started — 11 strategies | Trail ORB=0.2R H4=0.3R");
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason) { EventKillTimer(); }
void OnTick() {}

//+------------------------------------------------------------------+
void OnTimer()
{
   ResetDaily();
   ManageTrails();

   // London Breakout 07:00-10:00 (skip Tuesday — PF 0.96 on Tue)
   CheckLBEur();
   CheckLBGbp();

   // DAX ORB 09:00-12:00
   CheckDAXOrb();

   // US Open 14:00-16:00 (NAS100: Tue-Fri — Fri PF 2.25, skip Mon only)
   CheckNAS100();
   CheckNatGas();
   CheckNatGasH1();   // H1 EMA fallback when ORB doesn't fire (PF 1.75)

   // H4 EMA — fire whenever in session
   CheckH4(Sym_DAX,    Risk_H4, 8,  16, h4_dax_fired,    "H4_DAX");
   CheckH4(Sym_OIL,    Risk_H4, 14, 21, h4_oil_fired,    "H4_OIL");
   CheckH4(Sym_UK100,  Risk_H4, 8,  16, h4_uk100_fired,  "H4_UK100");
   CheckH4(Sym_EURCHF, Risk_H4, 8,  17, h4_eurchf_fired, "H4_EURCHF");
   CheckH4(Sym_GBPJPY, Risk_H4, 0,  21, h4_gbpjpy_fired, "H4_GBPJPY");
   CheckH4(Sym_USDCHF, Risk_H4, 8,  17, h4_usdchf_fired, "H4_USDCHF");
}

//+------------------------------------------------------------------+
void ResetDaily()
{
   MqlDateTime dt;
   TimeToStruct(TimeGMT(), dt);
   datetime today = StringToTime(StringFormat("%d.%02d.%02d",
                    dt.year, dt.mon, dt.day));
   if(today == last_reset) return;

   lb_eur_fired = lb_gbp_fired = dax_orb_fired = nas_fired = ng_fired = ng_h1_fired = false;
   h4_dax_fired = h4_oil_fired = h4_uk100_fired = h4_eurchf_fired = false;
   h4_gbpjpy_fired = h4_usdchf_fired = false;
   last_reset   = today;
   g_trail_n    = 0;
   Print("Daily flags reset — ", dt.day, "/", dt.mon, "/", dt.year);
}

//+------------------------------------------------------------------+
int UTCHour()
{
   MqlDateTime dt;
   TimeToStruct(TimeGMT(), dt);
   return dt.hour;
}

bool HasPosition(string sym)
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
      if(pos.SelectByIndex(i) && pos.Symbol()==sym && pos.Magic()==Magic)
         return true;
   return false;
}

double CalcLots(string sym, double sl_pts, double risk_pct)
{
   double bal  = AccountInfoDouble(ACCOUNT_BALANCE);
   double risk = bal * (risk_pct / 100.0);
   double tv   = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double ts   = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   if(tv<=0||ts<=0||sl_pts<=0) return SymbolInfoDouble(sym,SYMBOL_VOLUME_MIN);
   double lots = risk / ((sl_pts/ts)*tv);
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   lots = MathFloor(lots/step)*step;
   return MathMax(SymbolInfoDouble(sym,SYMBOL_VOLUME_MIN),
          MathMin(SymbolInfoDouble(sym,SYMBOL_VOLUME_MAX), lots));
}

void DoBuy(string sym, double sl, double risk_pct, string tag)
{
   SymbolSelect(sym, true);
   double ask  = SymbolInfoDouble(sym, SYMBOL_ASK);
   double lots = CalcLots(sym, MathAbs(ask-sl), risk_pct);
   if(trade.Buy(lots, sym, ask, sl, 0, tag))
      Print("BUY  ", sym, " @ ", ask, " SL=", sl, " lots=", lots, " [",tag,"]");
   else
      Print("BUY FAIL ", sym, " err=", GetLastError());
}

void DoSell(string sym, double sl, double risk_pct, string tag)
{
   SymbolSelect(sym, true);
   double bid  = SymbolInfoDouble(sym, SYMBOL_BID);
   double lots = CalcLots(sym, MathAbs(bid-sl), risk_pct);
   if(trade.Sell(lots, sym, bid, sl, 0, tag))
      Print("SELL ", sym, " @ ", bid, " SL=", sl, " lots=", lots, " [",tag,"]");
   else
      Print("SELL FAIL ", sym, " err=", GetLastError());
}

//+------------------------------------------------------------------+
//| Trailing stop management                                         |
//+------------------------------------------------------------------+
void SetBest(ulong ticket, double price)
{
   for(int i=0;i<g_trail_n;i++)
      if(g_trails[i].ticket==ticket){g_trails[i].best=price;return;}
   if(g_trail_n<100){g_trails[g_trail_n].ticket=ticket;
                     g_trails[g_trail_n].best=price;g_trail_n++;}
}

double GetBest(ulong ticket, double def)
{
   for(int i=0;i<g_trail_n;i++)
      if(g_trails[i].ticket==ticket) return g_trails[i].best;
   return def;
}

double TrailMult(string comment)
{
   // ORB and LB strategies use 0.2R (tight — breakouts move fast then fade)
   // H4 EMA strategies use 0.3R (slightly more room for trend continuation)
   if(StringFind(comment,"H4_")>=0) return Trail_H4;
   return Trail_ORB;
}

void ManageTrails()
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      if(!pos.SelectByIndex(i)) continue;
      if(pos.Magic()!=Magic)    continue;

      string sym     = pos.Symbol();
      double entry   = pos.PriceOpen();
      double sl_cur  = pos.StopLoss();
      double sl_dist = MathAbs(entry-sl_cur);
      if(sl_dist<=0) continue;
      double trail   = sl_dist * TrailMult(pos.Comment());
      double pt      = SymbolInfoDouble(sym,SYMBOL_POINT);
      ulong  ticket  = pos.Ticket();

      if(pos.PositionType()==POSITION_TYPE_BUY)
      {
         double bid  = SymbolInfoDouble(sym,SYMBOL_BID);
         double best = GetBest(ticket, entry);
         if(bid > best){ best=bid; SetBest(ticket,best); }
         if(best >= entry+sl_dist && sl_cur < entry-pt)
            trade.PositionModify(sym, entry, 0);
         double new_sl = best - trail;
         if(new_sl > sl_cur+pt && new_sl > entry)
            trade.PositionModify(sym, new_sl, 0);
      }
      else
      {
         double ask  = SymbolInfoDouble(sym,SYMBOL_ASK);
         double best = GetBest(ticket, entry);
         if(ask < best){ best=ask; SetBest(ticket,best); }
         if(best <= entry-sl_dist && sl_cur > entry+pt)
            trade.PositionModify(sym, entry, 0);
         double new_sl = best + trail;
         if(new_sl < sl_cur-pt && new_sl < entry)
            trade.PositionModify(sym, new_sl, 0);
      }
   }
}

//+------------------------------------------------------------------+
//| H1 data helpers                                                  |
//+------------------------------------------------------------------+
double H1Hi(string sym, int shift, int n)
{
   MqlRates r[];
   if(CopyRates(sym,PERIOD_H1,shift,n,r)<1) return 0;
   double hi=0; for(int i=0;i<n;i++) hi=MathMax(hi,r[i].high); return hi;
}
double H1Lo(string sym, int shift, int n)
{
   MqlRates r[];
   if(CopyRates(sym,PERIOD_H1,shift,n,r)<1) return DBL_MAX;
   double lo=DBL_MAX; for(int i=0;i<n;i++) lo=MathMin(lo,r[i].low); return lo;
}
bool GetH1(string sym, int shift, double &hi, double &lo)
{
   MqlRates r[];
   if(CopyRates(sym,PERIOD_H1,shift,1,r)<1) return false;
   hi=r[0].high; lo=r[0].low; return true;
}

//+------------------------------------------------------------------+
//| 1. LONDON BREAKOUT                                               |
//+------------------------------------------------------------------+
void CheckLBSingle(string sym, double pip, bool &fired, string tag)
{
   if(fired||HasPosition(sym)) return;
   double a_hi = H1Hi(sym,3,9);
   double a_lo = H1Lo(sym,3,9);
   double rng  = a_hi-a_lo;
   if(rng/pip<10||rng/pip>100) return;
   double buf  = rng*0.15;
   double bid  = SymbolInfoDouble(sym,SYMBOL_BID);
   double ask  = SymbolInfoDouble(sym,SYMBOL_ASK);
   if(ask>a_hi)  { DoBuy (sym,a_lo-buf,Risk_LB,tag+"_B"); fired=true; }
   else if(bid<a_lo){ DoSell(sym,a_hi+buf,Risk_LB,tag+"_S"); fired=true; }
}
void CheckLBEur()
{
   MqlDateTime dt; TimeToStruct(TimeGMT(),dt);
   if(dt.day_of_week==2) return;   // skip Tuesday — PF 0.96 (kills overall PF)
   if(UTCHour()<7||UTCHour()>=10) return;
   CheckLBSingle(Sym_EURUSD,0.0001,lb_eur_fired,"LB_EUR");
}
void CheckLBGbp()
{
   MqlDateTime dt; TimeToStruct(TimeGMT(),dt);
   if(dt.day_of_week==2) return;   // skip Tuesday — PF 1.19 (below threshold)
   if(UTCHour()<7||UTCHour()>=10) return;
   CheckLBSingle(Sym_GBPUSD,0.0001,lb_gbp_fired,"LB_GBP");
}

//+------------------------------------------------------------------+
//| 2. DAX ORB                                                       |
//+------------------------------------------------------------------+
void CheckDAXOrb()
{
   int h=UTCHour();
   if(h<9||h>=12||dax_orb_fired||HasPosition(Sym_DAX)) return;
   double hi,lo;
   if(!GetH1(Sym_DAX,h-8,hi,lo)) return;
   double rng=hi-lo;
   if(rng<30||rng>300) return;
   double bid=SymbolInfoDouble(Sym_DAX,SYMBOL_BID);
   double ask=SymbolInfoDouble(Sym_DAX,SYMBOL_ASK);
   if(ask>hi)  { DoBuy (Sym_DAX,lo,Risk_ORB,"DAX_ORB_B"); dax_orb_fired=true; }
   else if(bid<lo){ DoSell(Sym_DAX,hi,Risk_ORB,"DAX_ORB_S"); dax_orb_fired=true; }
}

//+------------------------------------------------------------------+
//| 3. NAS100 OPEN (Tue-Fri — Mon PF 1.49, Fri PF 2.25 confirmed)   |
//+------------------------------------------------------------------+
void CheckNAS100()
{
   MqlDateTime dt; TimeToStruct(TimeGMT(),dt);
   if(dt.day_of_week<2||dt.day_of_week>5) return;  // Tue=2 to Fri=5
   int h=UTCHour();
   if(h<14||h>=16||nas_fired||HasPosition(Sym_NAS100)) return;
   double hi,lo;
   if(!GetH1(Sym_NAS100,h-13,hi,lo)) return;
   double rng=hi-lo;
   if(rng<50||rng>1500) return;
   double bid=SymbolInfoDouble(Sym_NAS100,SYMBOL_BID);
   double ask=SymbolInfoDouble(Sym_NAS100,SYMBOL_ASK);
   if(ask>hi)  { DoBuy (Sym_NAS100,lo,Risk_NAS,"NAS_B"); nas_fired=true; }
   else if(bid<lo){ DoSell(Sym_NAS100,hi,Risk_NAS,"NAS_S"); nas_fired=true; }
}

//+------------------------------------------------------------------+
//| 4. NATGAS OPEN (PF 1.98 @0.2R trail, 60.5% win — all days)      |
//+------------------------------------------------------------------+
void CheckNatGas()
{
   int h=UTCHour();
   if(h<14||h>=16||ng_fired||HasPosition(Sym_NATGAS)) return;
   double hi,lo;
   if(!GetH1(Sym_NATGAS,h-13,hi,lo)) return;
   double rng=hi-lo;
   if(rng<0.03||rng>1.0) return;
   double bid=SymbolInfoDouble(Sym_NATGAS,SYMBOL_BID);
   double ask=SymbolInfoDouble(Sym_NATGAS,SYMBOL_ASK);
   if(ask>hi)  { DoBuy (Sym_NATGAS,lo,Risk_NG,"NG_B"); ng_fired=true; }
   else if(bid<lo){ DoSell(Sym_NATGAS,hi,Risk_NG,"NG_S"); ng_fired=true; }
}

//+------------------------------------------------------------------+
//| 5. NATGAS H1 EMA (PF 1.75, 59.5% win — fallback if ORB skipped) |
//| Only fires if the 14:00 ORB didn't trigger today                 |
//+------------------------------------------------------------------+
void CheckNatGasH1()
{
   if(ng_fired||ng_h1_fired||HasPosition(Sym_NATGAS)) return;
   int h=UTCHour();
   if(h<14||h>=21) return;

   int h10=iMA(Sym_NATGAS,PERIOD_H1,10,0,MODE_EMA,PRICE_CLOSE);
   int h20=iMA(Sym_NATGAS,PERIOD_H1,20,0,MODE_EMA,PRICE_CLOSE);
   int ha =iATR(Sym_NATGAS,PERIOD_H1,14);
   int hd =iADX(Sym_NATGAS,PERIOD_H1,14);
   if(h10==INVALID_HANDLE||h20==INVALID_HANDLE||
      ha ==INVALID_HANDLE||hd ==INVALID_HANDLE) return;

   double e10[3],e20[3],atr[2],adx[2];
   bool ok = CopyBuffer(h10,0,0,3,e10)>=3 &&
             CopyBuffer(h20,0,0,3,e20)>=3 &&
             CopyBuffer(ha, 0,0,2,atr)>=2 &&
             CopyBuffer(hd, 0,0,2,adx)>=2;
   IndicatorRelease(h10); IndicatorRelease(h20);
   IndicatorRelease(ha);  IndicatorRelease(hd);
   if(!ok||adx[1]<20) return;

   bool bull = e10[1]>e20[1] && e10[2]<=e20[2];
   bool bear = e10[1]<e20[1] && e10[2]>=e20[2];
   if(!bull&&!bear) return;

   double a=atr[1];
   if(bull){ DoBuy (Sym_NATGAS,SymbolInfoDouble(Sym_NATGAS,SYMBOL_ASK)-1.5*a,Risk_NG,"NG_H1_B"); ng_h1_fired=true; }
   else    { DoSell(Sym_NATGAS,SymbolInfoDouble(Sym_NATGAS,SYMBOL_BID)+1.5*a,Risk_NG,"NG_H1_S"); ng_h1_fired=true; }
}

//+------------------------------------------------------------------+
//| 6-11. H4 EMA (DAX, Oil, UK100, EURCHF, GBPJPY, USDCHF)          |
//+------------------------------------------------------------------+
void CheckH4(string sym, double risk, int s_start, int s_end,
             bool &fired, string tag)
{
   int h=UTCHour();
   bool in_sess = (s_start<=s_end) ? (h>=s_start&&h<s_end)
                                    : (h>=s_start||h<s_end);
   if(!in_sess||fired||HasPosition(sym)) return;

   int h10=iMA(sym,PERIOD_H4,10,0,MODE_EMA,PRICE_CLOSE);
   int h20=iMA(sym,PERIOD_H4,20,0,MODE_EMA,PRICE_CLOSE);
   int ha =iATR(sym,PERIOD_H4,14);
   int hd =iADX(sym,PERIOD_H4,14);
   if(h10==INVALID_HANDLE||h20==INVALID_HANDLE||
      ha ==INVALID_HANDLE||hd ==INVALID_HANDLE) return;

   double e10[3],e20[3],atr[2],adx[2];
   bool ok = CopyBuffer(h10,0,0,3,e10)>=3 &&
             CopyBuffer(h20,0,0,3,e20)>=3 &&
             CopyBuffer(ha, 0,0,2,atr)>=2 &&
             CopyBuffer(hd, 0,0,2,adx)>=2;
   IndicatorRelease(h10); IndicatorRelease(h20);
   IndicatorRelease(ha);  IndicatorRelease(hd);
   if(!ok||adx[1]<25) return;

   bool bull = e10[1]>e20[1] && e10[2]<=e20[2];
   bool bear = e10[1]<e20[1] && e10[2]>=e20[2];
   if(!bull&&!bear) return;

   double a=atr[1];
   if(bull){ DoBuy (sym,SymbolInfoDouble(sym,SYMBOL_ASK)-1.5*a,risk,tag+"_B"); fired=true; }
   else    { DoSell(sym,SymbolInfoDouble(sym,SYMBOL_BID)+1.5*a,risk,tag+"_S"); fired=true; }
}
//+------------------------------------------------------------------+
