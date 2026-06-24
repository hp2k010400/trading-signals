//+------------------------------------------------------------------+
//| SignalBotEA.mq5 v4.00 — GC4C Algorithmic Trading Bot            |
//| Attach to ANY chart. Runs every 60 seconds.                      |
//|                                                                   |
//| ── BREAKOUT / ORB (Trail 0.2R) ─────────────────────────────── ─|
//|  1.  London Breakout  EURUSD, GBPUSD   07:00-10:00 (skip Tue)   |
//|  2.  DAX ORB          GER40            09:00-12:00               |
//|  3.  NAS100 Open      US100.cash       14:00-16:00 (Tue-Fri)    |
//|  4.  SP500 Open       US500.cash       14:00-16:00 (Tue-Fri)    |
//|  5.  NatGas Open      XNGUSD           14:00-16:00               |
//|  6.  NatGas H1 EMA    XNGUSD           14:00-21:00 (fallback)   |
//|                                                                   |
//| ── PDH/PDL BREAKOUT (Trail 0.2R) ───────────────────────────── ─|
//|  7.  PDH DAX          GER40            08:00-17:00  +D1 bias     |
//|  8.  PDH NAS100       US100.cash       14:00-21:00               |
//|  9.  PDH SP500        US500.cash       14:00-21:00  +D1 bias     |
//| 10.  PDH NatGas       XNGUSD           14:00-21:00               |
//| 11.  PDH GBPJPY       GBPJPY           07:00-17:00               |
//|                                                                   |
//| ── PREV WEEK HIGH/LOW (Trail 0.2R) ─────────────────────────── ─|
//| 12.  PWH DAX          GER40            08:00-17:00               |
//| 13.  PWH NAS100       US100.cash       14:00-21:00               |
//| 14.  PWH SP500        US500.cash       14:00-21:00               |
//|                                                                   |
//| ── AMD MANIPULATION REVERSAL (Trail 0.2R) ─────────────────── ─ |
//| 15.  AMD EURUSD       EURUSD           07:00-09:00               |
//| 16.  AMD GBPUSD       GBPUSD           07:00-09:00               |
//| 17.  AMD NAS100       US100.cash       14:00-16:00               |
//|                                                                   |
//| ── LIQUIDITY SWEEP REVERSAL (Trail 0.2R) ──────────────────── ─ |
//| 18.  LSR NAS100       US100.cash       14:00-21:00               |
//| 19.  LSR EURUSD       EURUSD           07:00-17:00               |
//|                                                                   |
//| ── FAIR VALUE GAP (Trail 0.2R) ───────────────────────────────── |
//| 20.  FVG EURUSD       EURUSD           07:00-17:00               |
//|                                                                   |
//| ── H4 EMA TREND (Trail 0.3R) ───────────────────────────────── ─|
//| 21.  DAX H4 EMA       GER40            08:00-16:00               |
//| 22.  UK100 H4 EMA     UK100.cash       08:00-16:00               |
//| 23.  EURCHF H4 EMA    EURCHF           08:00-17:00               |
//| 24.  GBPJPY H4 EMA    GBPJPY           00:00-21:00               |
//| 25.  USDCHF H4 EMA    USDCHF           08:00-17:00               |
//| 26.  EURUSD H4 EMA    EURUSD           07:00-17:00               |
//| 27.  GBPUSD H4 EMA    GBPUSD           07:00-17:00               |
//| 28.  EURJPY H4 EMA    EURJPY           07:00-17:00               |
//|                                                                   |
//| ── DONCHIAN 20-DAY BREAKOUT (Trail 0.4R) ─────────────────────── |
//| 29.  Donchian DAX     GER40            08:00-17:00               |
//| 30.  Donchian UK100   UK100.cash       08:00-17:00               |
//| 31.  Donchian NAS100  US100.cash       14:00-21:00               |
//| 32.  Donchian Gold    XAUUSD           08:00-20:00               |
//|                                                                   |
//| ── GOLD LSR (Trail 0.2R) ─────────────────────────────────────── |
//| 33.  Gold LSR         XAUUSD           08:00-20:00               |
//|                                                                   |
//| ── UK100 REMOVED (PWH+LSR+PDH) — bull market SELL losses        |
//|                                                                   |
//| ── SAFETY ─────────────────────────────────────────────────────  |
//|  Daily loss circuit breaker: stops NEW entries at 3.5% day loss  |
//|  (FTMO daily limit = 5%. Buffer = 1.5%)                          |
//+------------------------------------------------------------------+
#property copyright "GC4C Signal Bot"
#property version   "5.10"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

CTrade        trade;
CPositionInfo pos;

