//+------------------------------------------------------------------+
//| 6botV2.mq5  —  GC4C Core 5-Strategy Bot                         |
//|                                                                   |
//|  1. LB_EUR   EURUSD  07:00-10:00 UTC  skip Tue  0.40% risk       |
//|  2. LB_GBP   GBPUSD  07:00-10:00 UTC  skip Tue  0.40% risk       |
//|  3. DAX_ORB  GER40   09:00-12:00 UTC  all days  0.75% risk       |
//|  4. NAS_ORB  US100   14:00-16:00 UTC  skip Mon  0.75% risk       |
//|  5. SP5_ORB  US500   14:00-16:00 UTC  skip Mon  0.40% risk       |
//|  (NG_ORB removed - live SL slippage erodes edge)                 |
//|                                                                   |
//|  Trail: 0.1R after 1R breakeven                                  |
//|  News: MT5 economic calendar HIGH impact +/-30 min               |
//|  Safety: daily loss CB, instrument cooldown, fired-flag restore  |
//|  Attach to ANY chart. Timer fires every 60 seconds.              |
//+------------------------------------------------------------------+
#property copyright "GC4C"
#property version   "2.01"
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

//--- Risk
input double  Risk_LB       = 0.40;
input double  Risk_ORB_HIGH = 0.75;
input double  Risk_ORB_MED  = 0.40;

//--- Trail
input double  Trail_R     = 0.10;

//--- Timing (UTC)
input int     Server_UTC  = 3;
input int     LB_Start    = 7;
input int     LB_End      = 10;
input int     DAX_RefH    = 8;
input int     DAX_Start   = 9;
input int     DAX_End     = 12;
input int     US_RefH     = 13;
input int     US_Start    = 14;
input int     US_End      = 16;

//--- News
input bool    UseNews      = true;
input int     NewsPauseMin = 30;

//--- Safety
input double  MaxDailyLoss = 3.5;
input int     Magic        = 20250625;

//--- Fired flags
bool g_lb_eur, g_lb_gbp, g_dax_orb, g_nas_orb, g_sp5_orb;

//--- Instrument cooldown
bool g_blk_eur, g_blk_gbp, g_blk_dax, g_blk_nas, g_blk_sp5;

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
   // Set last_reset to today BEFORE RestoreFiredFlags so ResetDaily()
   // on first timer tick does not wipe the restored fired flags
   g_last_reset = (datetime)(TimeGMT()/86400*86400);
   g_day_equity = AccountInfoDouble(ACCOUNT_EQUITY);
   RestoreFiredFlags();
   CheckSLHits();
   Print("6botV2 v2.03 online | Magic=",Magic," | Server_UTC=",Server_UTC);
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
   int dow = UtcDow();

   if(dow!=2 && h>=LB_Start && h<LB_End)
   {
      if(!g_lb_eur) RunLB(Sym_EURUSD,"LB_EUR",Risk_LB,0.0001,g_lb_eur);
      if(!g_lb_gbp) RunLB(Sym_GBPUSD,"LB_GBP",Risk_LB,0.0001,g_lb_gbp);
   }

   if(h>=DAX_Start && h<DAX_End)
      if(!g_dax_orb) RunORB(Sym_DAX,"DAX_ORB",Risk_ORB_HIGH,DAX_RefH,30.0,300.0,g_dax_orb);

   if(dow!=1 && h>=US_Start && h<US_End)
   {
      if(!g_nas_orb) RunORB(Sym_NAS100,"NAS_ORB",Risk_ORB_HIGH,US_RefH,50.0,1500.0,g_nas_orb);
      if(!g_sp5_orb) RunORB(Sym_SP500, "SP5_ORB",Risk_ORB_MED, US_RefH, 5.0, 300.0,g_sp5_orb);
   }
}

//+------------------------------------------------------------------+
int UtcHour() { return (int)(TimeGMT()%86400)/3600; }
int UtcDow()  { MqlDateTime t; TimeToStruct(TimeGMT(),t); return t.day_of_week; }
datetime ToServer(datetime u) { return u + Server_UTC*3600; }

