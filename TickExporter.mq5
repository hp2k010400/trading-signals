//+------------------------------------------------------------------+
//| TickExporter.mq5 — forward-only raw tick collector                |
//|                                                                    |
//| Attach as an EA to ONE CHART PER INSTRUMENT. True OnTick() firing  |
//| requires one chart per symbol -- do NOT try to poll many symbols   |
//| from a single chart on a timer, that WILL silently miss ticks      |
//| between polls, defeating the point of collecting tick-level data.  |
//|                                                                    |
//| Rotates to a new CSV at each broker-server calendar day boundary.  |
//| Within a day, always APPENDS (never truncates) -- safe across EA   |
//| restarts, terminal restarts, and VPS reboots. At most the last     |
//| unflushed batch (<=500 ticks) is lost on a hard crash.             |
//|                                                                    |
//| Output: MQL5\Files\ticks_<SYMBOL>_<YYYYMMDD>.csv                   |
//| Columns: time,time_msc,bid,ask,last,volume,volume_real,            |
//|          spread_price,flags,flags_decoded,symbol                  |
//|                                                                    |
//| Deliberately does NOT compute session/region labels here -- that's |
//| a derived analysis-time concept (see ALPHA04_MARKET_CLOCK.md for   |
//| the broker-time session mapping) that can be improved later without|
//| needing to recompile/redeploy this EA. Raw data only, per the      |
//| "do not aggregate away the information before storage" directive.  |
//+------------------------------------------------------------------+
#property copyright "Tick Data Collection"
#property version   "1.00"
#property strict

input string FilePrefix = "";   // optional filename prefix; blank = use Symbol()

datetime g_current_day      = 0;
int      g_file_handle      = INVALID_HANDLE;
long     g_ticks_written_today = 0;
long     g_last_time_msc    = -1;
double   g_last_bid         = -1;
double   g_last_ask         = -1;

//+------------------------------------------------------------------+
string SanitizedSymbolName()
{
   string sym = (FilePrefix == "") ? Symbol() : FilePrefix;
   StringReplace(sym, ".", "_");
   return sym;
}

string DayFileName(datetime day)
{
   MqlDateTime dt;
   TimeToStruct(day, dt);
   return StringFormat("ticks_%s_%04d%02d%02d.csv", SanitizedSymbolName(), dt.year, dt.mon, dt.day);
}

string DecodeFlags(uint flags)
{
   string s = "";
   if((flags & TICK_FLAG_BID)    != 0) s += "BID|";
   if((flags & TICK_FLAG_ASK)    != 0) s += "ASK|";
   if((flags & TICK_FLAG_LAST)   != 0) s += "LAST|";
   if((flags & TICK_FLAG_VOLUME) != 0) s += "VOL|";
   if((flags & TICK_FLAG_BUY)    != 0) s += "BUY|";
   if((flags & TICK_FLAG_SELL)   != 0) s += "SELL|";
   if(s == "") s = "NONE";
   return s;
}

//+------------------------------------------------------------------+
void OpenDayFile(datetime nowTime)
{
   if(g_file_handle != INVALID_HANDLE)
   {
      FileFlush(g_file_handle);
      FileClose(g_file_handle);
      g_file_handle = INVALID_HANDLE;
   }

   MqlDateTime dt;
   TimeToStruct(nowTime, dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   g_current_day = StructToTime(dt);

   string fname = DayFileName(nowTime);
   bool file_exists = FileIsExist(fname);

   int fh = FileOpen(fname, FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_SHARE_READ, ',');
   if(fh == INVALID_HANDLE)
   {
      Print("ERROR: cannot open ", fname, " err=", GetLastError());
      return;
   }

   if(!file_exists)
   {
      FileWrite(fh, "time", "time_msc", "bid", "ask", "last", "volume", "volume_real",
                 "spread_price", "flags", "flags_decoded", "symbol");
   }
   else
   {
      FileSeek(fh, 0, SEEK_END);   // append -- never truncate a file that already has today's ticks
   }

   g_file_handle = fh;
   g_ticks_written_today = 0;
   Print("TickExporter: file ", file_exists ? "reopened (appending) " : "created ", fname);
}

void CheckDayRollover()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   datetime today = StructToTime(dt);
   if(today != g_current_day)
      OpenDayFile(TimeCurrent());
}

//+------------------------------------------------------------------+
int OnInit()
{
   OpenDayFile(TimeCurrent());
   EventSetTimer(1);   // safety net only, to catch day rollover on symbols that go quiet overnight
   Print("TickExporter started on ", Symbol());
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   if(g_file_handle != INVALID_HANDLE)
   {
      FileFlush(g_file_handle);
      FileClose(g_file_handle);
      g_file_handle = INVALID_HANDLE;
   }
   Print("TickExporter stopped on ", Symbol(), ". Ticks written today: ", g_ticks_written_today);
}

void OnTick()
{
   MqlTick tick;
   if(!SymbolInfoTick(Symbol(), tick))
      return;

   bool is_true_duplicate = (g_ticks_written_today > 0) &&
                             (tick.time_msc == g_last_time_msc) &&
                             (tick.bid == g_last_bid) &&
                             (tick.ask == g_last_ask);
   if(is_true_duplicate)
      return;

   g_last_time_msc = tick.time_msc;
   g_last_bid = tick.bid;
   g_last_ask = tick.ask;

   CheckDayRollover();
   if(g_file_handle == INVALID_HANDLE)
      return;

   double spread_price = tick.ask - tick.bid;
   FileWrite(g_file_handle,
      (long)tick.time,
      tick.time_msc,
      DoubleToString(tick.bid, _Digits),
      DoubleToString(tick.ask, _Digits),
      DoubleToString(tick.last, _Digits),
      (long)tick.volume,
      DoubleToString(tick.volume_real, 2),
      DoubleToString(spread_price, _Digits),
      (long)tick.flags,
      DecodeFlags(tick.flags),
      Symbol());

   g_ticks_written_today++;
   if(g_ticks_written_today % 500 == 0)
      FileFlush(g_file_handle);   // periodic flush: a hard crash loses at most ~500 ticks, not the session
}

void OnTimer()
{
   CheckDayRollover();
}
//+------------------------------------------------------------------+