//--- Symbol inputs
input string  Sym_EURUSD = "EURUSD";
input string  Sym_GBPUSD = "GBPUSD";
input string  Sym_DAX    = "GER40.cash";
input string  Sym_NAS100 = "US100.cash";
input string  Sym_SP500  = "US500.cash";
input string  Sym_OIL    = "";
input string  Sym_NATGAS = "NATGAS.cash";
input string  Sym_UK100  = "UK100.cash";
input string  Sym_EURCHF = "EURCHF";
input string  Sym_GBPJPY = "GBPJPY";
input string  Sym_USDCHF = "USDCHF";
input string  Sym_EURJPY = "EURJPY";
input string  Sym_GOLD   = "XAUUSD";

//--- Risk per trade (% of account balance)
input double  Risk_LB     = 0.4;
input double  Risk_ORB    = 0.75;
input double  Risk_NAS    = 0.75;
input double  Risk_SP5    = 0.4;
input double  Risk_NG     = 0.40;  // reduced — NatGas has high SL slippage
input double  Risk_PDH_EU = 0.5;
input double  Risk_PDH    = 0.4;
input double  Risk_PWH_EU = 0.4;
input double  Risk_PWH_US = 0.3;
input double  Risk_AMD    = 0.4;
input double  Risk_LSR    = 0.3;
input double  Risk_FVG    = 0.3;
input double  Risk_H4     = 0.75;
input double  Risk_DCH    = 0.5;
input double  Risk_DCH_US = 0.75;
input double  Risk_DCH_GOLD = 0.4;
input double  Risk_LSR_GOLD = 0.3;

//--- Trail multipliers
input double  Trail_ORB = 0.2;
input double  Trail_H4  = 0.3;
input double  Trail_DCH = 0.4;

//--- Safety
input double  Max_Daily_Loss = 3.5;
input int     Magic = 20250619;

//--- Daily fired flags
bool lb_eur_fired, lb_gbp_fired, dax_orb_fired;
bool nas_fired, sp5_fired, ng_fired, ng_h1_fired;
//--- PDH (UK100+NG removed)
bool pdh_dax_fired, pdh_nas_fired;
bool pdh_sp5_fired, pdh_gbpjpy_fired;
//--- PWH (UK100+DAX+SP5 removed)
bool pwh_nas_fired;
//--- AMD
bool amd_eur_fired, amd_gbp_fired, amd_nas_fired;
//--- LSR (UK100 re-added with D1 bias)
bool lsr_uk100_fired, lsr_nas_fired, lsr_eur_fired;
//--- FVG
bool fvg_eur_fired;
//--- H4 EMA (EURCHF removed)
bool h4_dax_fired, h4_oil_fired, h4_uk100_fired;
bool h4_gbpjpy_fired, h4_usdchf_fired;
bool h4_eurusd_fired, h4_gbpusd_fired, h4_eurjpy_fired;
//--- Donchian
bool dch_dax_fired, dch_uk100_fired, dch_nas_fired, dch_gold_fired;
//--- Gold LSR
bool lsr_gold_fired;

datetime last_reset = 0;

double   g_day_open_equity = 0;
datetime g_day_start       = 0;

//--- Trail tracker
struct TrailData { ulong ticket; double best; double orig_sld; };
TrailData g_trails[300];
int       g_trail_n = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(Magic);
   trade.SetDeviationInPoints(20);
   EventSetTimer(60);
   g_day_open_equity = AccountInfoDouble(ACCOUNT_EQUITY);
   Print("11botV3 started — 34 strategies | Circuit breaker: ",
         Max_Daily_Loss, "% daily loss limit");
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason) { EventKillTimer(); }
void OnTick() {}

