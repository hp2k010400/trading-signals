//+------------------------------------------------------------------+
//| 10kbotV3.mq5  —  GC4C £10k/mo 8-Strategy Bot                    |
//| v3.00                                                             |
//|                                                                   |
//|  ORB STRATEGIES (morning breakout, SL = ref-bar opposite edge):  |
//|  1. DAX_ORB  GER40   08:00 ref  09:00-12:00 UTC  all days  0.75%|
//|  2. NAS_ORB  US100   13:00 ref  14:00-16:00 UTC  Tue/Thu   0.75%|
//|  3. SP5_ORB  US500   13:00 ref  14:00-16:00 UTC  skip Mon  0.40%|
//|                                                                   |
//|  LONDON CLOSE REVERSAL (fade morning move at 16:00 UTC):         |
//|  4. LC_EUR   EURUSD  16:00 UTC  skip Fri  0.40%  min 20 pips    |
//|  5. LC_GBP   GBPUSD  16:00 UTC  skip Fri  0.40%  min 25 pips    |
//|  6. LC_DAX   GER40   16:00 UTC  skip Fri  0.75%  min 30 pts     |
//|  7. LC_UK    UK100   16:00 UTC  skip Fri  0.75%  min 30 pts     |
//|  8. LC_GOLD  XAUUSD  16:00 UTC  skip Fri  0.40%  min 8 USD      |
//|                                                                   |
//|  Trail: 0.1R after 1R breakeven                                  |
//|  News:  MT5 economic calendar HIGH impact +/-30 min              |
//|  Safety: daily loss CB, instrument cooldown, fired-flag restore  |
//|  Friday: close all positions at 20:00 UTC                        |
//|  Attach to ANY chart. Timer fires every 60 seconds.              |
//+------------------------------------------------------------------+
#property copyright "GC4C"
#property version   "3.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

CTrade        trade;
CPositionInfo pos;

//── Symbol inputs ─────────────────────────────────────────────────────────────
input string  Sym_DAX    = "GER40.cash";
input string  Sym_NAS100 = "US100.cash";
input string  Sym_SP500  = "US500.cash";
input string  Sym_EURUSD = "EURUSD";
input string  Sym_GBPUSD = "GBPUSD";
input string  Sym_UK100  = "UK100.cash";
input string  Sym_GOLD   = "XAUUSD";

//── Risk inputs ───────────────────────────────────────────────────────────────
input double  Risk_ORB_HIGH  = 0.75;   // DAX_ORB / NAS_ORB
input double  Risk_ORB_MED   = 0.40;   // SP5_ORB
input double  Risk_LC_IDX    = 0.75;   // LC_DAX / LC_UK
input double  Risk_LC_FX     = 0.40;   // LC_EUR / LC_GBP / LC_GOLD
input double  Trail_R        = 0.10;   // Trail step = 0.1 * original SL distance

//── Timing inputs ─────────────────────────────────────────────────────────────
input int     Server_UTC    = 3;       // Server offset from UTC (hours)
input int     DAX_RefH      = 8;       // DAX ref-bar UTC hour
input int     DAX_Start     = 9;       // DAX ORB window open UTC
input int     DAX_End       = 12;      // DAX ORB window close UTC
input int     US_RefH       = 13;      // US ref-bar UTC hour
input int     US_Start      = 14;      // US ORB window open UTC
input int     US_End        = 16;      // US ORB window close UTC
input int     LC_Hour       = 16;      // LC entry hour UTC (fire at or after)
input int     LC_MornStart  = 7;       // Morning session open UTC (07:00 bar)
input int     LC_MornEnd    = 15;      // Last morning bar UTC (15:00 bar)

//── LC min-move inputs ────────────────────────────────────────────────────────
input double  LC_MinMove_EUR  = 0.0020; // 20 pips on EURUSD
input double  LC_MinMove_GBP  = 0.0025; // 25 pips on GBPUSD
input double  LC_MinMove_IDX  = 30.0;   // 30 pts on GER40 / UK100
input double  LC_MinMove_GOLD = 8.0;    // $8 on XAUUSD

//── Safety inputs ─────────────────────────────────────────────────────────────
input bool    UseNews        = true;
input int     NewsPauseMin   = 30;
input double  MaxDailyLoss   = 3.5;    // % equity circuit breaker
input bool    CloseFriday    = true;   // Auto-close all positions Friday eve
input int     FridayCloseH   = 20;     // UTC hour to close on Friday
input int     Magic          = 20260627;

