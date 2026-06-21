//+------------------------------------------------------------------+
//| SignalBotEA.mq5 — GC4C Algorithmic Trading Bot                  |
//| Attach to ANY chart. Runs in background, checks every 60s.       |
//|                                                                   |
//| ── BREAKOUT / ORB STRATEGIES (Trail 0.2R) ──────────────────── ─|
//|  1.  London Breakout  EURUSD, GBPUSD   07:00-10:00 (skip Tue)   |
//|  2.  DAX ORB          GER40            09:00-12:00               |
//|  3.  NAS100 Open      US100.cash       14:00-16:00 (Tue-Fri)    |
//|  4.  SP500 Open       US500.cash       14:00-16:00 (Tue-Fri)    |
//|  5.  NatGas Open      XNGUSD           14:00-16:00 (all days)   |
//|  6.  NatGas H1 EMA    XNGUSD           14:00-21:00 (fallback)   |
//|                                                                   |
//| ── PDH/PDL BREAKOUT (Trail 0.2R) ───────────────────────────── ─|
//|  7.  PDH DAX          GER40            08:00-17:00               |
//|  8.  PDH UK100        UK100.cash       08:00-17:00               |
//|  9.  PDH NAS100       US100.cash       14:00-21:00 (fallback)   |
//| 10.  PDH SP500        US500.cash       14:00-21:00 (fallback)   |
//| 11.  PDH NatGas       XNGUSD           14:00-21:00 (fallback)   |
//| 12.  PDH GBPJPY       GBPJPY           07:00-17:00               |
//|                                                                   |
//| ── H4 EMA TREND STRATEGIES (Trail 0.3R) ─────────────────────── |
//| 13.  DAX H4 EMA       GER40            08:00-16:00               |
//| 14.  Oil H4 EMA       USOIL.cash       14:00-21:00               |
//| 15.  UK100 H4 EMA     UK100.cash       08:00-16:00               |
//| 16.  EURCHF H4 EMA    EURCHF           08:00-17:00               |
//| 17.  GBPJPY H4 EMA    GBPJPY           00:00-21:00               |
//| 18.  USDCHF H4 EMA    USDCHF           08:00-17:00               |
//|                                                                   |
//| Trail: ORB/LB/PDH = 0.2R (backtest peak) | H4 EMA = 0.3R        |
//+------------------------------------------------------------------+
#property copyright "GC4C Signal Bot"
#property version   "3.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

CTrade        trade;
CPositionInfo pos;

//--- Symbol inputs — verify against YOUR broker's Market Watch
input string  Sym_EURUSD = "EURUSD";
input string  Sym_GBPUSD = "GBPUSD";
input string  Sym_DAX    = "GER40.cash";
input string  Sym_NAS100 = "US100.cash";
input string  Sym_SP500  = "US500.cash";
input string  Sym_OIL    = "USOIL.cash";
input string  Sym_NATGAS = "XNGUSD";
input string  Sym_UK100  = "UK100.cash";
input string  Sym_EURCHF = "EURCHF";
input string  Sym_GBPJPY = "GBPJPY";
input string  Sym_USDCHF = "USDCHF";

//--- Risk per trade (% of account balance)
input double  Risk_LB     = 0.4;    // London Breakout
input double  Risk_ORB    = 0.75;   // DAX ORB
input double  Risk_NAS    = 0.75;   // NAS100 Open
input double  Risk_SP5    = 0.4;    // SP500 Open  (lower — correlates with NAS100)
input double  Risk_NG     = 0.75;   // NatGas Open / H1 EMA
input double  Risk_PDH_EU = 0.5;    // PDH DAX + UK100 (standalone)
input double  Risk_PDH    = 0.4;    // PDH NAS100/SP500/NatGas/GBPJPY
input double  Risk_H4     = 0.75;   // All H4 EMA strategies

//--- Trail multipliers (backtest_optimise2.py sweep)
input double  Trail_ORB = 0.2;   // ORB / LB / PDH strategies
input double  Trail_H4  = 0.3;   // H4 EMA trend strategies