//+------------------------------------------------------------------+
void OnTimer()
{
   ResetDaily();
   ManageTrails();
   if(DailyLossExceeded()) return;

   CheckLBEur();
   CheckLBGbp();

   CheckDAXOrb();
   CheckNAS100();
   CheckSP500();
   CheckNatGas();
   CheckNatGasH1();

   // PDH (UK100/NG removed; DAX+SP5 use D1 bias filter)
   CheckPDH(Sym_DAX,    Risk_PDH_EU, 8,  17, pdh_dax_fired,    "PDH_DAX",    true);
   CheckPDH(Sym_GBPJPY, Risk_PDH,    7,  17, pdh_gbpjpy_fired, "PDH_GBPJPY");
   CheckPDH(Sym_NAS100, Risk_PDH,   14,  21, pdh_nas_fired,    "PDH_NAS");
   CheckPDH(Sym_SP500,  Risk_PDH,   14,  21, pdh_sp5_fired,    "PDH_SP5",    true);
   // PDH_NG removed — PF 1.00 after spread/slippage

   // PWH (UK100/DAX/SP5 removed)
   CheckPWH(Sym_NAS100, Risk_PWH_US, 14, 21, pwh_nas_fired,    "PWH_NAS");
   // PWH_DAX removed — PF 1.11 | PWH_SP5 removed — PF 0.89

   CheckAMD(Sym_EURUSD, Risk_AMD, "AMD_EUR", amd_eur_fired);
   CheckAMD(Sym_GBPUSD, Risk_AMD, "AMD_GBP", amd_gbp_fired);
   CheckAMDUS(Sym_NAS100, Risk_AMD, "AMD_NAS", amd_nas_fired);

   // LSR (UK100 re-added with D1 bias — PF 2.02)
   CheckLSR(Sym_UK100,  Risk_LSR, 8,  17, lsr_uk100_fired, "LSR_UK100", true);
   CheckLSR(Sym_NAS100, Risk_LSR, 14, 21, lsr_nas_fired,   "LSR_NAS");
   CheckLSR(Sym_EURUSD, Risk_LSR, 7,  17, lsr_eur_fired,   "LSR_EUR");

   CheckFVG(Sym_EURUSD, Risk_FVG, 7, 17, fvg_eur_fired, "FVG_EUR");

   CheckH4(Sym_DAX,    Risk_H4, 8,  16, h4_dax_fired,    "H4_DAX");
   CheckH4(Sym_UK100,  Risk_H4, 8,  16, h4_uk100_fired,  "H4_UK100",  true); // D1 bias
   // H4_EURCHF removed — PF 0.99 after spread/slippage
   CheckH4(Sym_GBPJPY, Risk_H4, 0,  21, h4_gbpjpy_fired, "H4_GBPJPY");
   CheckH4(Sym_USDCHF, Risk_H4, 8,  17, h4_usdchf_fired, "H4_USDCHF");
   CheckH4(Sym_EURUSD, Risk_H4, 7,  17, h4_eurusd_fired, "H4_EURUSD");
   CheckH4(Sym_GBPUSD, Risk_H4, 7,  17, h4_gbpusd_fired, "H4_GBPUSD");
   CheckH4(Sym_EURJPY, Risk_H4, 7,  17, h4_eurjpy_fired, "H4_EURJPY");

   CheckDonchian(Sym_DAX,    Risk_DCH,      8,  17, dch_dax_fired,   "DCH_DAX");
   CheckDonchian(Sym_UK100,  Risk_DCH,      8,  17, dch_uk100_fired, "DCH_UK100");
   CheckDonchian(Sym_NAS100, Risk_DCH_US,  14,  21, dch_nas_fired,   "DCH_NAS");
   CheckDonchian(Sym_GOLD,   Risk_DCH_GOLD, 8,  20, dch_gold_fired,  "DCH_GOLD");

   CheckLSR(Sym_GOLD, Risk_LSR_GOLD, 8, 20, lsr_gold_fired, "LSR_GOLD");
}

//+------------------------------------------------------------------+
bool DailyLossExceeded()
{
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_day_open_equity <= 0) return false;
   double pct = (g_day_open_equity - eq) / g_day_open_equity * 100.0;
   if(pct >= Max_Daily_Loss)
   {
      static datetime last_warn = 0;
      if(TimeGMT() - last_warn > 300)
      {
         Print("⛔ Daily loss circuit breaker: -", DoubleToString(pct,2),
               "% — no new entries until tomorrow");
         last_warn = TimeGMT();
      }
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
void ResetDaily()
{
   MqlDateTime dt; TimeToStruct(TimeGMT(), dt);
   datetime today = StringToTime(StringFormat("%d.%02d.%02d",
                    dt.year, dt.mon, dt.day));
   if(today == last_reset) return;

   lb_eur_fired = lb_gbp_fired = dax_orb_fired = false;
   nas_fired    = sp5_fired    = ng_fired = ng_h1_fired = false;
   pdh_dax_fired = pdh_nas_fired = false;
   pdh_sp5_fired = pdh_gbpjpy_fired = false;
   pwh_nas_fired = false;
   amd_eur_fired = amd_gbp_fired = amd_nas_fired = false;
   lsr_uk100_fired = lsr_nas_fired = lsr_eur_fired = false;
   fvg_eur_fired = false;
   h4_dax_fired = h4_oil_fired = h4_uk100_fired = false;
   h4_gbpjpy_fired = h4_usdchf_fired = false;
   h4_eurusd_fired = h4_gbpusd_fired = h4_eurjpy_fired = false;
   dch_dax_fired = dch_uk100_fired = dch_nas_fired = dch_gold_fired = false;
   lsr_gold_fired = false;

   last_reset        = today;
   g_day_open_equity = AccountInfoDouble(ACCOUNT_EQUITY);
   CleanTrails();
   Print("Daily reset — equity open: £", DoubleToString(g_day_open_equity,0));
}

//+------------------------------------------------------------------+
int UTCHour()
{
   MqlDateTime dt; TimeToStruct(TimeGMT(), dt); return dt.hour;
}

bool HasPosition(string sym)
{
   for(int i=PositionsTotal()-1; i>=0; i--)
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
   double sl_d = MathAbs(ask - sl);
   double min_stop = SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL)
                     * SymbolInfoDouble(sym, SYMBOL_POINT);
   if(sl_d <= min_stop)
      { Print("BUY SKIP ", sym, " — SL too close [", tag, "]"); return; }
   double lots = CalcLots(sym, sl_d, risk_pct);
   if(trade.Buy(lots, sym, ask, sl, 0, tag))
      Print("BUY  ", sym, " @ ", ask, " SL=", sl, " [", tag, "]");
   else Print("BUY FAIL ", sym, " err=", GetLastError());
}

