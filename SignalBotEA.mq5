//+------------------------------------------------------------------+
//| SignalBotEA.mq5 — Auto-executes all 5 strategies                 |
//| Attach to ANY chart. Runs in background, checks every 60s.       |
//|                                                                   |
//| Strategies:                                                       |
//|  1. London Breakout  EURUSD, GBPUSD   07:00-10:00 UTC            |
//|  2. DAX ORB          GER40            09:00-12:00 UTC            |
//|  3. NAS100 Open      US100.cash       14:00-16:00 UTC            |
//|  4. DAX H4 EMA       GER40            08:00-16:00 UTC            |
//|  5. Oil H4 EMA       XTIUSD           14:00-21:00 UTC            |
//+------------------------------------------------------------------+
#property copyright "GC4C Signal Bot"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

CTrade         trade;
CPositionInfo  pos;

//--- Input parameters (change symbol names to match your broker)
input string   Sym_EURUSD  = "EURUSD";       // EURUSD symbol
input string   Sym_GBPUSD  = "GBPUSD";       // GBPUSD symbol
input string   Sym_DAX     = "GER40.cash";   // DAX symbol
input string   Sym_NAS100  = "US100.cash";   // NAS100 symbol  ← already visible in your MT5
input string   Sym_OIL     = "XTIUSD";       // Oil symbol

input double   Risk_LB     = 0.4;    // London Breakout risk % per trade
input double   Risk_ORB    = 0.75;   // DAX ORB risk %
input double   Risk_NAS    = 0.75;   // NAS100 Open risk %
input double   Risk_H4     = 0.75;   // H4 EMA risk %

input int      Magic       = 20250619; // unique ID for our trades

//--- Daily fired flags (reset at midnight UTC)
bool  lb_eur_fired   = false;
bool  lb_gbp_fired   = false;
bool  dax_orb_fired  = false;
bool  nas_fired      = false;
bool  h4_dax_fired   = false;
bool  h4_oil_fired   = false;
datetime last_reset  = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(Magic);
   trade.SetDeviationInPoints(20);
   EventSetTimer(60);
   Print("SignalBotEA started | Magic: ", Magic);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); }
void OnTick() {}

//+------------------------------------------------------------------+
void OnTimer()
{
   ResetDailyFlags();
   ManageTrailingStops();
   CheckLondonBreakout();
   CheckDAXOrb();
   CheckNAS100Open();
   CheckH4EMA();
}

//+------------------------------------------------------------------+
//| Reset all daily flags at midnight UTC                            |
//+------------------------------------------------------------------+
void ResetDailyFlags()
{
   MqlDateTime dt;
   TimeToStruct(TimeGMT(), dt);
   datetime today = StringToTime(StringFormat("%d.%02d.%02d 00:00",
                                 dt.year, dt.mon, dt.day));
   if(today != last_reset)
   {
      lb_eur_fired = lb_gbp_fired = dax_orb_fired = false;
      nas_fired    = h4_dax_fired = h4_oil_fired  = false;
      last_reset   = today;
      Print("Daily flags reset");
   }
}

//+------------------------------------------------------------------+
//| Lot size from risk % and SL distance                             |
//+------------------------------------------------------------------+
double CalcLots(string symbol, double sl_points, double risk_pct)
{
   double balance    = AccountInfoDouble(ACCOUNT_BALANCE);
   double risk_money = balance * (risk_pct / 100.0);
   double tick_val   = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_val <= 0 || tick_size <= 0 || sl_points <= 0) return 0.01;
   double sl_ticks   = sl_points / tick_size;
   double lots       = risk_money / (sl_ticks * tick_val);
   double step       = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   lots = MathFloor(lots / step) * step;
   double min_lot    = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double max_lot    = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   return MathMax(min_lot, MathMin(max_lot, lots));
}

