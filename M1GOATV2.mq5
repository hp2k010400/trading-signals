//+------------------------------------------------------------------+
//|                                               M1GOATV2.mq5       |
//|     H1 Inside Bar + Pin Bar — 9 Instrument FTMO System           |
//|  DAX | NAS100 | SP500 | EURUSD | GBPUSD | GOLD | NATGAS          |
//|  US30 | USDJPY                                                    |
//|                                                                   |
//|  IB:  compression (inside bar) → breakout. SL = IB range.        |
//|  PB:  wick rejection (pin bar)  → breakout. SL = full bar range. |
//|  TP:  4R on all signals.                                          |
//|                                                                   |
//|  PF 3.15 OOS 2022-2026 | FTMO pass rate ≥98.5% (MC 5000 sims)   |
//|  0% signal overlap between IB and PB strategies.                 |
//|                                                                   |
//|  Chart setup (run one instance per chart):                        |
//|  DAX/NAS100/SP500/EURUSD/GBPUSD/GOLD/NATGAS/US30 → STRATEGY_BOTH |
//|  USDJPY → STRATEGY_PB  (IB edge absent on this pair)             |
//+------------------------------------------------------------------+
#property copyright "M1GOATV2"
#property version   "2.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

enum ENUM_STRATEGY
{
    STRATEGY_BOTH = 0,  // IB + Pin Bar (default — all except USDJPY)
    STRATEGY_IB   = 1,  // Inside Bar only
    STRATEGY_PB   = 2,  // Pin Bar only  (use on USDJPY chart)
};

//── Inputs ──────────────────────────────────────────────────────────
input group "=== Risk Management ==="
input double InpRiskPct      = 0.5;   // Risk per trade (% of balance)
input double InpTP_R         = 4.0;   // Take profit (R-multiple)
input int    InpMaxPerDay    = 3;     // Max trades per day this instrument
input double InpDailyStopPct = 4.5;  // Halt if daily loss > this % (FTMO limit = 5%)

input group "=== Strategy ==="
input ENUM_STRATEGY InpStrategy         = STRATEGY_BOTH; // Strategy selection
input int    InpEntryWindowH            = 3;             // Hours after signal to watch for breakout
input double InpMinIBRangePct           = 0.015;         // Min IB range as % of price
input double InpPBWickRatio             = 2.0;           // Pin bar: wick >= N x body
input double InpPBWickRangeFraction     = 0.5;           // Pin bar: wick >= N x full bar range

input group "=== News Filter ==="
input bool   InpNewsFilter  = true;   // Block trades near high-impact news
input int    InpNewsBefore  = 30;     // Minutes to block before event
input int    InpNewsAfter   = 30;     // Minutes to block after event

input group "=== EA Settings ==="
input int    InpMagic  = 202001;   // Magic number — set unique value per chart instance
input bool   InpAlerts = true;     // Terminal alerts on trade events

//── Objects ─────────────────────────────────────────────────────────
CTrade        Trade;
CPositionInfo PosInfo;

//── State ───────────────────────────────────────────────────────────
bool     g_armed           = false;   // Signal armed, watching for breakout
double   g_armed_h         = 0;      // High level — trigger long / SL for short
double   g_armed_l         = 0;      // Low level  — trigger short / SL for long
int      g_armed_dir       = 0;      // 0=both (IB), 1=long only (bull PB), -1=short only (bear PB)
datetime g_arm_time        = 0;      // Time armed (entry window reference)
string   g_pattern         = "";     // "IB" / "PB-BULL" / "PB-BEAR"
datetime g_last_h1         = 0;
datetime g_last_trade_time = 0;      // Cooldown: blocks double-entry on consecutive ticks
int      g_trades_today    = 0;
datetime g_today_start     = 0;