void DoSell(string sym, double sl, double risk_pct, string tag)
{
   SymbolSelect(sym, true);
   double bid  = SymbolInfoDouble(sym, SYMBOL_BID);
   double sl_d = MathAbs(bid - sl);
   double min_stop = SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL)
                     * SymbolInfoDouble(sym, SYMBOL_POINT);
   if(sl_d <= min_stop)
      { Print("SELL SKIP ", sym, " — SL too close [", tag, "]"); return; }
   double lots = CalcLots(sym, sl_d, risk_pct);
   if(trade.Sell(lots, sym, bid, sl, 0, tag))
      Print("SELL ", sym, " @ ", bid, " SL=", sl, " [", tag, "]");
   else Print("SELL FAIL ", sym, " err=", GetLastError());
}

//+------------------------------------------------------------------+
double GetATR(string sym, ENUM_TIMEFRAMES tf, int period)
{
   int h = iATR(sym, tf, period);
   if(h == INVALID_HANDLE) return 0;
   double buf[2];
   bool ok = CopyBuffer(h, 0, 0, 2, buf) >= 2;
   IndicatorRelease(h);
   return ok ? buf[1] : 0;
}

//+------------------------------------------------------------------+
double TrailMult(string comment)
{
   if(StringFind(comment,"H4_") >=0) return Trail_H4;
   if(StringFind(comment,"DCH_")>=0) return Trail_DCH;
   return Trail_ORB;
}

void SetBest(ulong t, double p, double osld=0)
{
   for(int i=0;i<g_trail_n;i++)
      if(g_trails[i].ticket==t)
      {
         g_trails[i].best=p;
         if(osld>0 && g_trails[i].orig_sld<=0) g_trails[i].orig_sld=osld;
         return;
      }
   if(g_trail_n<300)
   {
      g_trails[g_trail_n].ticket=t;
      g_trails[g_trail_n].best=p;
      g_trails[g_trail_n].orig_sld=osld;
      g_trail_n++;
   }
}
double GetBest(ulong t, double def)
{
   for(int i=0;i<g_trail_n;i++)
      if(g_trails[i].ticket==t) return g_trails[i].best;
   return def;
}
double GetOrigSld(ulong t)
{
   for(int i=0;i<g_trail_n;i++)
      if(g_trails[i].ticket==t) return g_trails[i].orig_sld;
   return 0;
}
void CleanTrails()
{
   int w=0;
   for(int i=0;i<g_trail_n;i++)
   {
      bool alive=false;
      for(int j=PositionsTotal()-1;j>=0;j--)
         if(pos.SelectByIndex(j)&&pos.Ticket()==g_trails[i].ticket){alive=true;break;}
      if(alive) g_trails[w++]=g_trails[i];
   }
   g_trail_n=w;
}

void ManageTrails()
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      if(!pos.SelectByIndex(i)||pos.Magic()!=Magic) continue;
      string sym=pos.Symbol(); double entry=pos.PriceOpen();
      double sl_cur=pos.StopLoss(); double sld=MathAbs(entry-sl_cur);
      ulong ticket=pos.Ticket();

      double eff_sld=sld>0 ? sld : GetOrigSld(ticket);
      if(eff_sld<=0)
      {
         ENUM_TIMEFRAMES tf=StringFind(pos.Comment(),"H4_")>=0 ? PERIOD_H4 : PERIOD_H1;
         eff_sld=GetATR(sym,tf,14)*1.5;
      }
      if(eff_sld<=0) continue;

      double trail=eff_sld*TrailMult(pos.Comment());
      double pt=SymbolInfoDouble(sym,SYMBOL_POINT);
      if(pos.PositionType()==POSITION_TYPE_BUY)
      {
         double bid=SymbolInfoDouble(sym,SYMBOL_BID);
         double best=GetBest(ticket,entry);
         if(bid>best){best=bid;SetBest(ticket,best,sld);}
         if(best>=entry+eff_sld&&sl_cur<entry-pt) trade.PositionModify(sym,entry,0);
         double ns=best-trail;
         if(ns>sl_cur+pt&&ns>entry) trade.PositionModify(sym,ns,0);
      }
      else
      {
         double ask=SymbolInfoDouble(sym,SYMBOL_ASK);
         double best=GetBest(ticket,entry);
         if(ask<best){best=ask;SetBest(ticket,best,sld);}
         if(best<=entry-eff_sld&&sl_cur>entry+pt) trade.PositionModify(sym,entry,0);
         double ns=best+trail;
         if(ns<sl_cur-pt&&ns<entry) trade.PositionModify(sym,ns,0);
      }
   }
}