//+------------------------------------------------------------------+
//| Place a trade                                                    |
//+------------------------------------------------------------------+
bool OpenTrade(string symbol, ENUM_ORDER_TYPE type, double sl, string comment)
{
   SymbolSelect(symbol, true);
   double price = (type == ORDER_TYPE_BUY)
                  ? SymbolInfoDouble(symbol, SYMBOL_ASK)
                  : SymbolInfoDouble(symbol, SYMBOL_BID);
   double sl_pts = MathAbs(price - sl);
   double lots   = CalcLots(symbol, sl_pts, Risk_ORB); // default, overridden per strategy

   if(lots <= 0) { Print("CalcLots returned 0 for ", symbol); return false; }

   bool ok = (type == ORDER_TYPE_BUY)
             ? trade.Buy(lots, symbol, price, sl, 0, comment)
             : trade.Sell(lots, symbol, price, sl, 0, comment);

   if(ok) Print("TRADE OPENED: ", symbol, " ", EnumToString(type),
                " @ ", price, " SL=", sl, " lots=", lots);
   else   Print("TRADE FAILED: ", symbol, " error=", GetLastError());

   return ok;
}

bool OpenBuy(string symbol, double sl, double risk_pct, string comment)
{
   SymbolSelect(symbol, true);
   double price  = SymbolInfoDouble(symbol, SYMBOL_ASK);
   double sl_pts = MathAbs(price - sl);
   double lots   = CalcLots(symbol, sl_pts, risk_pct);
   if(lots <= 0) return false;
   bool ok = trade.Buy(lots, symbol, price, sl, 0, comment);
   if(ok) Print("BUY ", symbol, " @ ", price, " SL=", sl, " lots=", lots, " [", comment, "]");
   else   Print("BUY FAILED ", symbol, " err=", GetLastError());
   return ok;
}

bool OpenSell(string symbol, double sl, double risk_pct, string comment)
{
   SymbolSelect(symbol, true);
   double price  = SymbolInfoDouble(symbol, SYMBOL_BID);
   double sl_pts = MathAbs(price - sl);
   double lots   = CalcLots(symbol, sl_pts, risk_pct);
   if(lots <= 0) return false;
   bool ok = trade.Sell(lots, symbol, price, sl, 0, comment);
   if(ok) Print("SELL ", symbol, " @ ", price, " SL=", sl, " lots=", lots, " [", comment, "]");
   else   Print("SELL FAILED ", symbol, " err=", GetLastError());
   return ok;
}