//+------------------------------------------------------------------+
//| Power hours per instrument (UTC)                                  |
//+------------------------------------------------------------------+
bool IsPowerHour(int hour_utc)
{
    string sym = _Symbol;

    if(StringFind(sym,"US30")>=0)
        return (hour_utc >= 13 && hour_utc <= 16);

    if(StringFind(sym,"US100")>=0 || StringFind(sym,"NAS")>=0 ||
       StringFind(sym,"US500")>=0 || StringFind(sym,"SPX")>=0)
        return (hour_utc >= 13 && hour_utc <= 16);

    if(StringFind(sym,"GER")>=0 || StringFind(sym,"DAX")>=0 || StringFind(sym,"DE4")>=0)
        return ((hour_utc >= 8 && hour_utc <= 10) || hour_utc == 13 || hour_utc == 14);

    if(StringFind(sym,"UK100")>=0 || StringFind(sym,"FTSE")>=0)
        return ((hour_utc >= 8 && hour_utc <= 10) || hour_utc == 13 || hour_utc == 14);

    if(StringFind(sym,"OIL")>=0 || StringFind(sym,"WTI")>=0 || StringFind(sym,"BRENT")>=0)
        return (hour_utc >= 13 && hour_utc <= 16);

    if(StringFind(sym,"NATGAS")>=0 || StringFind(sym,"NGas")>=0)
        return (hour_utc >= 13 && hour_utc <= 16);

    // FX pairs + Gold + USDJPY — London open + NY open overlap
    return ((hour_utc >= 8 && hour_utc <= 9) || (hour_utc >= 13 && hour_utc <= 15));
}

//+------------------------------------------------------------------+
//| Skip days — 0=Sun 1=Mon 2=Tue 3=Wed 4=Thu 5=Fri 6=Sat           |
//+------------------------------------------------------------------+
bool IsSkipDay(int dow)
{
    string sym = _Symbol;
    if(StringFind(sym,"US100")>=0 || StringFind(sym,"NAS")>=0 ||
       StringFind(sym,"US500")>=0 || StringFind(sym,"SPX")>=0 ||
       StringFind(sym,"US30")>=0)
        return (dow==0 || dow==1 || dow==5 || dow==6);
    return (dow==0 || dow==6);
}

//+------------------------------------------------------------------+
//| News filter                                                       |
//+------------------------------------------------------------------+
bool IsNewsNearby()
{
    if(!InpNewsFilter) return false;
    MqlCalendarValue values[];
    datetime from = TimeCurrent() - (datetime)(InpNewsBefore * 60);
    datetime to   = TimeCurrent() + (datetime)(InpNewsAfter  * 60);
    int count = CalendarValueHistory(values, from, to, NULL, NULL);
    if(count <= 0) return false;
    for(int i = 0; i < count; i++)
    {
        MqlCalendarEvent ev;
        if(!CalendarEventById(values[i].event_id, ev)) continue;
        if(ev.importance == CALENDAR_IMPORTANCE_HIGH)
        {
            Print("M1GOATV2 | News block: ", ev.name, " | ", TimeToString(values[i].time));
            return true;
        }
    }
    return false;
}

//+------------------------------------------------------------------+
//| Reset daily counter when date rolls over                          |
//+------------------------------------------------------------------+
void CheckDayReset()
{
    MqlDateTime dt;
    TimeToStruct(TimeCurrent(), dt);
    datetime today = TimeCurrent() - (dt.hour*3600 + dt.min*60 + dt.sec);
    if(today != g_today_start)
    {
        g_today_start  = today;
        g_trades_today = 0;
        g_armed        = false;
        Print("M1GOATV2 | Day reset | ", _Symbol);
    }
}

//+------------------------------------------------------------------+
//| Fixed-fractional lot size                                         |
//+------------------------------------------------------------------+
double CalcLots(double sl_distance)
{
    if(sl_distance <= 0) return 0;
    double balance    = AccountInfoDouble(ACCOUNT_BALANCE);
    double risk_amt   = balance * InpRiskPct / 100.0;
    double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
    double tick_size  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
    if(tick_size <= 0 || tick_value <= 0) return 0;
    double lots = risk_amt / ((sl_distance / tick_size) * tick_value);
    double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
    double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
    double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
    lots = MathFloor(lots / step) * step;
    return MathMax(vmin, MathMin(vmax, lots));
}