//+------------------------------------------------------------------+
double H1Hi(string sym, int shift, int n)
{
   MqlRates r[]; if(CopyRates(sym,PERIOD_H1,shift,n,r)<1) return 0;
   double hi=0; for(int i=0;i<n;i++) hi=MathMax(hi,r[i].high); return hi;
}
double H1Lo(string sym, int shift, int n)
{
   MqlRates r[]; if(CopyRates(sym,PERIOD_H1,shift,n,r)<1) return DBL_MAX;
   double lo=DBL_MAX; for(int i=0;i<n;i++) lo=MathMin(lo,r[i].low); return lo;
}
bool GetH1(string sym, int shift, double &hi, double &lo)
{
   MqlRates r[]; if(CopyRates(sym,PERIOD_H1,shift,1,r)<1) return false;
   hi=r[0].high; lo=r[0].low; return true;
}

//+------------------------------------------------------------------+
void CheckLBSingle(string sym, double pip, bool &fired, string tag)
{
   if(fired||HasPosition(sym)) return;
   double a_hi=H1Hi(sym,3,9), a_lo=H1Lo(sym,3,9), rng=a_hi-a_lo;
   if(rng/pip<10||rng/pip>100) return;
   double buf=rng*0.15;
   double bid=SymbolInfoDouble(sym,SYMBOL_BID);
   double ask=SymbolInfoDouble(sym,SYMBOL_ASK);
   if(ask>a_hi)    {DoBuy (sym,a_lo-buf,Risk_LB,tag+"_B");fired=true;}
   else if(bid<a_lo){DoSell(sym,a_hi+buf,Risk_LB,tag+"_S");fired=true;}
}
void CheckLBEur()
{
   MqlDateTime dt; TimeToStruct(TimeGMT(),dt);
   if(dt.day_of_week==2||UTCHour()<7||UTCHour()>=10) return;
   CheckLBSingle(Sym_EURUSD,0.0001,lb_eur_fired,"LB_EUR");
}
void CheckLBGbp()
{
   MqlDateTime dt; TimeToStruct(TimeGMT(),dt);
   if(dt.day_of_week==2||UTCHour()<7||UTCHour()>=10) return;
   CheckLBSingle(Sym_GBPUSD,0.0001,lb_gbp_fired,"LB_GBP");
}

//+------------------------------------------------------------------+
void CheckDAXOrb()
{
   int h=UTCHour();
   if(h<9||h>=12||dax_orb_fired||HasPosition(Sym_DAX)) return;
   double hi,lo; if(!GetH1(Sym_DAX,h-8,hi,lo)) return;
   double rng=hi-lo; if(rng<30||rng>300) return;
   double bid=SymbolInfoDouble(Sym_DAX,SYMBOL_BID);
   double ask=SymbolInfoDouble(Sym_DAX,SYMBOL_ASK);
   if(ask>hi)    {DoBuy (Sym_DAX,lo,Risk_ORB,"DAX_ORB_B");dax_orb_fired=true;}
   else if(bid<lo){DoSell(Sym_DAX,hi,Risk_ORB,"DAX_ORB_S");dax_orb_fired=true;}
}

//+------------------------------------------------------------------+
void CheckNAS100()
{
   MqlDateTime dt; TimeToStruct(TimeGMT(),dt);
   if(dt.day_of_week<2||dt.day_of_week>5) return;
   int h=UTCHour();
   if(h<14||h>=16||nas_fired||HasPosition(Sym_NAS100)) return;
   double hi,lo; if(!GetH1(Sym_NAS100,h-13,hi,lo)) return;
   double rng=hi-lo; if(rng<50||rng>1500) return;
   double bid=SymbolInfoDouble(Sym_NAS100,SYMBOL_BID);
   double ask=SymbolInfoDouble(Sym_NAS100,SYMBOL_ASK);
   if(ask>hi)    {DoBuy (Sym_NAS100,lo,Risk_NAS,"NAS_B");nas_fired=true;}
   else if(bid<lo){DoSell(Sym_NAS100,hi,Risk_NAS,"NAS_S");nas_fired=true;}
}
void CheckSP500()
{
   MqlDateTime dt; TimeToStruct(TimeGMT(),dt);
   if(dt.day_of_week<2||dt.day_of_week>5) return;
   int h=UTCHour();
   if(h<14||h>=16||sp5_fired||HasPosition(Sym_SP500)) return;
   double hi,lo; if(!GetH1(Sym_SP500,h-13,hi,lo)) return;
   double rng=hi-lo; if(rng<5||rng>300) return;
   double bid=SymbolInfoDouble(Sym_SP500,SYMBOL_BID);
   double ask=SymbolInfoDouble(Sym_SP500,SYMBOL_ASK);
   if(ask>hi)    {DoBuy (Sym_SP500,lo,Risk_SP5,"SP5_B");sp5_fired=true;}
   else if(bid<lo){DoSell(Sym_SP500,hi,Risk_SP5,"SP5_S");sp5_fired=true;}
}