input int     Magic = 20250619;

//--- Daily fired flags
bool lb_eur_fired, lb_gbp_fired, dax_orb_fired;
bool nas_fired, sp5_fired, ng_fired, ng_h1_fired;
bool pdh_dax_fired, pdh_uk100_fired, pdh_nas_fired;
bool pdh_sp5_fired, pdh_ng_fired, pdh_gbpjpy_fired;
bool h4_dax_fired, h4_oil_fired, h4_uk100_fired;
bool h4_eurchf_fired, h4_gbpjpy_fired, h4_usdchf_fired;
datetime last_reset = 0;

//--- Trailing stop tracker
struct TrailData { ulong ticket; double best; };
TrailData g_trails[200];
int       g_trail_n = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(Magic);
   trade.SetDeviationInPoints(20);
   EventSetTimer(60);
   Print("SignalBotEA v3.00 started — 18 strategies | ORB+PDH+H4EMA");
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason) { EventKillTimer(); }
void OnTick() {}

//+------------------------------------------------------------------+
void OnTimer()
{
   ResetDaily();
   ManageTrails();

   // ── London Breakout 07:00-10:00 (skip Tuesday) ──────────────────
   CheckLBEur();
   CheckLBGbp();

   // ── Session ORBs ─────────────────────────────────────────────────
   CheckDAXOrb();    // 09:00-12:00
   CheckNAS100();    // 14:00-16:00 Tue-Fri
   CheckSP500();     // 14:00-16:00 Tue-Fri
   CheckNatGas();    // 14:00-16:00 all days
   CheckNatGasH1();  // 14:00-21:00 fallback if ORB didn't fire

   // ── PDH/PDL Breakout ─────────────────────────────────────────────
   CheckPDH(Sym_DAX,    Risk_PDH_EU, 8,  17, pdh_dax_fired,    "PDH_DAX");
   CheckPDH(Sym_UK100,  Risk_PDH_EU, 8,  17, pdh_uk100_fired,  "PDH_UK100");
   CheckPDH(Sym_GBPJPY, Risk_PDH,    7,  17, pdh_gbpjpy_fired, "PDH_GBPJPY");
   // NAS100/SP500/NatGas: fire only when their ORB hasn't (HasPosition handles this)
   CheckPDH(Sym_NAS100, Risk_PDH,   14,  21, pdh_nas_fired,    "PDH_NAS");
   CheckPDH(Sym_SP500,  Risk_PDH,   14,  21, pdh_sp5_fired,    "PDH_SP5");
   CheckPDH(Sym_NATGAS, Risk_PDH,   14,  21, pdh_ng_fired,     "PDH_NG");

   // ── H4 EMA trend ─────────────────────────────────────────────────
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

   lb_eur_fired = lb_gbp_fired = dax_orb_fired = false;
   nas_fired    = sp5_fired    = ng_fired       = ng_h1_fired = false;
   pdh_dax_fired = pdh_uk100_fired = pdh_nas_fired = false;
   pdh_sp5_fired = pdh_ng_fired   = pdh_gbpjpy_fired = false;
   h4_dax_fired  = h4_oil_fired   = h4_uk100_fired   = false;
   h4_eurchf_fired = h4_gbpjpy_fired = h4_usdchf_fired = false;
   last_reset    = today;
   g_trail_n     = 0;
   Print("Daily reset — ", dt.day, "/", dt.mon, "/", dt.year);
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
      Print("BUY  ", sym, " @ ", ask, " SL=", sl, " [", tag, "]");
   else
      Print("BUY FAIL ", sym, " err=", GetLastError());
}

void DoSell(string sym, double sl, double risk_pct, string tag)
{
   SymbolSelect(sym, true);
   double bid  = SymbolInfoDouble(sym, SYMBOL_BID);
   double lots = CalcLots(sym, MathAbs(bid-sl), risk_pct);
   if(trade.Sell(lots, sym, bid, sl, 0, tag))
      Print("SELL ", sym, " @ ", bid, " SL=", sl, " [", tag, "]");
   else
      Print("SELL FAIL ", sym, " err=", GetLastError());
}