//+------------------------------------------------------------------+
//| Account daily P&L: closed deals + open floats                    |
//+------------------------------------------------------------------+
double GetDailyPnL()
{
    double pnl = 0;
    if(HistorySelect(g_today_start, TimeCurrent()))
    {
        for(int i = 0; i < HistoryDealsTotal(); i++)
        {
            ulong ticket = HistoryDealGetTicket(i);
            ENUM_DEAL_TYPE dt = (ENUM_DEAL_TYPE)HistoryDealGetInteger(ticket, DEAL_TYPE);
            if(dt == DEAL_TYPE_BALANCE || dt == DEAL_TYPE_CREDIT) continue;
            pnl += HistoryDealGetDouble(ticket, DEAL_PROFIT)
                 + HistoryDealGetDouble(ticket, DEAL_SWAP)
                 + HistoryDealGetDouble(ticket, DEAL_COMMISSION);
        }
    }
    for(int i = 0; i < PositionsTotal(); i++)
        if(PositionGetSymbol(i) != "") pnl += PositionGetDouble(POSITION_PROFIT);
    return pnl;
}

//+------------------------------------------------------------------+
//| True if this EA has an open position on this symbol               |
//+------------------------------------------------------------------+
bool HasOpenPosition()
{
    for(int i = 0; i < PositionsTotal(); i++)
    {
        PositionSelectByTicket(PositionGetTicket(i));
        if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
           (int)PositionGetInteger(POSITION_MAGIC) == InpMagic)
            return true;
    }
    return false;
}

//+------------------------------------------------------------------+
//| Execute trade — direction 1=long -1=short                        |
//+------------------------------------------------------------------+
void ExecuteTrade(int direction, double entry, double sl)
{
    g_armed = false;              // disarm immediately — any second call returns at CheckBreakout top
    g_last_trade_time = TimeCurrent();

    double sl_dist = MathAbs(entry - sl);
    double tp = (direction == 1) ? entry + sl_dist * InpTP_R
                                 : entry - sl_dist * InpTP_R;
    double lots = CalcLots(sl_dist);
    if(lots <= 0) { Print("M1GOATV2 | CalcLots=0 | ", _Symbol, " SL dist:", sl_dist); return; }

    string comment = "M1GOATV2-" + g_pattern;
    bool ok = (direction == 1) ? Trade.Buy (lots, _Symbol, 0, sl, tp, comment)
                               : Trade.Sell(lots, _Symbol, 0, sl, tp, comment);
    if(ok)
    {
        g_trades_today++;
        g_armed = false;
        string msg = StringFormat("M1GOATV2 | %s | %s | %s | Lots:%.2f SL:%.5f TP:%.5f | Day:%d/%d",
                                  _Symbol, g_pattern, (direction==1?"LONG":"SHORT"),
                                  lots, sl, tp, g_trades_today, InpMaxPerDay);
        Print(msg);
        if(InpAlerts) Alert(msg);
    }
    else
        Print("M1GOATV2 | Trade FAILED | ", Trade.ResultRetcodeDescription(),
              " Retcode:", Trade.ResultRetcode());
}

//+------------------------------------------------------------------+
//| Pre-checks shared by both IB and PB detection                    |
//+------------------------------------------------------------------+
bool PassesPreChecks(int dow, int hour_utc)
{
    if(IsSkipDay(dow))                 return false;
    if(!IsPowerHour(hour_utc))         return false;
    if(g_trades_today >= InpMaxPerDay) return false;
    double bal = AccountInfoDouble(ACCOUNT_BALANCE);
    if(bal > 0 && GetDailyPnL() / bal * 100.0 <= -InpDailyStopPct) return false;
    return true;
}

