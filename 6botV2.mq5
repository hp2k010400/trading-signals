//+------------------------------------------------------------------+
//| 6botV2.mq5  —  GC4C Core 6-Strategy Bot                         |
//|                                                                   |
//|  1. LB_EUR   EURUSD  07:00-10:00 UTC  skip Tue  0.40% risk       |
//|  2. LB_GBP   GBPUSD  07:00-10:00 UTC  skip Tue  0.40% risk       |
//|  3. DAX_ORB  GER40   09:00-12:00 UTC  all days  0.75% risk       |
//|  4. NAS_ORB  US100   14:00-16:00 UTC  skip Mon  0.75% risk       |
//|  5. SP5_ORB  US500   14:00-16:00 UTC  skip Mon  0.40% risk       |
//|  6. NG_ORB   NatGas  14:00-16:00 UTC  all days  0.75% risk       |
//|                                                                   |
//|  Trail: 0.1R after 1R breakeven (matches backtest exactly)       |
//|  News: MT5 economic calendar, HIGH impact, ±30 min pause         |
//|  Safety: daily loss CB · instrument cooldown · fired-flag restore |
//|  Attach to ANY chart. Timer fires every 60 seconds.              |
//+------------------------------------------------------------------+
#property copyright "GC4C"
#property version   "2.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

CTrade        trade;
CPositionInfo pos;

//--- Symbols
input string  Sym_EURUSD  = "EURUSD";
input string  Sym_GBPUSD  = "GBPUSD";
input string  Sym_DAX     = "GER40.cash";
input string  Sym_NAS100  = "US100.cash";
input string  Sym_SP500   = "US500.cash";
input string  Sym_NATGAS  = "NATGAS.cash";

//--- Risk (% of equity per trade)
input double  Risk_LB        = 0.40;   // LB_EUR and LB_GBP
input double  Risk_ORB_HIGH  = 0.75;   // NAS_ORB, DAX_ORB, NG_ORB
input double  Risk_ORB_MED   = 0.40;   // SP5_ORB

//--- Trail
input double  Trail_R     = 0.10;   // Fraction of SL distance; activates AFTER 1R breakeven

//--- Timing (all UTC hours)
input int     Server_UTC  = 3;      // Broker server UTC offset — EET winter=2, EEST summer=3
input int     LB_Start    = 7;      // LB window open UTC
input int     LB_End      = 10;     // LB window close UTC
input int     DAX_RefH    = 8;      // DAX ORB reference bar UTC hour
input int     DAX_Start   = 9;      // DAX ORB entry open UTC
input int     DAX_End     = 12;     // DAX ORB entry close UTC
input int     US_RefH     = 13;     // US ORBs reference bar UTC hour
input int     US_Start    = 14;     // US ORBs entry open UTC
input int     US_End      = 16;     // US ORBs entry close UTC

//--- News filter
input bool    UseNews     = true;
input int     NewsPauseMin = 30;    // Pause ±N minutes around HIGH impact events

//--- Safety
input double  MaxDailyLoss = 3.5;   // % daily equity loss → circuit breaker
input int     Magic        = 20250625;

//--- Fired flags (one trade per strategy per day)
bool g_lb_eur, g_lb_gbp, g_dax_orb, g_nas_orb, g_sp5_orb, g_ng_orb;

//--- Instrument cooldown (SL hit today → block rest of day)
bool g_blk_eur, g_blk_gbp, g_blk_dax, g_blk_nas, g_blk_sp5, g_blk_ng;

datetime g_last_reset = 0;
double   g_day_equity = 0;

//--- Trail tracker
struct TTrail { ulong ticket; double best; double orig_sld; };
TTrail g_trails[50];
int    g_trail_n = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetDeviationInPoints(20);
   EventSetTimer(60);
   g_day_equity = AccountInfoDouble(ACCOUNT_EQUITY);
   RestoreFiredFlags();
   Print("6botV2 v2.00 online | Magic=", Magic,
         " | Server_UTC=", Server_UTC,
         " | News=", UseNews);
   return INIT_SUCCEEDED;
}
void OnDeinit(const int r) { EventKillTimer(); }