//+------------------------------------------------------------------+
void CheckNatGas()
{
   int h=UTCHour();
   if(h<14||h>=16||ng_fired||HasPosition(Sym_NATGAS)) return;
   double hi,lo; if(!GetH1(Sym_NATGAS,h-13,hi,lo)) return;
   double rng=hi-lo; if(rng<0.03||rng>1.0) return;
   double bid=SymbolInfoDouble(Sym_NATGAS,SYMBOL_BID);
   double ask=SymbolInfoDouble(Sym_NATGAS,SYMBOL_ASK);
   if(ask>hi)    {DoBuy (Sym_NATGAS,lo,Risk_NG,"NG_B");ng_fired=true;}
   else if(bid<lo){DoSell(Sym_NATGAS,hi,Risk_NG,"NG_S");ng_fired=true;}
}
void CheckNatGasH1()
{
   if(ng_fired||ng_h1_fired||HasPosition(Sym_NATGAS)) return;
   int h=UTCHour(); if(h<14||h>=21) return;
   int h10=iMA(Sym_NATGAS,PERIOD_H1,10,0,MODE_EMA,PRICE_CLOSE);
   int h20=iMA(Sym_NATGAS,PERIOD_H1,20,0,MODE_EMA,PRICE_CLOSE);
   int ha=iATR(Sym_NATGAS,PERIOD_H1,14);
   int hd=iADX(Sym_NATGAS,PERIOD_H1,14);
   if(h10==INVALID_HANDLE||h20==INVALID_HANDLE||ha==INVALID_HANDLE||hd==INVALID_HANDLE) return;
   double e10[3],e20[3],atr[2],adx[2];
   bool ok=CopyBuffer(h10,0,0,3,e10)>=3&&CopyBuffer(h20,0,0,3,e20)>=3&&
           CopyBuffer(ha,0,0,2,atr)>=2&&CopyBuffer(hd,0,0,2,adx)>=2;
   IndicatorRelease(h10);IndicatorRelease(h20);IndicatorRelease(ha);IndicatorRelease(hd);
   if(!ok||adx[1]<20) return;
   bool bull=e10[1]>e20[1]&&e10[2]<=e20[2];
   bool bear=e10[1]<e20[1]&&e10[2]>=e20[2];
   if(!bull&&!bear) return;
   double a=atr[1];
   if(bull){DoBuy (Sym_NATGAS,SymbolInfoDouble(Sym_NATGAS,SYMBOL_ASK)-1.5*a,Risk_NG,"NG_H1_B");ng_h1_fired=true;}
   else    {DoSell(Sym_NATGAS,SymbolInfoDouble(Sym_NATGAS,SYMBOL_BID)+1.5*a,Risk_NG,"NG_H1_S");ng_h1_fired=true;}
}

//+------------------------------------------------------------------+
int GetD1Bias(string sym)
{
   int h=iMA(sym,PERIOD_D1,20,0,MODE_SMA,PRICE_CLOSE);
   if(h==INVALID_HANDLE) return 0;
   double sma[1];
   bool ok=CopyBuffer(h,0,1,1,sma)>=1;
   IndicatorRelease(h);
   if(!ok) return 0;
   double cl=iClose(sym,PERIOD_D1,1);
   if(cl<=0||sma[0]<=0) return 0;
   return cl>sma[0] ? 1 : -1;
}

void CheckPDH(string sym, double risk, int s_start, int s_end,
              bool &fired, string tag, bool use_bias=false)
{
   int h=UTCHour();
   if(h<s_start||h>=s_end||fired||HasPosition(sym)) return;
   double pdh=iHigh(sym,PERIOD_D1,1), pdl=iLow(sym,PERIOD_D1,1);
   if(pdh<=0||pdl<=0||pdh<=pdl) return;
   double a=GetATR(sym,PERIOD_H1,14); if(a<=0) return;
   double rng=pdh-pdl;
   if(rng<a*0.4||rng>a*4.0) return;
   double bid=SymbolInfoDouble(sym,SYMBOL_BID);
   double ask=SymbolInfoDouble(sym,SYMBOL_ASK);
   double buf=a*0.05;
   int bias=use_bias ? GetD1Bias(sym) : 0;
   if(ask>pdh+buf    && (!use_bias||bias==1)) {DoBuy (sym,ask-1.5*a,risk,tag+"_B");fired=true;}
   else if(bid<pdl-buf && (!use_bias||bias==-1)){DoSell(sym,bid+1.5*a,risk,tag+"_S");fired=true;}
}