//+------------------------------------------------------------------+
//| Detect IB or PB on each new H1 bar                               |
//+------------------------------------------------------------------+
void CheckH1Bar()
{
    datetime current_h1 = iTime(_Symbol, PERIOD_H1, 0);
    if(current_h1 == g_last_h1) return;
    g_last_h1 = current_h1;

    // If existing signal is still within its entry window, let it play out
    if(g_armed && TimeCurrent() <= g_arm_time + (datetime)(InpEntryWindowH * 3600))
        return;

    g_armed = false;  // expired or no prior signal — scan for new one

    double h1 = iHigh (_Symbol, PERIOD_H1, 1);
    double l1 = iLow  (_Symbol, PERIOD_H1, 1);
    double h2 = iHigh (_Symbol, PERIOD_H1, 2);
    double l2 = iLow  (_Symbol, PERIOD_H1, 2);
    if(h1<=0 || l1<=0 || h2<=0 || l2<=0) return;

    int server_utc_offset = (int)(TimeCurrent() - TimeGMT());
    datetime bar_utc = iTime(_Symbol, PERIOD_H1, 1) - server_utc_offset;
    MqlDateTime dt;
    TimeToStruct(bar_utc, dt);
    if(!PassesPreChecks(dt.day_of_week, dt.hour)) return;

    // ── INSIDE BAR ──────────────────────────────────────────────────
    if(InpStrategy == STRATEGY_IB || InpStrategy == STRATEGY_BOTH)
    {
        if(h1 < h2 && l1 > l2)
        {
            double rng = h1 - l1;
            if(h1 > 0 && (rng / h1) >= (InpMinIBRangePct / 100.0))
            {
                g_armed     = true;
                g_armed_h   = h1;
                g_armed_l   = l1;
                g_armed_dir = 0;       // trade both directions
                g_arm_time  = current_h1;
                g_pattern   = "IB";
                Print(StringFormat("M1GOATV2 | IB ARMED | %s | H:%.5f L:%.5f Range:%.5f | Window:%dh",
                                   _Symbol, h1, l1, rng, InpEntryWindowH));
                return;  // IB takes priority — skip PB check on same bar
            }
        }
    }

    // ── PIN BAR ─────────────────────────────────────────────────────
    if(InpStrategy == STRATEGY_PB || InpStrategy == STRATEGY_BOTH)
    {
        double o1  = iOpen (_Symbol, PERIOD_H1, 1);
        double c1  = iClose(_Symbol, PERIOD_H1, 1);
        double rng = h1 - l1;
        if(rng > 0 && o1 > 0)
        {
            double body       = MathAbs(c1 - o1);
            double wick_lower = MathMin(o1,c1) - l1;
            double wick_upper = h1 - MathMax(o1,c1);

            bool bull_pin = (wick_lower >= InpPBWickRatio * body &&
                             wick_lower >= InpPBWickRangeFraction * rng);
            bool bear_pin = (wick_upper >= InpPBWickRatio * body &&
                             wick_upper >= InpPBWickRangeFraction * rng);

            if(bull_pin || bear_pin)
            {
                g_armed     = true;
                g_armed_h   = h1;
                g_armed_l   = l1;
                g_armed_dir = bull_pin ? 1 : -1;  // 1=long only, -1=short only
                g_arm_time  = current_h1;
                g_pattern   = bull_pin ? "PB-BULL" : "PB-BEAR";
                Print(StringFormat("M1GOATV2 | %s ARMED | %s | H:%.5f L:%.5f Range:%.5f | Window:%dh",
                                   g_pattern, _Symbol, h1, l1, rng, InpEntryWindowH));
            }
        }
    }
}