//+------------------------------------------------------------------+
void OnTimer()
{
   ResetDaily();
   ManageTrails();
   CheckSLHits();
   if (DailyLossExceeded()) return;

   int h   = UtcHour();
   int dow = UtcDow();   // 0=Sun 1=Mon 2=Tue 3=Wed 4=Thu 5=Fri 6=Sat

   // London Breakout — skip Tuesday
   if (dow != 2 && h >= LB_Start && h < LB_End) {
      if (!g_lb_eur) RunLB(Sym_EURUSD, "LB_EUR", Risk_LB,     0.0001, g_lb_eur);
      if (!g_lb_gbp) RunLB(Sym_GBPUSD, "LB_GBP", Risk_LB,     0.0001, g_lb_gbp);
   }

   // DAX ORB — all days
   if (h >= DAX_Start && h < DAX_End)
      if (!g_dax_orb)
         RunORB(Sym_DAX, "DAX_ORB", Risk_ORB_HIGH, DAX_RefH, 30.0, 300.0, g_dax_orb);

   // US ORBs — skip Monday
   if (dow != 1 && h >= US_Start && h < US_End) {
      if (!g_nas_orb) RunORB(Sym_NAS100, "NAS_ORB", Risk_ORB_HIGH, US_RefH, 50.0,  1500.0, g_nas_orb);
      if (!g_sp5_orb) RunORB(Sym_SP500,  "SP5_ORB", Risk_ORB_MED,  US_RefH,  5.0,   300.0, g_sp5_orb);
      if (!g_ng_orb)  RunORB(Sym_NATGAS, "NG_ORB",  Risk_ORB_HIGH, US_RefH,  0.03,    1.0, g_ng_orb);
   }
}

//+------------------------------------------------------------------+
// Time helpers
int UtcHour()
{
   return (int)(TimeGMT() % 86400) / 3600;
}
int UtcDow()
{
   MqlDateTime t; TimeToStruct(TimeGMT(), t); return t.day_of_week;
}
datetime ToServer(datetime utc_dt)
{
   return utc_dt + Server_UTC * 3600;
}

//+------------------------------------------------------------------+
void ResetDaily()
{
   datetime today = (datetime)(TimeGMT() / 86400 * 86400);
   if (g_last_reset == today) return;
   g_lb_eur  = g_lb_gbp  = false;
   g_dax_orb = g_nas_orb = g_sp5_orb = g_ng_orb = false;
   g_blk_eur = g_blk_gbp = g_blk_dax = false;
   g_blk_nas = g_blk_sp5 = g_blk_ng  = false;
   g_last_reset = today;
   g_day_equity = AccountInfoDouble(ACCOUNT_EQUITY);
   Print("6botV2 daily reset");
}

bool DailyLossExceeded()
{
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if ((g_day_equity - eq) / g_day_equity * 100.0 >= MaxDailyLoss) {
      Print("Circuit breaker: daily loss >= ", MaxDailyLoss, "%");
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
// News filter — MT5 economic calendar
bool NewsNear(string sym)
{
   if (!UseNews) return false;
   datetime now = TimeGMT();
   MqlCalendarValue vals[];
   int n = CalendarValueHistory(vals,
               now - NewsPauseMin * 60,
               now + NewsPauseMin * 60);
   if (n <= 0) return false;
   for (int i = 0; i < n; i++) {
      MqlCalendarEvent ev;
      if (!CalendarEventById(vals[i].event_id, ev)) continue;
      if (ev.importance != CALENDAR_IMPORTANCE_HIGH) continue;
      MqlCalendarCountry co;
      if (!CalendarCountryById(ev.country_id, co)) continue;
      string c = co.currency;
      if (c == "USD") return true;   // USD news blocks everything
      if (c == "EUR" && (StringFind(sym,"EUR")>=0||StringFind(sym,"GER")>=0)) return true;
      if (c == "GBP" &&  StringFind(sym,"GBP")>=0) return true;
   }
   return false;
}

//+------------------------------------------------------------------+
// Instrument cooldown helpers
bool & BlkFlag(string sym)
{
   if (sym==Sym_EURUSD) return g_blk_eur;
   if (sym==Sym_GBPUSD) return g_blk_gbp;
   if (sym==Sym_DAX)    return g_blk_dax;
   if (sym==Sym_NAS100) return g_blk_nas;
   if (sym==Sym_SP500)  return g_blk_sp5;
   return g_blk_ng;
}

void CheckSLHits()
{
   datetime day = (datetime)(TimeGMT() / 86400 * 86400);
   HistorySelect(day, TimeGMT());
   for (int i = HistoryDealsTotal()-1; i >= 0; i--) {
      ulong tk = HistoryDealGetTicket(i);
      if (HistoryDealGetInteger(tk, DEAL_MAGIC)  != Magic)           continue;
      if (HistoryDealGetInteger(tk, DEAL_ENTRY)  != DEAL_ENTRY_OUT)  continue;
      if (HistoryDealGetDouble (tk, DEAL_PROFIT) >= -5.0)            continue;
      BlkFlag(HistoryDealGetString(tk, DEAL_SYMBOL)) = true;
   }
}

//+------------------------------------------------------------------+
// Restore fired flags on EA reload (prevents duplicate entries)
void RestoreFiredFlags()
{
   datetime day = (datetime)(TimeGMT() / 86400 * 86400);
   HistorySelect(day, TimeGMT());
   for (int i = HistoryDealsTotal()-1; i >= 0; i--) {
      ulong tk = HistoryDealGetTicket(i);
      if (HistoryDealGetInteger(tk, DEAL_MAGIC) != Magic)          continue;
      if (HistoryDealGetInteger(tk, DEAL_ENTRY) != DEAL_ENTRY_IN)  continue;
      SetFiredFlag(HistoryDealGetString(tk, DEAL_COMMENT));
   }
   for (int i = PositionsTotal()-1; i >= 0; i--)
      if (pos.SelectByIndex(i) && pos.Magic() == Magic)
         SetFiredFlag(pos.Comment());
}
void SetFiredFlag(string t)
{
   if (t=="LB_EUR")  g_lb_eur  = true;
   if (t=="LB_GBP")  g_lb_gbp  = true;
   if (t=="DAX_ORB") g_dax_orb = true;
   if (t=="NAS_ORB") g_nas_orb = true;
   if (t=="SP5_ORB") g_sp5_orb = true;
   if (t=="NG_ORB")  g_ng_orb  = true;
}

//+------------------------------------------------------------------+
// Lot sizing
double CalcLots(string sym, double entry, double sl, double risk_pct)
{
   double sl_d  = MathAbs(entry - sl);
   if (sl_d <= 0) return 0;
   double tv    = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double ts    = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   if (tv <= 0 || ts <= 0) return 0;
   double risk  = AccountInfoDouble(ACCOUNT_EQUITY) * risk_pct / 100.0;
   double lots  = risk / (sl_d / ts * tv);
   double step  = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   lots = MathFloor(lots / step) * step;
   return MathMax(SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN),
          MathMin(SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX), lots));
}