//+------------------------------------------------------------------+
void ResetDaily()
{
   datetime today=(datetime)(TimeGMT()/86400*86400);
   if(g_last_reset==today) return;
   g_lb_eur=g_lb_gbp=g_dax_orb=g_nas_orb=g_sp5_orb=false;
   g_blk_eur=g_blk_gbp=g_blk_dax=g_blk_nas=g_blk_sp5=false;
   g_last_reset=today;
   g_day_equity=AccountInfoDouble(ACCOUNT_EQUITY);
   Print("6botV2 daily reset");
}

bool DailyLossExceeded()
{
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   if((g_day_equity-eq)/g_day_equity*100.0>=MaxDailyLoss)
   { Print("Circuit breaker fired"); return true; }
   return false;
}

//+------------------------------------------------------------------+
bool NewsNear(string sym)
{
   if(!UseNews) return false;
   datetime now=TimeGMT();
   MqlCalendarValue vals[];
   int n=CalendarValueHistory(vals,now-NewsPauseMin*60,now+NewsPauseMin*60);
   if(n<=0) return false;
   for(int i=0;i<n;i++)
   {
      MqlCalendarEvent ev;
      if(!CalendarEventById(vals[i].event_id,ev)) continue;
      if(ev.importance!=CALENDAR_IMPORTANCE_HIGH) continue;
      MqlCalendarCountry co;
      if(!CalendarCountryById(ev.country_id,co)) continue;
      string c=co.currency;
      if(c=="USD") return true;
      if(c=="EUR"&&(StringFind(sym,"EUR")>=0||StringFind(sym,"GER")>=0)) return true;
      if(c=="GBP"&&StringFind(sym,"GBP")>=0) return true;
   }
   return false;
}

//+------------------------------------------------------------------+
bool GetBlkFlag(string sym)
{
   if(sym==Sym_EURUSD) return g_blk_eur;
   if(sym==Sym_GBPUSD) return g_blk_gbp;
   if(sym==Sym_DAX)    return g_blk_dax;
   if(sym==Sym_NAS100) return g_blk_nas;
   return g_blk_sp5;
}
void SetBlkFlag(string sym)
{
   if(sym==Sym_EURUSD){g_blk_eur=true;return;}
   if(sym==Sym_GBPUSD){g_blk_gbp=true;return;}
   if(sym==Sym_DAX)   {g_blk_dax=true;return;}
   if(sym==Sym_NAS100){g_blk_nas=true;return;}
   g_blk_sp5=true;
}

void CheckSLHits()
{
   datetime day=(datetime)(TimeGMT()/86400*86400);
   HistorySelect(day,TimeGMT());
   for(int i=HistoryDealsTotal()-1;i>=0;i--)
   {
      ulong tk=HistoryDealGetTicket(i);
      if(HistoryDealGetInteger(tk,DEAL_MAGIC) !=Magic)          continue;
      if(HistoryDealGetInteger(tk,DEAL_ENTRY) !=DEAL_ENTRY_OUT) continue;
      if(HistoryDealGetDouble(tk,DEAL_PROFIT) >=-5.0)           continue;
      SetBlkFlag(HistoryDealGetString(tk,DEAL_SYMBOL));
   }
}

//+------------------------------------------------------------------+
void RestoreFiredFlags()
{
   datetime day=(datetime)(TimeGMT()/86400*86400);
   HistorySelect(day,TimeGMT());
   for(int i=HistoryDealsTotal()-1;i>=0;i--)
   {
      ulong tk=HistoryDealGetTicket(i);
      if(HistoryDealGetInteger(tk,DEAL_MAGIC) !=Magic)          continue;
      if(HistoryDealGetInteger(tk,DEAL_ENTRY) !=DEAL_ENTRY_IN)  continue;
      SetFiredFlag(HistoryDealGetString(tk,DEAL_COMMENT));
   }
   for(int i=PositionsTotal()-1;i>=0;i--)
      if(pos.SelectByIndex(i)&&pos.Magic()==Magic)
         SetFiredFlag(pos.Comment());
}
void SetFiredFlag(string t)
{
   if(t=="LB_EUR")  g_lb_eur =true;
   if(t=="LB_GBP")  g_lb_gbp =true;
   if(t=="DAX_ORB") g_dax_orb=true;
   if(t=="NAS_ORB") g_nas_orb=true;
   if(t=="SP5_ORB") g_sp5_orb=true;
}