//+------------------------------------------------------------------+
//| Trailing stop management — runs every 60s for all our positions  |
//+------------------------------------------------------------------+
void ManageTrailingStops()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!pos.SelectByIndex(i)) continue;
      if(pos.Magic() != Magic)  continue;

      string sym    = pos.Symbol();
      double entry  = pos.PriceOpen();
      double sl_cur = pos.StopLoss();
      double sl_dist = MathAbs(entry - sl_cur);
      double trail  = sl_dist * 0.5;   // trail at 0.5R — proven best config

      if(pos.PositionType() == POSITION_TYPE_BUY)
      {
         double best = pos.PriceHighest();   // highest price reached
         // Move to breakeven once +1R
         if(best >= entry + sl_dist && sl_cur < entry)
         {
            trade.PositionModify(sym, entry, 0);
            Print("BE: ", sym, " SL moved to entry ", entry);
         }
         // Trail behind best price
         double new_sl = best - trail;
         if(new_sl > sl_cur + SymbolInfoDouble(sym, SYMBOL_POINT))
         {
            trade.PositionModify(sym, new_sl, 0);
            Print("TRAIL: ", sym, " SL -> ", new_sl);
         }
      }
      else if(pos.PositionType() == POSITION_TYPE_SELL)
      {
         double best = pos.PriceLowest();
         if(best <= entry - sl_dist && sl_cur > entry)
         {
            trade.PositionModify(sym, entry, 0);
            Print("BE: ", sym, " SL moved to entry ", entry);
         }
         double new_sl = best + trail;
         if(new_sl < sl_cur - SymbolInfoDouble(sym, SYMBOL_POINT))
         {
            trade.PositionModify(sym, new_sl, 0);
            Print("TRAIL: ", sym, " SL -> ", new_sl);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Already have an open position for this symbol from this EA?      |
//+------------------------------------------------------------------+
bool HasPosition(string symbol)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(pos.SelectByIndex(i) && pos.Symbol() == symbol && pos.Magic() == Magic)
         return true;
   return false;
}

//+------------------------------------------------------------------+
//| Get H1 bar data for a symbol                                     |
//+------------------------------------------------------------------+
bool GetH1Bar(string symbol, int shift, double &o, double &h, double &l, double &c)
{
   MqlRates rates[];
   if(CopyRates(symbol, PERIOD_H1, shift, 1, rates) < 1) return false;
   o = rates[0].open; h = rates[0].high;
   l = rates[0].low;  c = rates[0].close;
   return true;
}

double H1High(string symbol, int from_shift, int count)
{
   MqlRates rates[];
   if(CopyRates(symbol, PERIOD_H1, from_shift, count, rates) < 1) return 0;
   double hi = 0;
   for(int i = 0; i < count; i++) hi = MathMax(hi, rates[i].high);
   return hi;
}

double H1Low(string symbol, int from_shift, int count)
{
   MqlRates rates[];
   if(CopyRates(symbol, PERIOD_H1, from_shift, count, rates) < 1) return DBL_MAX;
   double lo = DBL_MAX;
   for(int i = 0; i < count; i++) lo = MathMin(lo, rates[i].low);
   return lo;
}

//+------------------------------------------------------------------+
//| Current UTC hour                                                 |
//+------------------------------------------------------------------+
int UTCHour() { MqlDateTime dt; TimeToStruct(TimeGMT(), dt); return dt.hour; }

//+------------------------------------------------------------------+
//| 1. LONDON BREAKOUT                                               |
//| Asian range: 22:00-07:00 UTC. Break at 07:00-10:00 UTC.         |
//+------------------------------------------------------------------+
void CheckLondonBreakout()
{
   int h = UTCHour();
   if(h < 7 || h >= 10) return;

   string syms[2];   syms[0] = Sym_EURUSD;   syms[1] = Sym_GBPUSD;
   bool  &fired[2];  fired[0] = lb_eur_fired; fired[1] = lb_gbp_fired;
   double pip[2];    pip[0]   = 0.0001;       pip[1]   = 0.0001;

   for(int s = 0; s < 2; s++)
   {
      if(fired[s] || HasPosition(syms[s])) continue;

      // Asian range = previous 9 H1 bars (22:00-07:00 — roughly bars at shift 3-11)
      // Current H1 bar = shift 0 (forming). Asian bars approx shift 3-11.
      double a_hi = H1High(syms[s], 3, 9);
      double a_lo = H1Low (syms[s], 3, 9);
      double rng  = a_hi - a_lo;
      double pips = rng / pip[s];

      if(pips < 10 || pips > 100) continue;

      double price = SymbolInfoDouble(syms[s], SYMBOL_BID);
      double buf   = rng * 0.15;

      if(price > a_hi)   // breakout up
      {
         double sl = a_lo - buf;
         OpenBuy(syms[s], sl, Risk_LB, "LB_BUY");
         fired[s] = true;
         if(s == 0) lb_eur_fired = true; else lb_gbp_fired = true;
      }
      else if(price < a_lo)  // breakout down
      {
         double sl = a_hi + buf;
         OpenSell(syms[s], sl, Risk_LB, "LB_SELL");
         fired[s] = true;
         if(s == 0) lb_eur_fired = true; else lb_gbp_fired = true;
      }
   }
}

//+------------------------------------------------------------------+
//| 2. DAX OPENING RANGE BREAKOUT                                   |
//| ORB = 08:00 H1 bar. Break at 09:00-12:00 UTC.                   |
//+------------------------------------------------------------------+
void CheckDAXOrb()
{
   int h = UTCHour();
   if(h < 9 || h >= 12 || dax_orb_fired || HasPosition(Sym_DAX)) return;

   // 08:00 UTC bar = shift depends on current hour
   // If it's 09:00, the 08:00 bar is at shift 1. If 10:00, shift 2. Etc.
   int orb_shift = h - 8;   // bars ago
   double o, hi, lo, c;
   if(!GetH1Bar(Sym_DAX, orb_shift, o, hi, lo, c)) return;

   double rng = hi - lo;
   if(rng < 30 || rng > 300) return;

   double price = SymbolInfoDouble(Sym_DAX, SYMBOL_BID);

   if(price > hi)
   {
      double sl = lo;
      OpenBuy(Sym_DAX, sl, Risk_ORB, "DAX_ORB_BUY");
      dax_orb_fired = true;
   }
   else if(price < lo)
   {
      double sl = hi;
      OpenSell(Sym_DAX, sl, Risk_ORB, "DAX_ORB_SELL");
      dax_orb_fired = true;
   }
}

//+------------------------------------------------------------------+
//| 3. NAS100 US OPEN                                               |
//| Pre-market bar = 13:00 UTC H1. Break at 14:00-16:00 UTC.        |
//+------------------------------------------------------------------+
void CheckNAS100Open()
{
   int h = UTCHour();
   if(h < 14 || h >= 16 || nas_fired || HasPosition(Sym_NAS100)) return;

   // 13:00 UTC bar: if it's 14:00 shift=1, if 15:00 shift=2
   int ref_shift = h - 13;
   double o, hi, lo, c;
   if(!GetH1Bar(Sym_NAS100, ref_shift, o, hi, lo, c)) return;

   double rng = hi - lo;
   if(rng < 50 || rng > 1500) return;

   double price = SymbolInfoDouble(Sym_NAS100, SYMBOL_BID);

   if(price > hi)
   {
      double sl = lo;
      OpenBuy(Sym_NAS100, sl, Risk_NAS, "NAS_OPEN_BUY");
      nas_fired = true;
   }
   else if(price < lo)
   {
      double sl = hi;
      OpenSell(Sym_NAS100, sl, Risk_NAS, "NAS_OPEN_SELL");
      nas_fired = true;
   }
}

//+------------------------------------------------------------------+
//| 4+5. H4 EMA TREND (DAX, Oil)                                    |
//| EMA 10/20 cross + ADX > 25                                      |
//+------------------------------------------------------------------+
void CheckH4EMA()
{
   CheckH4Single(Sym_DAX,  Risk_H4, 8,  16, h4_dax_fired, "DAX_H4");
   CheckH4Single(Sym_OIL,  Risk_H4, 14, 21, h4_oil_fired, "OIL_H4");
}

void CheckH4Single(string sym, double risk, int sess_start, int sess_end,
                   bool &fired, string tag)
{
   int h = UTCHour();
   if(h < sess_start || h >= sess_end || fired || HasPosition(sym)) return;

   // EMA 10/20 on H4 — use iMA indicator
   int ema10_h = iMA(sym, PERIOD_H4, 10, 0, MODE_EMA, PRICE_CLOSE);
   int ema20_h = iMA(sym, PERIOD_H4, 20, 0, MODE_EMA, PRICE_CLOSE);
   if(ema10_h == INVALID_HANDLE || ema20_h == INVALID_HANDLE) return;

   double ema10[3], ema20[3];
   if(CopyBuffer(ema10_h, 0, 0, 3, ema10) < 3) return;
   if(CopyBuffer(ema20_h, 0, 0, 3, ema20) < 3) return;
   IndicatorRelease(ema10_h); IndicatorRelease(ema20_h);

   // ADX filter
   int adx_h = iADX(sym, PERIOD_H4, 14);
   if(adx_h == INVALID_HANDLE) return;
   double adx[2];
   if(CopyBuffer(adx_h, 0, 0, 2, adx) < 2) return;
   IndicatorRelease(adx_h);
   if(adx[1] < 25) return;   // index 1 = last completed bar

   // ATR for SL sizing
   int atr_h = iATR(sym, PERIOD_H4, 14);
   if(atr_h == INVALID_HANDLE) return;
   double atr[2];
   if(CopyBuffer(atr_h, 0, 0, 2, atr) < 2) return;
   IndicatorRelease(atr_h);

   double price = SymbolInfoDouble(sym, SYMBOL_BID);
   double atr_val = atr[1];

   // Bull cross: ema10 crossed above ema20 on last completed bar
   bool bull_cross = (ema10[1] > ema20[1] && ema10[2] <= ema20[2]);
   bool bear_cross = (ema10[1] < ema20[1] && ema10[2] >= ema20[2]);

   if(bull_cross)
   {
      double sl = price - 1.5 * atr_val;
      OpenBuy(sym, sl, risk, tag + "_BUY");
      fired = true;
   }
   else if(bear_cross)
   {
      double sl = price + 1.5 * atr_val;
      OpenSell(sym, sl, risk, tag + "_SELL");
      fired = true;
   }
}
//+------------------------------------------------------------------+