bool HasPos(string sym)
{
   for (int i = PositionsTotal()-1; i >= 0; i--)
      if (pos.SelectByIndex(i) && pos.Symbol()==sym && pos.Magic()==Magic)
         return true;
   return false;
}

//--- Place the trade (all validation in one place)
bool Enter(string sym, int dir, double entry, double sl,
           double risk_pct, string tag, bool &fired)
{
   if (HasPos(sym))   { Print(tag," SKIP HasPos");        return false; }
   if (BlkFlag(sym))  { Print(tag," SKIP InstCooldown");  return false; }
   if (NewsNear(sym)) { Print(tag," SKIP NewsNear");       return false; }

   double lots = CalcLots(sym, entry, sl, risk_pct);
   if (lots <= 0) { Print(tag," SKIP lots=0"); return false; }

   double min_stop = SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL)
                     * SymbolInfoDouble(sym, SYMBOL_POINT);
   if (MathAbs(entry-sl) < min_stop) { Print(tag," SKIP SL<MinStop"); return false; }

   bool ok = (dir==1) ? trade.Buy (lots,sym,0,sl,0,tag)
                       : trade.Sell(lots,sym,0,sl,0,tag);
   if (ok) {
      SetTrailBest(trade.ResultOrder(), entry, MathAbs(entry-sl));
      fired = true;
      Print(tag," ",(dir==1?"BUY":"SELL")," ",DoubleToString(lots,2),
            " entry=",entry," sl=",sl);
   }
   return ok;
}