//+------------------------------------------------------------------+
double CalcLots(string sym, double entry, double sl, double risk_pct)
{
   double sl_d=MathAbs(entry-sl);
   if(sl_d<=0) return 0;
   double tv=SymbolInfoDouble(sym,SYMBOL_TRADE_TICK_VALUE);
   double ts=SymbolInfoDouble(sym,SYMBOL_TRADE_TICK_SIZE);
   if(tv<=0||ts<=0) return 0;
   double risk=AccountInfoDouble(ACCOUNT_EQUITY)*risk_pct/100.0;
   double lots=risk/(sl_d/ts*tv);
   double step=SymbolInfoDouble(sym,SYMBOL_VOLUME_STEP);
   lots=MathFloor(lots/step)*step;
   return MathMax(SymbolInfoDouble(sym,SYMBOL_VOLUME_MIN),
          MathMin(SymbolInfoDouble(sym,SYMBOL_VOLUME_MAX),lots));
}

bool HasPos(string sym)
{
   for(int i=PositionsTotal()-1;i>=0;i--)
      if(pos.SelectByIndex(i)&&pos.Symbol()==sym&&pos.Magic()==Magic)
         return true;
   return false;
}

bool Enter(string sym, int dir, double entry, double sl,
           double risk_pct, string tag, bool &fired)
{
   if(HasPos(sym))     {Print(tag," SKIP HasPos");       return false;}
   if(GetBlkFlag(sym)) {Print(tag," SKIP InstCooldown"); return false;}
   if(NewsNear(sym))   {Print(tag," SKIP News");         return false;}
   double lots=CalcLots(sym,entry,sl,risk_pct);
   if(lots<=0)         {Print(tag," SKIP lots=0");       return false;}
   double min_stop=SymbolInfoInteger(sym,SYMBOL_TRADE_STOPS_LEVEL)
                   *SymbolInfoDouble(sym,SYMBOL_POINT);
   if(MathAbs(entry-sl)<min_stop){Print(tag," SKIP SL<MinStop"); return false;}
   bool ok=(dir==1)?trade.Buy(lots,sym,0,sl,0,tag):trade.Sell(lots,sym,0,sl,0,tag);
   if(ok)
   {
      SetTrailBest(trade.ResultOrder(),entry,MathAbs(entry-sl));
      fired=true;
      Print(tag," ",(dir==1?"BUY":"SELL")," ",DoubleToString(lots,2)," SL=",sl);
   }
   return ok;
}