//+------------------------------------------------------------------+
//| Trail management                                                 |
//+------------------------------------------------------------------+
double TrailMult(string comment)
{
   return (StringFind(comment,"H4_")>=0) ? Trail_H4 : Trail_ORB;
}

void SetBest(ulong t, double p)
{
   for(int i=0;i<g_trail_n;i++)
      if(g_trails[i].ticket==t){g_trails[i].best=p;return;}
   if(g_trail_n<200){g_trails[g_trail_n].ticket=t;
                     g_trails[g_trail_n].best=p;g_trail_n++;}
}
double GetBest(ulong t, double def)
{
   for(int i=0;i<g_trail_n;i++)
      if(g_trails[i].ticket==t) return g_trails[i].best;
   return def;
}

void ManageTrails()
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      if(!pos.SelectByIndex(i)) continue;
      if(pos.Magic()!=Magic)    continue;

      string sym    = pos.Symbol();
      double entry  = pos.PriceOpen();
      double sl_cur = pos.StopLoss();
      double sld    = MathAbs(entry-sl_cur);
      if(sld<=0) continue;
      double trail  = sld * TrailMult(pos.Comment());
      double pt     = SymbolInfoDouble(sym,SYMBOL_POINT);
      ulong  ticket = pos.Ticket();

      if(pos.PositionType()==POSITION_TYPE_BUY)
      {
         double bid  = SymbolInfoDouble(sym,SYMBOL_BID);
         double best = GetBest(ticket,entry);
         if(bid>best){best=bid;SetBest(ticket,best);}
         if(best>=entry+sld && sl_cur<entry-pt) trade.PositionModify(sym,entry,0);
         double ns=best-trail;
         if(ns>sl_cur+pt && ns>entry) trade.PositionModify(sym,ns,0);
      }
      else
      {
         double ask  = SymbolInfoDouble(sym,SYMBOL_ASK);
         double best = GetBest(ticket,entry);
         if(ask<best){best=ask;SetBest(ticket,best);}
         if(best<=entry-sld && sl_cur>entry+pt) trade.PositionModify(sym,entry,0);
         double ns=best+trail;
         if(ns<sl_cur-pt && ns<entry) trade.PositionModify(sym,ns,0);
      }
   }
}

//+------------------------------------------------------------------+
//| H1 range helpers                                                 |
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
//| 1. LONDON BREAKOUT (skip Tuesday — PF 0.96 on Tue)              |
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
   if(ask>a_hi)   { DoBuy (sym,a_lo-buf,Risk_LB,tag+"_B"); fired=true; }
   else if(bid<a_lo){ DoSell(sym,a_hi+buf,Risk_LB,tag+"_S"); fired=true; }
}
void CheckLBEur()
{
   MqlDateTime dt; TimeToStruct(TimeGMT(),dt);
   if(dt.day_of_week==2) return;
   if(UTCHour()<7||UTCHour()>=10) return;
   CheckLBSingle(Sym_EURUSD,0.0001,lb_eur_fired,"LB_EUR");
}
void CheckLBGbp()
{
   MqlDateTime dt; TimeToStruct(TimeGMT(),dt);
   if(dt.day_of_week==2) return;
   if(UTCHour()<7||UTCHour()>=10) return;
   CheckLBSingle(Sym_GBPUSD,0.0001,lb_gbp_fired,"LB_GBP");
}

//+------------------------------------------------------------------+
//| 2. DAX ORB (09:00-12:00)                                        |
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
   if(ask>hi)   { DoBuy (Sym_DAX,lo,Risk_ORB,"DAX_ORB_B"); dax_orb_fired=true; }
   else if(bid<lo){ DoSell(Sym_DAX,hi,Risk_ORB,"DAX_ORB_S"); dax_orb_fired=true; }
}