//+------------------------------------------------------------------+
//| Check for breakout entry on every tick                            |
//+------------------------------------------------------------------+
void CheckBreakout()
{
    if(!g_armed) return;
    if(TimeCurrent() - g_last_trade_time < 10) return;  // 10s cooldown prevents double-entry

    if(TimeCurrent() > g_arm_time + (datetime)(InpEntryWindowH * 3600))
    {
        Print("M1GOATV2 | Window expired | ", _Symbol, " | ", g_pattern);
        g_armed = false;
        return;
    }

    if(HasOpenPosition())              return;
    if(g_trades_today >= InpMaxPerDay) { g_armed = false; return; }

    double bal = AccountInfoDouble(ACCOUNT_BALANCE);
    if(bal > 0 && GetDailyPnL() / bal * 100.0 <= -InpDailyStopPct)
    { g_armed = false; return; }

    if(IsNewsNearby()) return;

    double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
    double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

    // Long: IB (dir 0) or bull pin (dir 1)
    if(ask > g_armed_h && g_armed_dir >= 0)
    {
        ExecuteTrade(1, ask, g_armed_l);
        return;
    }

    // Short: IB (dir 0) or bear pin (dir -1)
    if(bid < g_armed_l && g_armed_dir <= 0)
    {
        ExecuteTrade(-1, bid, g_armed_h);
        return;
    }
}

//+------------------------------------------------------------------+
//| Restore trade count from history after EA restart                 |
//+------------------------------------------------------------------+
void CountTodayTrades()
{
    g_trades_today = 0;
    if(!HistorySelect(g_today_start, TimeCurrent())) return;
    for(int i = 0; i < HistoryDealsTotal(); i++)
    {
        ulong ticket = HistoryDealGetTicket(i);
        if((int)HistoryDealGetInteger(ticket, DEAL_MAGIC) != InpMagic) continue;
        if(HistoryDealGetString(ticket, DEAL_SYMBOL) != _Symbol) continue;
        if(HistoryDealGetInteger(ticket, DEAL_ENTRY) == DEAL_ENTRY_IN)
            g_trades_today++;
    }
    Print("M1GOATV2 | Trades today: ", g_trades_today);
}

//+------------------------------------------------------------------+
//| Auto-detect broker order filling mode                             |
//+------------------------------------------------------------------+
void SetFillingMode()
{
    int mode = (int)SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
    if((mode & SYMBOL_FILLING_IOC) != 0)
        Trade.SetTypeFilling(ORDER_FILLING_IOC);
    else if((mode & SYMBOL_FILLING_FOK) != 0)
        Trade.SetTypeFilling(ORDER_FILLING_FOK);
    else
        Trade.SetTypeFilling(ORDER_FILLING_RETURN);
}

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit()
{
    if(_Period != PERIOD_M1)
    {
        Alert("M1GOATV2: Must run on M1 chart. Current: ", EnumToString(_Period));
        return INIT_FAILED;
    }

    Trade.SetExpertMagicNumber(InpMagic);
    Trade.SetDeviationInPoints(30);
    SetFillingMode();
    CheckDayReset();
    CountTodayTrades();

    string strat_str = (InpStrategy == STRATEGY_BOTH ? "IB+PB"    :
                        InpStrategy == STRATEGY_IB   ? "IB only"  : "PB only");

    Print(StringFormat("M1GOATV2 STARTED | %s | Balance:%.2f | Risk:%.2f%% | TP:%.1fR | %s | Magic:%d",
                       _Symbol, AccountInfoDouble(ACCOUNT_BALANCE),
                       InpRiskPct, InpTP_R, strat_str, InpMagic));
    if(InpAlerts)
        Alert("M1GOATV2 | ", _Symbol, " | ", strat_str, " | TP ", InpTP_R, "R | Risk ", InpRiskPct, "%");

    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnTick                                                            |
//+------------------------------------------------------------------+
void OnTick()
{
    CheckDayReset();
    CheckH1Bar();
    CheckBreakout();
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    Print("M1GOATV2 STOPPED | ", _Symbol, " | Reason:", reason);
}
//+------------------------------------------------------------------+