//+------------------------------------------------------------------+
void CheckPWH(string sym, double risk, int s_start, int s_end,
              bool &fired, string tag)
{
   int h=UTCHour();
   if(h<s_start||h>=s_end||fired||HasPosition(sym)) return;
   double pwh=iHigh(sym,PERIOD_W1,1), pwl=iLow(sym,PERIOD_W1,1);
   if(pwh<=0||pwl<=0||pwh<=pwl) return;
   double a=GetATR(sym,PERIOD_H1,14); if(a<=0) return;
   double rng=pwh-pwl;
   if(rng<0.5*a||rng>8.0*a) return;
   double bid=SymbolInfoDouble(sym,SYMBOL_BID);
   double ask=SymbolInfoDouble(sym,SYMBOL_ASK);
   double buf=a*0.05;
   if(ask>pwh+buf)    {DoBuy (sym,ask-1.5*a,risk,tag+"_B");fired=true;}
   else if(bid<pwl-buf){DoSell(sym,bid+1.5*a,risk,tag+"_S");fired=true;}
}

//+------------------------------------------------------------------+
void CheckAMD(string sym, double risk, string tag, bool &fired)
{
   if(fired||HasPosition(sym)) return;
   int h=UTCHour(); if(h<7||h>=9) return;
   double a_hi=H1Hi(sym,3,9), a_lo=H1Lo(sym,3,9);
   double rng=a_hi-a_lo; if(rng<=0) return;
   double a=GetATR(sym,PERIOD_H1,14); if(a<=0) return;
   MqlRates cur[]; if(CopyRates(sym,PERIOD_H1,1,1,cur)<1) return;
   if(cur[0].high>a_hi && cur[0].close<a_hi && (cur[0].high-a_hi)<rng*0.6)
      {DoSell(sym,cur[0].high+a*0.1,risk,tag+"_S"); fired=true; return;}
   if(cur[0].low<a_lo && cur[0].close>a_lo && (a_lo-cur[0].low)<rng*0.6)
      {DoBuy (sym,cur[0].low-a*0.1, risk,tag+"_B"); fired=true;}
}

//+------------------------------------------------------------------+
void CheckAMDUS(string sym, double risk, string tag, bool &fired)
{
   if(fired||HasPosition(sym)) return;
   int h=UTCHour(); if(h<14||h>=16) return;
   double pm_hi=H1Hi(sym,2,2), pm_lo=H1Lo(sym,2,2);
   double rng=pm_hi-pm_lo; if(rng<=0) return;
   double a=GetATR(sym,PERIOD_H1,14); if(a<=0) return;
   MqlRates cur[]; if(CopyRates(sym,PERIOD_H1,1,1,cur)<1) return;
   if(cur[0].high>pm_hi && cur[0].close<pm_hi && (cur[0].high-pm_hi)<rng*0.6)
      {DoSell(sym,cur[0].high+a*0.1,risk,tag+"_S"); fired=true; return;}
   if(cur[0].low<pm_lo && cur[0].close>pm_lo && (pm_lo-cur[0].low)<rng*0.6)
      {DoBuy (sym,cur[0].low-a*0.1, risk,tag+"_B"); fired=true;}
}

//+------------------------------------------------------------------+
void CheckLSR(string sym, double risk, int s_start, int s_end,
              bool &fired, string tag, bool use_bias=false)
{
   int h=UTCHour();
   if(h<s_start||h>=s_end||fired||HasPosition(sym)) return;
   double pdh=iHigh(sym,PERIOD_D1,1), pdl=iLow(sym,PERIOD_D1,1);
   if(pdh<=0||pdl<=0) return;
   double a=GetATR(sym,PERIOD_H1,14); if(a<=0) return;
   MqlRates cur[]; if(CopyRates(sym,PERIOD_H1,1,1,cur)<1) return;
   int d1=use_bias ? GetD1Bias(sym) : 0;
   if(cur[0].high>pdh && cur[0].close<pdh && (cur[0].high-pdh)<0.6*a && (!use_bias||d1==-1))
      {DoSell(sym,cur[0].high+a*0.1,risk,tag+"_S"); fired=true; return;}
   if(cur[0].low<pdl && cur[0].close>pdl && (pdl-cur[0].low)<0.6*a && (!use_bias||d1==1))
      {DoBuy (sym,cur[0].low-a*0.1, risk,tag+"_B"); fired=true;}
}