//+------------------------------------------------------------------+
//| 3. NAS100 OPEN (Tue-Fri, skip Mon — Mon PF 1.49)                |
//+------------------------------------------------------------------+
void CheckNAS100()
{
   MqlDateTime dt; TimeToStruct(TimeGMT(),dt);
   if(dt.day_of_week<2||dt.day_of_week>5) return;
   int h=UTCHour();
   if(h<14||h>=16||nas_fired||HasPosition(Sym_NAS100)) return;
   double hi,lo;
   if(!GetH1(Sym_NAS100,h-13,hi,lo)) return;
   double rng=hi-lo;
   if(rng<50||rng>1500) return;
   double bid=SymbolInfoDouble(Sym_NAS100,SYMBOL_BID);
   double ask=SymbolInfoDouble(Sym_NAS100,SYMBOL_ASK);
   if(ask>hi)   { DoBuy (Sym_NAS100,lo,Risk_NAS,"NAS_B"); nas_fired=true; }
   else if(bid<lo){ DoSell(Sym_NAS100,hi,Risk_NAS,"NAS_S"); nas_fired=true; }
}

//+------------------------------------------------------------------+
//| 4. SP500 OPEN — PF 1.90 OOS, best walk-forward of any strategy  |
//+------------------------------------------------------------------+
void CheckSP500()
{
   MqlDateTime dt; TimeToStruct(TimeGMT(),dt);
   if(dt.day_of_week<2||dt.day_of_week>5) return;
   int h=UTCHour();
   if(h<14||h>=16||sp5_fired||HasPosition(Sym_SP500)) return;
   double hi,lo;
   if(!GetH1(Sym_SP500,h-13,hi,lo)) return;
   double rng=hi-lo;
   if(rng<5||rng>300) return;
   double bid=SymbolInfoDouble(Sym_SP500,SYMBOL_BID);
   double ask=SymbolInfoDouble(Sym_SP500,SYMBOL_ASK);
   if(ask>hi)   { DoBuy (Sym_SP500,lo,Risk_SP5,"SP5_B"); sp5_fired=true; }
   else if(bid<lo){ DoSell(Sym_SP500,hi,Risk_SP5,"SP5_S"); sp5_fired=true; }
}

//+------------------------------------------------------------------+
//| 5. NATGAS OPEN (all days — PF 1.98 @0.2R)                       |
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
   if(ask>hi)   { DoBuy (Sym_NATGAS,lo,Risk_NG,"NG_B"); ng_fired=true; }
   else if(bid<lo){ DoSell(Sym_NATGAS,hi,Risk_NG,"NG_S"); ng_fired=true; }
}

//+------------------------------------------------------------------+
//| 6. NATGAS H1 EMA (PF 1.75 — only fires if ORB didn't)           |
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
   bool ok=CopyBuffer(h10,0,0,3,e10)>=3&&CopyBuffer(h20,0,0,3,e20)>=3&&
           CopyBuffer(ha, 0,0,2,atr)>=2&&CopyBuffer(hd, 0,0,2,adx)>=2;
   IndicatorRelease(h10);IndicatorRelease(h20);
   IndicatorRelease(ha); IndicatorRelease(hd);
   if(!ok||adx[1]<20) return;
   bool bull=e10[1]>e20[1]&&e10[2]<=e20[2];
   bool bear=e10[1]<e20[1]&&e10[2]>=e20[2];
   if(!bull&&!bear) return;
   double a=atr[1];
   if(bull){DoBuy (Sym_NATGAS,SymbolInfoDouble(Sym_NATGAS,SYMBOL_ASK)-1.5*a,Risk_NG,"NG_H1_B");ng_h1_fired=true;}
   else    {DoSell(Sym_NATGAS,SymbolInfoDouble(Sym_NATGAS,SYMBOL_BID)+1.5*a,Risk_NG,"NG_H1_S");ng_h1_fired=true;}
}