//── State ─────────────────────────────────────────────────────────────────────
bool g_dax_orb, g_nas_orb, g_sp5_orb;
bool g_lc_eur,  g_lc_gbp,  g_lc_dax,  g_lc_uk,  g_lc_gold;
bool g_blk_dax, g_blk_nas, g_blk_sp5;
bool g_blk_eur, g_blk_gbp, g_blk_uk,  g_blk_gold;
bool g_friday_closed;

datetime g_last_reset = 0;
double   g_day_equity = 0;

struct TTrail { ulong ticket; double best; double orig_sld; };
TTrail g_trails[50];
int    g_trail_n = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(Magic);
   trade.SetDeviationInPoints(20);
   EventSetTimer(60);
   g_last_reset = (datetime)(TimeGMT()/86400*86400);
   g_day_equity = AccountInfoDouble(ACCOUNT_EQUITY);
   RestoreFiredFlags();
   CheckSLHits();
   Print("10kbotV3 v3.00 online | Magic=",Magic," | Server_UTC=",Server_UTC);
   return INIT_SUCCEEDED;
}
void OnDeinit(const int r) { EventKillTimer(); }

//+------------------------------------------------------------------+
void OnTimer()
{
   ResetDaily();
   ManageTrails();
   CheckSLHits();
   if(DailyLossExceeded()) return;

   int h   = UtcHour();
   int dow = UtcDow(); // 0=Sun 1=Mon 2=Tue 3=Wed 4=Thu 5=Fri 6=Sat

   // Friday auto-close
   if(CloseFriday && dow == 5 && h >= FridayCloseH && !g_friday_closed)
   { CloseAll(); g_friday_closed = true; return; }

   // ── ORB strategies ────────────────────────────────────────────────────────
   if(h >= DAX_Start && h < DAX_End)
      if(!g_dax_orb)
         RunORB(Sym_DAX,"DAX_ORB",Risk_ORB_HIGH,DAX_RefH,30.0,300.0,g_dax_orb);

   if(h >= US_Start && h < US_End)
   {
      if((dow==2||dow==4) && !g_nas_orb)  // Tue / Thu only
         RunORB(Sym_NAS100,"NAS_ORB",Risk_ORB_HIGH,US_RefH,50.0,1500.0,g_nas_orb);
      if(dow!=1 && !g_sp5_orb)            // skip Mon
         RunORB(Sym_SP500, "SP5_ORB",Risk_ORB_MED, US_RefH, 5.0, 300.0,g_sp5_orb);
   }

   // ── London Close Reversal (16:00 UTC, skip Fri) ───────────────────────────
   if(dow != 5 && h >= LC_Hour)
   {
      if(!g_lc_eur)  RunLC(Sym_EURUSD,"LC_EUR", Risk_LC_FX,  LC_MinMove_EUR,  g_lc_eur);
      if(!g_lc_gbp)  RunLC(Sym_GBPUSD,"LC_GBP", Risk_LC_FX,  LC_MinMove_GBP,  g_lc_gbp);
      if(!g_lc_dax)  RunLC(Sym_DAX,   "LC_DAX", Risk_LC_IDX, LC_MinMove_IDX,  g_lc_dax);
      if(!g_lc_uk)   RunLC(Sym_UK100, "LC_UK",  Risk_LC_IDX, LC_MinMove_IDX,  g_lc_uk);
      if(!g_lc_gold) RunLC(Sym_GOLD,  "LC_GOLD",Risk_LC_FX,  LC_MinMove_GOLD, g_lc_gold);
   }
}

//+------------------------------------------------------------------+
int  UtcHour() { return (int)(TimeGMT()%86400)/3600; }
int  UtcDow()  { MqlDateTime t; TimeToStruct(TimeGMT(),t); return t.day_of_week; }
datetime ToServer(datetime u) { return u + Server_UTC*3600; }

//+------------------------------------------------------------------+
void ResetDaily()
{
   datetime today = (datetime)(TimeGMT()/86400*86400);
   if(g_last_reset == today) return;
   g_dax_orb = g_nas_orb  = g_sp5_orb  = false;
   g_lc_eur  = g_lc_gbp   = g_lc_dax   = g_lc_uk  = g_lc_gold = false;
   g_blk_dax = g_blk_nas  = g_blk_sp5  = false;
   g_blk_eur = g_blk_gbp  = g_blk_uk   = g_blk_gold = false;
   g_friday_closed = false;
   g_last_reset = today;
   g_day_equity = AccountInfoDouble(ACCOUNT_EQUITY);
   Print("10kbotV3 daily reset");
}

//+------------------------------------------------------------------+
bool DailyLossExceeded()
{
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if((g_day_equity - eq)/g_day_equity*100.0 >= MaxDailyLoss)
   { Print("10kbotV3 circuit breaker fired — daily loss limit hit"); return true; }
   return false;
}