//+------------------------------------------------------------------+
// Trail management (activates after 1R BE, trails at Trail_R × SL)
void SetTrailBest(ulong tk, double best, double orig_sld)
{
   for (int i=0; i<g_trail_n; i++) {
      if (g_trails[i].ticket==tk) {
         g_trails[i].best = best;
         if (orig_sld>0 && g_trails[i].orig_sld<=0) g_trails[i].orig_sld=orig_sld;
         return;
      }
   }
   if (g_trail_n < 50) {
      g_trails[g_trail_n].ticket   = tk;
      g_trails[g_trail_n].best     = best;
      g_trails[g_trail_n].orig_sld = orig_sld;
      g_trail_n++;
   }
}
double GetTrailBest(ulong tk, double def)
{
   for (int i=0; i<g_trail_n; i++)
      if (g_trails[i].ticket==tk) return g_trails[i].best;
   return def;
}
double GetTrailOrigSld(ulong tk)
{
   for (int i=0; i<g_trail_n; i++)
      if (g_trails[i].ticket==tk) return g_trails[i].orig_sld;
   return 0;
}
void CleanTrails()
{
   int w=0;
   for (int i=0; i<g_trail_n; i++) {
      bool alive=false;
      for (int j=PositionsTotal()-1; j>=0; j--)
         if (pos.SelectByIndex(j) && pos.Ticket()==g_trails[i].ticket) { alive=true; break; }
      if (alive) g_trails[w++]=g_trails[i];
   }
   g_trail_n=w;
}
void ManageTrails()
{
   CleanTrails();
   for (int i=PositionsTotal()-1; i>=0; i--) {
      if (!pos.SelectByIndex(i) || pos.Magic()!=Magic) continue;
      string sym    = pos.Symbol();
      double entry  = pos.PriceOpen();
      double sl_cur = pos.StopLoss();
      ulong  tk     = pos.Ticket();
      double pt     = SymbolInfoDouble(sym, SYMBOL_POINT);
      double sld    = MathAbs(entry - sl_cur);
      double eff    = sld > 0 ? sld : GetTrailOrigSld(tk);
      if (eff <= 0) continue;
      double trail  = eff * Trail_R;

      if (pos.PositionType() == POSITION_TYPE_BUY) {
         double bid  = SymbolInfoDouble(sym, SYMBOL_BID);
         double best = GetTrailBest(tk, entry);
         if (bid > best) { best=bid; SetTrailBest(tk,best,sld); }
         // Move SL to entry (BE) once 1R in profit
         if (best >= entry+eff && sl_cur < entry-pt)
            trade.PositionModify(sym, entry, 0);
         // Trail only after BE is active
         if (sl_cur >= entry-pt) {
            double ns = best - trail;
            if (ns > sl_cur+pt) trade.PositionModify(sym, ns, 0);
         }
      } else {
         double ask  = SymbolInfoDouble(sym, SYMBOL_ASK);
         double best = GetTrailBest(tk, entry);
         if (ask < best) { best=ask; SetTrailBest(tk,best,sld); }
         if (best <= entry-eff && sl_cur > entry+pt)
            trade.PositionModify(sym, entry, 0);
         if (sl_cur <= entry+pt) {
            double ns = best + trail;
            if (ns < sl_cur-pt) trade.PositionModify(sym, ns, 0);
         }
      }
   }
}

//+------------------------------------------------------------------+
// London Breakout
void RunLB(string sym, string tag, double risk_pct, double pip, bool &fired)
{
   // Asian range: yesterday 22:00 UTC → today 07:00 UTC (9 H1 bars)
   datetime today_utc = (datetime)(TimeGMT() / 86400 * 86400);
   datetime rng_s     = today_utc - 2 * 3600;           // 22:00 UTC yesterday
   datetime rng_e     = today_utc + LB_Start * 3600;    // 07:00 UTC today

   MqlRates bars[];
   int n = CopyRates(sym, PERIOD_H1, ToServer(rng_s), ToServer(rng_e), bars);
   if (n < 3) { Print(tag," range bars=",n," (need 3+)"); return; }

   double a_hi=-DBL_MAX, a_lo=DBL_MAX;
   for (int i=0; i<n; i++) {
      a_hi = MathMax(a_hi, bars[i].high);
      a_lo = MathMin(a_lo, bars[i].low);
   }
   double rng = a_hi - a_lo;
   if (rng/pip < 10 || rng/pip > 100) return;  // range too narrow or too wide
   double buf = rng * 0.15;

   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);

   if      (ask > a_hi+buf) Enter(sym,  1, ask, a_lo-buf, risk_pct, tag, fired);
   else if (bid < a_lo-buf) Enter(sym, -1, bid, a_hi+buf, risk_pct, tag, fired);
}

//+------------------------------------------------------------------+
// Opening Range Breakout
void RunORB(string sym, string tag, double risk_pct,
            int ref_h, double rmin, double rmax, bool &fired)
{
   // Reference bar: the H1 bar that opened at ref_h:00 UTC today
   datetime today_utc = (datetime)(TimeGMT() / 86400 * 86400);
   datetime ref_utc   = today_utc + ref_h * 3600;
   if (TimeGMT() < ref_utc + 3600) return;  // ref bar not yet closed

   MqlRates ref[];
   int n = CopyRates(sym, PERIOD_H1, ToServer(ref_utc), ToServer(ref_utc)+3599, ref);
   if (n < 1) { Print(tag," ref bar not found at UTC ",ref_h,":00"); return; }

   double rhi = ref[0].high;
   double rlo = ref[0].low;
   double rng = rhi - rlo;
   if (rng < rmin || rng > rmax) return;  // range filter

   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);

   // Enter at market when price breaches the ORB level
   if      (ask > rhi) Enter(sym,  1, ask, rlo, risk_pct, tag, fired);
   else if (bid < rlo) Enter(sym, -1, bid, rhi, risk_pct, tag, fired);
}