//+------------------------------------------------------------------+
//| 7-12. PDH/PDL BREAKOUT (PF 2.39-3.12 validated 2yr)             |
//| Previous day high/low = institutional level. Enter on break,     |
//| SL = 1.5×ATR below entry. Trail_ORB (0.2R).                     |
//+------------------------------------------------------------------+
void CheckPDH(string sym, double risk, int s_start, int s_end,
              bool &fired, string tag)
{
   int h=UTCHour();
   bool in_sess=(h>=s_start&&h<s_end);
   if(!in_sess||fired||HasPosition(sym)) return;

   // Previous day high/low from D1 bar (shift=1)
   double pdh=iHigh(sym,PERIOD_D1,1);
   double pdl=iLow (sym,PERIOD_D1,1);
   if(pdh<=0||pdl<=0||pdh<=pdl) return;

   // ATR for SL sizing
   int ha=iATR(sym,PERIOD_H1,14);
   if(ha==INVALID_HANDLE) return;
   double atr[2];
   bool ok=CopyBuffer(ha,0,0,2,atr)>=2;
   IndicatorRelease(ha);
   if(!ok||atr[1]<=0) return;
   double a=atr[1];

   // Range quality filter — previous day must be meaningful
   double prev_rng=pdh-pdl;
   if(prev_rng<a*0.4||prev_rng>a*4.0) return;

   double bid=SymbolInfoDouble(sym,SYMBOL_BID);
   double ask=SymbolInfoDouble(sym,SYMBOL_ASK);
   double buf=a*0.05;

   if(ask>pdh+buf)  {DoBuy (sym,ask-1.5*a,risk,tag+"_B");fired=true;}
   else if(bid<pdl-buf){DoSell(sym,bid+1.5*a,risk,tag+"_S");fired=true;}
}

//+------------------------------------------------------------------+
//| 13-18. H4 EMA TREND (DAX PF 2.73, Oil/UK100/EURCHF/GBPJPY/USDCHF)|
//+------------------------------------------------------------------+
void CheckH4(string sym, double risk, int s_start, int s_end,
             bool &fired, string tag)
{
   int h=UTCHour();
   bool in_sess=(s_start<=s_end)?(h>=s_start&&h<s_end):(h>=s_start||h<s_end);
   if(!in_sess||fired||HasPosition(sym)) return;

   int h10=iMA(sym,PERIOD_H4,10,0,MODE_EMA,PRICE_CLOSE);
   int h20=iMA(sym,PERIOD_H4,20,0,MODE_EMA,PRICE_CLOSE);
   int ha =iATR(sym,PERIOD_H4,14);
   int hd =iADX(sym,PERIOD_H4,14);
   if(h10==INVALID_HANDLE||h20==INVALID_HANDLE||
      ha ==INVALID_HANDLE||hd ==INVALID_HANDLE) return;
   double e10[3],e20[3],atr[2],adx[2];
   bool ok=CopyBuffer(h10,0,0,3,e10)>=3&&CopyBuffer(h20,0,0,3,e20)>=3&&
           CopyBuffer(ha, 0,0,2,atr)>=2&&CopyBuffer(hd, 0,0,2,adx)>=2;
   IndicatorRelease(h10);IndicatorRelease(h20);
   IndicatorRelease(ha); IndicatorRelease(hd);
   if(!ok||adx[1]<25) return;
   bool bull=e10[1]>e20[1]&&e10[2]<=e20[2];
   bool bear=e10[1]<e20[1]&&e10[2]>=e20[2];
   if(!bull&&!bear) return;
   double a=atr[1];
   if(bull){DoBuy (sym,SymbolInfoDouble(sym,SYMBOL_ASK)-1.5*a,risk,tag+"_B");fired=true;}
   else    {DoSell(sym,SymbolInfoDouble(sym,SYMBOL_BID)+1.5*a,risk,tag+"_S");fired=true;}
}
//+------------------------------------------------------------------+