//+------------------------------------------------------------------+
bool NewsNear(string sym)
{
   if(!UseNews) return false;
   datetime now = TimeGMT();
   MqlCalendarValue vals[];
   int n = CalendarValueHistory(vals, now - NewsPauseMin*60, now + NewsPauseMin*60);
   if(n <= 0) return false;
   for(int i = 0; i < n; i++)
   {
      MqlCalendarEvent ev;
      if(!CalendarEventById(vals[i].event_id,ev)) continue;
      if(ev.importance != CALENDAR_IMPORTANCE_HIGH) continue;
      MqlCalendarCountry co;
      if(!CalendarCountryById(ev.country_id,co)) continue;
      string c = co.currency;
      if(c == "USD") return true;
      if(c == "EUR" && (StringFind(sym,"EUR")>=0 || StringFind(sym,"GER")>=0)) return true;
      if(c == "GBP" && (StringFind(sym,"GBP")>=0 || StringFind(sym,"UK1")>=0)) return true;
   }
   return false;
}

//+------------------------------------------------------------------+
bool GetBlkFlag(string sym)
{
   if(sym == Sym_DAX)    return g_blk_dax;
   if(sym == Sym_NAS100) return g_blk_nas;
   if(sym == Sym_SP500)  return g_blk_sp5;
   if(sym == Sym_EURUSD) return g_blk_eur;
   if(sym == Sym_GBPUSD) return g_blk_gbp;
   if(sym == Sym_UK100)  return g_blk_uk;
   return g_blk_gold;
}
void SetBlkFlag(string sym)
{
   if(sym == Sym_DAX)    { g_blk_dax  = true; return; }
   if(sym == Sym_NAS100) { g_blk_nas  = true; return; }
   if(sym == Sym_SP500)  { g_blk_sp5  = true; return; }
   if(sym == Sym_EURUSD) { g_blk_eur  = true; return; }
   if(sym == Sym_GBPUSD) { g_blk_gbp  = true; return; }
   if(sym == Sym_UK100)  { g_blk_uk   = true; return; }
   g_blk_gold = true;
}