//+------------------------------------------------------------------+
void CheckFVG(string sym, double risk, int s_start, int s_end,
              bool &fired, string tag)
{
   int h=UTCHour();
   if(h<s_start||h>=s_end||fired||HasPosition(sym)) return;
   double a=GetATR(sym,PERIOD_H1,14); if(a<=0) return;
   double bid=SymbolInfoDouble(sym,SYMBOL_BID);
   double ask=SymbolInfoDouble(sym,SYMBOL_ASK);
   MqlRates bars[];
   if(CopyRates(sym,PERIOD_H1,2,22,bars)<10) return;
   for(int i=2; i<ArraySize(bars); i++)
   {
      double gap_bull = bars[i].low  - bars[i-2].high;
      double gap_bear = bars[i-2].low - bars[i].high;
      if(gap_bull > a*0.15)
      {
         double lo=bars[i-2].high, hi=bars[i].low;
         if(ask>=lo && ask<=hi) {DoBuy(sym,lo-0.5*a,risk,tag+"_B");fired=true;return;}
      }
      if(gap_bear > a*0.15)
      {
         double lo=bars[i].high, hi=bars[i-2].low;
         if(bid>=lo && bid<=hi) {DoSell(sym,hi+0.5*a,risk,tag+"_S");fired=true;return;}
      }
   }
}

//+------------------------------------------------------------------+
void CheckH4(string sym, double risk, int s_start, int s_end,
             bool &fired, string tag, bool use_bias=false)
{
   int h=UTCHour();
   bool in_sess=(s_start<=s_end)?(h>=s_start&&h<s_end):(h>=s_start||h<s_end);
   if(!in_sess||fired||HasPosition(sym)) return;
   int h10=iMA(sym,PERIOD_H4,10,0,MODE_EMA,PRICE_CLOSE);
   int h20=iMA(sym,PERIOD_H4,20,0,MODE_EMA,PRICE_CLOSE);
   int ha=iATR(sym,PERIOD_H4,14);
   int hd=iADX(sym,PERIOD_H4,14);
   if(h10==INVALID_HANDLE||h20==INVALID_HANDLE||ha==INVALID_HANDLE||hd==INVALID_HANDLE) return;
   double e10[3],e20[3],atr[2],adx[2];
   bool ok=CopyBuffer(h10,0,0,3,e10)>=3&&CopyBuffer(h20,0,0,3,e20)>=3&&
           CopyBuffer(ha,0,0,2,atr)>=2&&CopyBuffer(hd,0,0,2,adx)>=2;
   IndicatorRelease(h10);IndicatorRelease(h20);IndicatorRelease(ha);IndicatorRelease(hd);
   if(!ok||adx[1]<25) return;
   bool bull=e10[1]>e20[1]&&e10[2]<=e20[2];
   bool bear=e10[1]<e20[1]&&e10[2]>=e20[2];
   if(!bull&&!bear) return;
   int d1=use_bias ? GetD1Bias(sym) : 0;
   double a=atr[1];
   if(bull&&(!use_bias||d1==1)) {DoBuy (sym,SymbolInfoDouble(sym,SYMBOL_ASK)-1.5*a,risk,tag+"_B");fired=true;}
   else if(bear&&(!use_bias||d1==-1)){DoSell(sym,SymbolInfoDouble(sym,SYMBOL_BID)+1.5*a,risk,tag+"_S");fired=true;}
}

//+------------------------------------------------------------------+
void CheckDonchian(string sym, double risk, int s_start, int s_end,
                   bool &fired, string tag)
{
   int h=UTCHour();
   bool in_sess=(s_start<=s_end)?(h>=s_start&&h<s_end):(h>=s_start||h<s_end);
   if(!in_sess||fired||HasPosition(sym)) return;
   double hi20[20], lo20[20];
   ArraySetAsSeries(hi20,true); ArraySetAsSeries(lo20,true);
   if(CopyHigh(sym,PERIOD_D1,1,20,hi20)<20) return;
   if(CopyLow (sym,PERIOD_D1,1,20,lo20)<20) return;
   double d20hi=hi20[ArrayMaximum(hi20,0,20)];
   double d20lo=lo20[ArrayMinimum(lo20,0,20)];
   int h_adx=iADX(sym,PERIOD_H4,14);
   if(h_adx==INVALID_HANDLE) return;
   double adx_v[2]; ArraySetAsSeries(adx_v,true);
   bool ok=CopyBuffer(h_adx,0,0,2,adx_v)>=2;
   IndicatorRelease(h_adx);
   if(!ok||adx_v[0]<25) return;
   double a=GetATR(sym,PERIOD_H1,14);
   if(a<=0) return;
   SymbolSelect(sym,true);
   double bid=SymbolInfoDouble(sym,SYMBOL_BID);
   double ask=SymbolInfoDouble(sym,SYMBOL_ASK);
   if(ask>d20hi)   {DoBuy (sym,ask-2.0*a,risk,tag+"_B");fired=true;}
   else if(bid<d20lo){DoSell(sym,bid+2.0*a,risk,tag+"_S");fired=true;}
}
//+------------------------------------------------------------------+
