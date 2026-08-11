//+------------------------------------------------------------------+
//| ExportNatGasCalendar.mq5 -- exports historical EIA Natural Gas   |
//| Storage report events (time, actual, forecast, previous) for a   |
//| news-driven NATGAS strategy.                                     |
//|                                                                    |
//| Finds the event by keyword match on the event name (not a fixed   |
//| event_id, which can differ per broker/terminal), same approach as |
//| ExportLesserTraded.mq5 used for symbol names.                     |
//|                                                                    |
//| IMPORTANT: calendar event times may NOT use the same timezone     |
//| convention as CopyRates() (which we confirmed is broker-server    |
//| time, UTC+3). Do not assume -- the first ~5 exported rows should  |
//| be sanity-checked against the known real release time (EIA        |
//| Natural Gas Storage: every Thursday, 10:30am US Eastern) before   |
//| this data is trusted for backtesting.                             |
//+------------------------------------------------------------------+
#property script_show_inputs
#property copyright "NatGas Calendar Export"

input string YearsBack = "8";   // how many years of calendar history to pull

void OnStart()
{
   int years = (int)StringToInteger(YearsBack);
   datetime from = TimeCurrent() - (datetime)(years * 365 * 24 * 60 * 60);
   datetime to   = TimeCurrent();

   MqlCalendarValue values[];
   int count = CalendarValueHistory(values, from, to, NULL, NULL);
   Print("Total historical calendar values fetched: ", count);

   if(count <= 0)
   {
      Print("ERROR: no calendar history returned.");
      return;
   }

   // Pass 1: find unique event_id(s) whose name matches "natural gas" / "gas storage"
   long matchedIds[];
   string matchedNames[];
   int nMatched = 0;
   ArrayResize(matchedIds, 20);
   ArrayResize(matchedNames, 20);

   long seenIds[];
   int nSeen = 0;
   ArrayResize(seenIds, count);

   for(int i = 0; i < count; i++)
   {
      long eid = values[i].event_id;
      bool already = false;
      for(int s = 0; s < nSeen; s++) if(seenIds[s] == eid) { already = true; break; }
      if(already) continue;
      seenIds[nSeen] = eid; nSeen++;

      MqlCalendarEvent ev;
      if(!CalendarEventById(eid, ev)) continue;

      string nmU = ev.name;
      StringToUpper(nmU);
      if(StringFind(nmU, "NATURAL GAS") >= 0 || StringFind(nmU, "GAS STORAGE") >= 0)
      {
         matchedIds[nMatched] = eid;
         matchedNames[nMatched] = ev.name;
         Print("MATCHED EVENT: id=", eid, "  name='", ev.name, "'  importance=", EnumToString(ev.importance),
               "  country_id=", ev.country_id);
         nMatched++;
      }
   }

   if(nMatched == 0)
   {
      Print("NOT FOUND: no calendar event matched 'natural gas' / 'gas storage' in its name.");
      Print("This broker's calendar may label it differently -- check the Journal above for");
      Print("any event names you recognize, or widen the keyword search.");
      return;
   }

   // Pass 2: export every historical value for the matched event id(s)
   string fname = "NATGAS_STORAGE_calendar.csv";
   int fh = FileOpen(fname, FILE_WRITE|FILE_CSV|FILE_ANSI, ',');
   if(fh == INVALID_HANDLE)
   {
      Print("ERROR: cannot write ", fname);
      return;
   }
   FileWrite(fh, "time", "event_id", "event_name", "actual", "forecast", "previous");

   int written = 0;
   for(int i = 0; i < count; i++)
   {
      bool isMatch = false;
      string nameForRow = "";
      for(int m = 0; m < nMatched; m++)
      {
         if(values[i].event_id == matchedIds[m]) { isMatch = true; nameForRow = matchedNames[m]; break; }
      }
      if(!isMatch) continue;

      double actual   = (values[i].actual_value   == LONG_MIN) ? 0 : (double)values[i].actual_value   / MathPow(10, values[i].event_value_digits);
      double forecast = (values[i].forecast_value == LONG_MIN) ? 0 : (double)values[i].forecast_value / MathPow(10, values[i].event_value_digits);
      double previous = (values[i].prev_value     == LONG_MIN) ? 0 : (double)values[i].prev_value     / MathPow(10, values[i].event_value_digits);

      FileWrite(fh, (long)values[i].time, (long)values[i].event_id, nameForRow, actual, forecast, previous);
      written++;
   }
   FileClose(fh);

   Print("=== Done: ", written, " rows written to ", fname, " ===");
   string path = TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\";
   Print("Location: ", path);

   // Print first 5 raw timestamps for manual sanity-check against the known
   // real release time (every Thursday, 10:30am US Eastern)
   Print("--- First 5 rows for timezone sanity-check ---");
   int shown = 0;
   for(int i = 0; i < count && shown < 5; i++)
   {
      bool isMatch = false;
      for(int m = 0; m < nMatched; m++) if(values[i].event_id == matchedIds[m]) { isMatch = true; break; }
      if(!isMatch) continue;
      Print("  ", TimeToString(values[i].time, TIME_DATE|TIME_MINUTES), "  (day of week check this is a Thursday)");
      shown++;
   }

   MessageBox(
      "Export complete: " + IntegerToString(written) + " event rows saved to\n" + fname + "\n\n" +
      "Check the Journal tab for the matched event name/importance and the\n" +
      "first 5 timestamps -- confirm they land on Thursdays, and work out\n" +
      "the UTC offset vs the known real release time (10:30am US Eastern).",
      "NatGas Calendar Export", MB_OK|MB_ICONINFORMATION);
}
