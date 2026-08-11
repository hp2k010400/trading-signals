//+------------------------------------------------------------------+
//| ExportHighImpactCalendar.mq5 -- exports ALL high/medium-impact   |
//| economic calendar events (not just NatGas), for a general        |
//| news-volatility-breakout strategy across the whole instrument    |
//| set. Each event is tagged with its country's currency, so the    |
//| Python side can map it to whichever of our instruments shares    |
//| that currency (USD releases -> EURUSD/GBPUSD/.../GOLD/indices,   |
//| AUD releases -> AUDNZD/AUDCAD/AUDCHF, etc.) -- one weekly report  |
//| alone isn't enough trade frequency, but ~15-20 high-impact        |
//| events/week across all currencies is.                            |
//|                                                                    |
//| The Natural Gas Storage event is always included regardless of   |
//| its importance tag (weekly EIA reports are sometimes tagged       |
//| Moderate, not High, but are a real NATGAS-specific vol driver).   |
//|                                                                    |
//| IMPORTANT: calendar event times may NOT use the same timezone     |
//| convention as CopyRates() (confirmed broker-server UTC+3). Do not |
//| assume -- the first 5 Natural Gas Storage timestamps are printed  |
//| so they can be sanity-checked against the known real release time |
//| (every Thursday, 10:30am US Eastern) before trusting this data.  |
//+------------------------------------------------------------------+
#property script_show_inputs
#property copyright "High-Impact Calendar Export"

input string YearsBack = "10";

bool NameMatchesGasStorage(string name)
{
   string nmU = name;
   StringToUpper(nmU);
   return (StringFind(nmU, "NATURAL GAS") >= 0 || StringFind(nmU, "GAS STORAGE") >= 0);
}

void OnStart()
{
   int years = (int)StringToInteger(YearsBack);
   datetime from = TimeCurrent() - (datetime)(years * 365 * 24 * 60 * 60);
   datetime to   = TimeCurrent();

   MqlCalendarValue values[];
   int count = CalendarValueHistory(values, from, to, NULL, NULL);
   Print("Total historical calendar values fetched: ", count);
   if(count <= 0) { Print("ERROR: no calendar history returned."); return; }

   // Pass 1: resolve each unique event_id once -> name, importance, currency
   long   seenIds[];      int nSeen = 0;      ArrayResize(seenIds, count);
   long   idList[];       string nameList[];  int impList[];   string currList[];
   int nEvents = 0;
   ArrayResize(idList, count); ArrayResize(nameList, count);
   ArrayResize(impList, count); ArrayResize(currList, count);

   for(int i = 0; i < count; i++)
   {
      long eid = values[i].event_id;
      bool already = false;
      for(int s = 0; s < nSeen; s++) if(seenIds[s] == eid) { already = true; break; }
      if(already) continue;
      seenIds[nSeen] = eid; nSeen++;

      MqlCalendarEvent ev;
      if(!CalendarEventById(eid, ev)) continue;

      bool isGas = NameMatchesGasStorage(ev.name);
      bool isHighOrMod = (ev.importance == CALENDAR_IMPORTANCE_HIGH || ev.importance == CALENDAR_IMPORTANCE_MODERATE);
      if(!isGas && !isHighOrMod) continue;   // skip low-importance noise (unless it's the gas report)

      string currency = "";
      MqlCalendarCountry country;
      if(CalendarCountryById(ev.country_id, country)) currency = country.currency;

      idList[nEvents] = eid;
      nameList[nEvents] = ev.name;
      impList[nEvents] = (int)ev.importance;
      currList[nEvents] = currency;
      nEvents++;
   }

   Print("Kept ", nEvents, " distinct qualifying events (High/Moderate importance, or Natural Gas Storage).");

   // Pass 2: export every historical value for the kept event ids
   string fname = "HighImpactCalendar.csv";
   int fh = FileOpen(fname, FILE_WRITE|FILE_CSV|FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) { Print("ERROR: cannot write ", fname); return; }
   FileWrite(fh, "time", "currency", "event_name", "importance", "actual", "forecast", "previous");

   int written = 0;
   int gasShown = 0;
   for(int i = 0; i < count; i++)
   {
      int idx = -1;
      for(int e = 0; e < nEvents; e++) if(idList[e] == values[i].event_id) { idx = e; break; }
      if(idx < 0) continue;

      double actual   = (values[i].actual_value   == LONG_MIN) ? 0 : (double)values[i].actual_value   / MathPow(10, values[i].event_value_digits);
      double forecast = (values[i].forecast_value == LONG_MIN) ? 0 : (double)values[i].forecast_value / MathPow(10, values[i].event_value_digits);
      double previous = (values[i].prev_value     == LONG_MIN) ? 0 : (double)values[i].prev_value     / MathPow(10, values[i].event_value_digits);

      FileWrite(fh, (long)values[i].time, currList[idx], nameList[idx], impList[idx], actual, forecast, previous);
      written++;

      if(NameMatchesGasStorage(nameList[idx]) && gasShown < 5)
      {
         Print("  GAS STORAGE sample: ", TimeToString(values[i].time, TIME_DATE|TIME_MINUTES),
               "  (confirm this lands on a Thursday, and work out offset vs 10:30am US Eastern)");
         gasShown++;
      }
   }
   FileClose(fh);

   Print("=== Done: ", written, " rows written to ", fname, " ===");
   string path = TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\";
   Print("Location: ", path);

   MessageBox(
      "Export complete: " + IntegerToString(written) + " event rows saved to\n" + fname + "\n\n" +
      "Check the Journal tab for the 5 'GAS STORAGE sample' timestamps --\n" +
      "confirm they land on Thursdays and work out the UTC offset vs the\n" +
      "known real release time (10:30am US Eastern) before we trust this\n" +
      "for backtesting.\n\nLocation:\n" + path,
      "High-Impact Calendar Export", MB_OK|MB_ICONINFORMATION);
}