//+------------------------------------------------------------------+
void CheckSLHits()
{
   datetime day = (datetime)(TimeGMT()/86400*86400);
   HistorySelect(day, TimeGMT());
   for(int i = HistoryDealsTotal()-1; i >= 0; i--)
   {
      ulong tk = HistoryDealGetTicket(i);
      if(HistoryDealGetInteger(tk,DEAL_MAGIC) != Magic)          continue;
      if(HistoryDealGetInteger(tk,DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      if(HistoryDealGetDouble(tk,DEAL_PROFIT) >= -5.0)           continue;
      SetBlkFlag(HistoryDealGetString(tk,DEAL_SYMBOL));
   }
}

//+------------------------------------------------------------------+
void RestoreFiredFlags()
{
   datetime day = (datetime)(TimeGMT()/86400*86400);
   HistorySelect(day, TimeGMT());
   for(int i = HistoryDealsTotal()-1; i >= 0; i--)
   {
      ulong tk = HistoryDealGetTicket(i);
      if(HistoryDealGetInteger(tk,DEAL_MAGIC) != Magic)         continue;
      if(HistoryDealGetInteger(tk,DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
      SetFiredFlag(HistoryDealGetString(tk,DEAL_COMMENT));
   }
   for(int i = PositionsTotal()-1; i >= 0; i--)
      if(pos.SelectByIndex(i) && pos.Magic() == Magic)
         SetFiredFlag(pos.Comment());
}
void SetFiredFlag(string t)
{
   if(t == "DAX_ORB") { g_dax_orb = true; return; }
   if(t == "NAS_ORB") { g_nas_orb = true; return; }
   if(t == "SP5_ORB") { g_sp5_orb = true; return; }
   if(t == "LC_EUR")  { g_lc_eur  = true; return; }
   if(t == "LC_GBP")  { g_lc_gbp  = true; return; }
   if(t == "LC_DAX")  { g_lc_dax  = true; return; }
   if(t == "LC_UK")   { g_lc_uk   = true; return; }
   if(t == "LC_GOLD") { g_lc_gold = true; return; }
}

//+------------------------------------------------------------------+
double CalcLots(string sym, double entry, double sl, double risk_pct)
{
   double sl_d = MathAbs(entry - sl);
   if(sl_d <= 0) return 0;
   double tv = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   if(tv <= 0 || ts <= 0) return 0;
   double risk = AccountInfoDouble(ACCOUNT_EQUITY) * risk_pct / 100.0;
   double lots = risk / (sl_d/ts*tv);
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   lots = MathFloor(lots/step)*step;
   return MathMax(SymbolInfoDouble(sym,SYMBOL_VOLUME_MIN),
          MathMin(SymbolInfoDouble(sym,SYMBOL_VOLUME_MAX),lots));
}

//+------------------------------------------------------------------+
bool HasPos(string sym)
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
      if(pos.SelectByIndex(i) && pos.Symbol() == sym)
         return true;
   return false;
}

//+------------------------------------------------------------------+
bool Enter(string sym, int dir, double entry, double sl,
           double risk_pct, string tag, bool &fired)
{
   if(HasPos(sym))     { Print(tag," SKIP HasPos");        return false; }
   if(GetBlkFlag(sym)) { Print(tag," SKIP InstCooldown");  return false; }
   if(NewsNear(sym))   { Print(tag," SKIP News");          return false; }
   double lots = CalcLots(sym, entry, sl, risk_pct);
   if(lots <= 0)       { Print(tag," SKIP lots=0");        return false; }
   double min_stop = SymbolInfoInteger(sym,SYMBOL_TRADE_STOPS_LEVEL)
                     * SymbolInfoDouble(sym,SYMBOL_POINT);
   if(MathAbs(entry-sl) < min_stop)
   { Print(tag," SKIP SL<MinStop"); return false; }
   bool ok = (dir == 1) ? trade.Buy(lots,sym,0,sl,0,tag)
                        : trade.Sell(lots,sym,0,sl,0,tag);
   if(ok)
   {
      SetTrailBest(trade.ResultOrder(), entry, MathAbs(entry-sl));
      fired = true;
      Print(tag," ",(dir==1?"BUY":"SELL")," ",DoubleToString(lots,2),
            " entry=",DoubleToString(entry,_Digits),
            " sl=",DoubleToString(sl,_Digits));
   }
   return ok;
}

//+------------------------------------------------------------------+
void SetTrailBest(ulong tk, double best, double orig_sld)
{
   for(int i = 0; i < g_trail_n; i++)
   {
      if(g_trails[i].ticket == tk)
      {
         g_trails[i].best = best;
         if(orig_sld > 0 && g_trails[i].orig_sld <= 0) g_trails[i].orig_sld = orig_sld;
         return;
      }
   }
   if(g_trail_n < 50)
   {
      g_trails[g_trail_n].ticket   = tk;
      g_trails[g_trail_n].best     = best;
      g_trails[g_trail_n].orig_sld = orig_sld;
      g_trail_n++;
   }
}
double GetTrailBest(ulong tk, double def)
{
   for(int i = 0; i < g_trail_n; i++)
      if(g_trails[i].ticket == tk) return g_trails[i].best;
   return def;
}
double GetTrailOrigSld(ulong tk)
{
   for(int i = 0; i < g_trail_n; i++)
      if(g_trails[i].ticket == tk) return g_trails[i].orig_sld;
   return 0;
}
double GetATR(string sym, int period=14)
{
   double buf[];
   int h = iATR(sym, PERIOD_H1, period);
   if(h == INVALID_HANDLE) return 0;
   if(CopyBuffer(h,0,0,1,buf) < 1) { IndicatorRelease(h); return 0; }
   IndicatorRelease(h);
   return buf[0];
}
void CleanTrails()
{
   int w = 0;
   for(int i = 0; i < g_trail_n; i++)
   {
      bool alive = false;
      for(int j = PositionsTotal()-1; j >= 0; j--)
         if(pos.SelectByIndex(j) && pos.Ticket() == g_trails[i].ticket)
         { alive = true; break; }
      if(alive) g_trails[w++] = g_trails[i];
   }
   g_trail_n = w;
}

//+------------------------------------------------------------------+
void ManageTrails()
{
   CleanTrails();
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      if(!pos.SelectByIndex(i) || pos.Magic() != Magic) continue;
      string sym    = pos.Symbol();
      double entry  = pos.PriceOpen();
      double sl_cur = pos.StopLoss();
      ulong  tk     = pos.Ticket();
      double pt     = SymbolInfoDouble(sym, SYMBOL_POINT);
      double sld    = MathAbs(entry - sl_cur);
      double eff    = sld > 0 ? sld : GetTrailOrigSld(tk);
      if(eff <= 0) eff = GetATR(sym) * 1.5;
      if(eff <= 0) continue;
      double trail  = eff * Trail_R;

      if(pos.PositionType() == POSITION_TYPE_BUY)
      {
         double bid  = SymbolInfoDouble(sym, SYMBOL_BID);
         double best = GetTrailBest(tk, entry);
         if(bid > best) { best = bid; SetTrailBest(tk, best, sld); }
         if(best >= entry + eff && sl_cur < entry - pt)
            trade.PositionModify(sym, entry, 0);
         if(sl_cur >= entry - pt)
         { double ns = best - trail; if(ns > sl_cur + pt) trade.PositionModify(sym, ns, 0); }
      }
      else
      {
         double ask  = SymbolInfoDouble(sym, SYMBOL_ASK);
         double best = GetTrailBest(tk, entry);
         if(ask < best) { best = ask; SetTrailBest(tk, best, sld); }
         if(best <= entry - eff && sl_cur > entry + pt)
            trade.PositionModify(sym, entry, 0);
         if(sl_cur <= entry + pt)
         { double ns = best + trail; if(ns < sl_cur - pt) trade.PositionModify(sym, ns, 0); }
      }
   }
}

//+------------------------------------------------------------------+
void CloseAll()
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
      if(pos.SelectByIndex(i) && pos.Magic() == Magic)
         trade.PositionClose(pos.Ticket());
   Print("10kbotV3 Friday auto-close complete");
}

//+------------------------------------------------------------------+
void RunORB(string sym, string tag, double risk_pct,
            int ref_h, double rmin, double rmax, bool &fired)
{
   datetime today_utc = (datetime)(TimeGMT()/86400*86400);
   datetime ref_utc   = today_utc + ref_h*3600;
   if(TimeGMT() < ref_utc + 3600) return;  // wait for ref bar to close
   MqlRates ref[];
   int n = CopyRates(sym, PERIOD_H1, ToServer(ref_utc), ToServer(ref_utc)+3599, ref);
   if(n < 1) { Print(tag," ref bar not found UTC ",ref_h,":00"); return; }
   double rhi = ref[0].high, rlo = ref[0].low;
   if(rhi - rlo < rmin || rhi - rlo > rmax) return;
   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   if     (ask > rhi) Enter(sym,  1, ask, rlo, risk_pct, tag, fired);
   else if(bid < rlo) Enter(sym, -1, bid, rhi, risk_pct, tag, fired);
}

//+------------------------------------------------------------------+
//| London Close Reversal                                            |
//| Logic: if morning (07:00 open → 15:00 close) moved > min_move,  |
//|   fade that move at 16:00. SL = session high/low + 10% buffer.  |
//+------------------------------------------------------------------+
void RunLC(string sym, string tag, double risk_pct, double min_move, bool &fired)
{
   datetime today_utc = (datetime)(TimeGMT()/86400*86400);
   if(TimeGMT() < today_utc + LC_Hour*3600) return; // wait for 16:00 UTC

   // 07:00 bar — morning open
   datetime bar07_utc = today_utc + LC_MornStart*3600;
   MqlRates bar07[];
   int n = CopyRates(sym, PERIOD_H1, ToServer(bar07_utc), ToServer(bar07_utc)+3599, bar07);
   if(n < 1) { Print(tag," no 07:00 bar"); return; }
   double morn_open = bar07[0].open;

   // 15:00 bar — morning close (bar closes at 16:00 UTC, so available after our check)
   datetime bar15_utc = today_utc + LC_MornEnd*3600;
   MqlRates bar15[];
   n = CopyRates(sym, PERIOD_H1, ToServer(bar15_utc), ToServer(bar15_utc)+3599, bar15);
   if(n < 1) { Print(tag," no 15:00 bar"); return; }
   double morn_close = bar15[0].close;

   double move = morn_close - morn_open;
   if(MathAbs(move) < min_move) return; // morning move too small, skip

   // Session high/low (07:00–15:00) for SL placement
   MqlRates sess[];
   n = CopyRates(sym, PERIOD_H1, ToServer(bar07_utc), ToServer(bar15_utc)+3599, sess);
   if(n < 2) { Print(tag," insufficient session bars"); return; }
   double d_hi = -DBL_MAX, d_lo = DBL_MAX;
   for(int i = 0; i < n; i++)
   { d_hi = MathMax(d_hi, sess[i].high); d_lo = MathMin(d_lo, sess[i].low); }
   double buf = (d_hi - d_lo) * 0.10;

   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);

   if(move > min_move)        // Morning rallied → fade SHORT
      Enter(sym, -1, bid, d_hi + buf, risk_pct, tag, fired);
   else if(move < -min_move)  // Morning fell → fade LONG
      Enter(sym,  1, ask, d_lo - buf, risk_pct, tag, fired);
}