//+------------------------------------------------------------------+
void SetTrailBest(ulong tk, double best, double orig_sld)
{
   for(int i=0;i<g_trail_n;i++)
   {
      if(g_trails[i].ticket==tk)
      {
         g_trails[i].best=best;
         if(orig_sld>0&&g_trails[i].orig_sld<=0) g_trails[i].orig_sld=orig_sld;
         return;
      }
   }
   if(g_trail_n<50)
   {
      g_trails[g_trail_n].ticket=tk;
      g_trails[g_trail_n].best=best;
      g_trails[g_trail_n].orig_sld=orig_sld;
      g_trail_n++;
   }
}
double GetTrailBest(ulong tk, double def)
{
   for(int i=0;i<g_trail_n;i++) if(g_trails[i].ticket==tk) return g_trails[i].best;
   return def;
}
double GetTrailOrigSld(ulong tk)
{
   for(int i=0;i<g_trail_n;i++) if(g_trails[i].ticket==tk) return g_trails[i].orig_sld;
   return 0;
}
double GetATR(string sym, int period=14)
{
   double buf[];
   int h=iATR(sym,PERIOD_H1,period);
   if(h==INVALID_HANDLE) return 0;
   if(CopyBuffer(h,0,0,1,buf)<1){IndicatorRelease(h);return 0;}
   IndicatorRelease(h);
   return buf[0];
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
   CleanTrails();
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      if(!pos.SelectByIndex(i)||pos.Magic()!=Magic) continue;
      string sym   =pos.Symbol();
      double entry =pos.PriceOpen();
      double sl_cur=pos.StopLoss();
      ulong  tk    =pos.Ticket();
      double pt    =SymbolInfoDouble(sym,SYMBOL_POINT);
      double sld   =MathAbs(entry-sl_cur);
      double eff   =sld>0?sld:GetTrailOrigSld(tk);
      if(eff<=0) eff=GetATR(sym)*1.5;   // fallback when SL=entry and orig lost on reload
      if(eff<=0) continue;
      double trail=eff*Trail_R;

      if(pos.PositionType()==POSITION_TYPE_BUY)
      {
         double bid =SymbolInfoDouble(sym,SYMBOL_BID);
         double best=GetTrailBest(tk,entry);
         if(bid>best){best=bid;SetTrailBest(tk,best,sld);}
         if(best>=entry+eff&&sl_cur<entry-pt) trade.PositionModify(sym,entry,0);
         if(sl_cur>=entry-pt){double ns=best-trail;if(ns>sl_cur+pt) trade.PositionModify(sym,ns,0);}
      }
      else
      {
         double ask =SymbolInfoDouble(sym,SYMBOL_ASK);
         double best=GetTrailBest(tk,entry);
         if(ask<best){best=ask;SetTrailBest(tk,best,sld);}
         if(best<=entry-eff&&sl_cur>entry+pt) trade.PositionModify(sym,entry,0);
         if(sl_cur<=entry+pt){double ns=best+trail;if(ns<sl_cur-pt) trade.PositionModify(sym,ns,0);}
      }
   }
}

//+------------------------------------------------------------------+
void RunLB(string sym, string tag, double risk_pct, double pip, bool &fired)
{
   datetime today_utc=(datetime)(TimeGMT()/86400*86400);
   datetime rng_s=today_utc-2*3600;
   datetime rng_e=today_utc+LB_Start*3600;
   MqlRates bars[];
   int n=CopyRates(sym,PERIOD_H1,ToServer(rng_s),ToServer(rng_e),bars);
   if(n<3){Print(tag," range bars=",n);return;}
   double a_hi=-DBL_MAX,a_lo=DBL_MAX;
   for(int i=0;i<n;i++){a_hi=MathMax(a_hi,bars[i].high);a_lo=MathMin(a_lo,bars[i].low);}
   double rng=a_hi-a_lo;
   if(rng/pip<10||rng/pip>100) return;
   double buf=rng*0.15;
   double ask=SymbolInfoDouble(sym,SYMBOL_ASK);
   double bid=SymbolInfoDouble(sym,SYMBOL_BID);
   if     (ask>a_hi+buf) Enter(sym, 1,ask,a_lo-buf,risk_pct,tag,fired);
   else if(bid<a_lo-buf) Enter(sym,-1,bid,a_hi+buf,risk_pct,tag,fired);
}

//+------------------------------------------------------------------+
void RunORB(string sym, string tag, double risk_pct,
            int ref_h, double rmin, double rmax, bool &fired)
{
   datetime today_utc=(datetime)(TimeGMT()/86400*86400);
   datetime ref_utc  =today_utc+ref_h*3600;
   if(TimeGMT()<ref_utc+3600) return;
   MqlRates ref[];
   int n=CopyRates(sym,PERIOD_H1,ToServer(ref_utc),ToServer(ref_utc)+3599,ref);
   if(n<1){Print(tag," ref bar not found UTC ",ref_h,":00");return;}
   double rhi=ref[0].high,rlo=ref[0].low;
   if(rhi-rlo<rmin||rhi-rlo>rmax) return;
   double ask=SymbolInfoDouble(sym,SYMBOL_ASK);
   double bid=SymbolInfoDouble(sym,SYMBOL_BID);
   if     (ask>rhi) Enter(sym, 1,ask,rlo,risk_pct,tag,fired);
   else if(bid<rlo) Enter(sym,-1,bid,rhi,risk_pct,tag,fired);
}
