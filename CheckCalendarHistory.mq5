//+------------------------------------------------------------------+
//| CheckCalendarHistory.mq5 -- tests whether MT5's economic calendar |
//| actually has historical (not just live/upcoming) event data,     |
//| which is what a news-based backtest strategy would need.         |
//+------------------------------------------------------------------+
#property copyright "Calendar History Check"

void OnStart()
{
   datetime from = TimeCurrent() - (datetime)(3 * 365 * 24 * 60 * 60);   // 3 years back
   datetime to   = TimeCurrent();

   MqlCalendarValue values[];
   int count = CalendarValueHistory(values, from, to, NULL, NULL);

   string msg;
   if(count <= 0)
   {
      msg = "No historical calendar data returned.\nCount: " + IntegerToString(count) +
            "\n\nThis means the terminal's calendar database isn't populated with history --\n" +
            "a news-based backtest strategy would not be buildable with this data source.";
   }
   else
   {
      datetime earliest = values[0].time;
      datetime latest = values[0].time;
      int highImpactCount = 0;
      for(int i = 0; i < count; i++)
      {
         if(values[i].time < earliest) earliest = values[i].time;
         if(values[i].time > latest) latest = values[i].time;

         MqlCalendarEvent ev;
         if(CalendarEventById(values[i].event_id, ev))
            if(ev.importance == CALENDAR_IMPORTANCE_HIGH)
               highImpactCount++;
      }

      msg = StringFormat(
         "Total events found: %d\nHigh-impact events: %d\nEarliest: %s\nLatest: %s\n\n"
         "If 'Earliest' is genuinely ~3 years back, historical calendar data IS usable for backtesting.\n"
         "If 'Earliest' is only recent (last few days/weeks), the terminal only has live/upcoming data cached\n"
         "and would need to be left running to accumulate history, or historical data isn't available at all.",
         count, highImpactCount, TimeToString(earliest, TIME_DATE), TimeToString(latest, TIME_DATE));
   }

   Print(msg);
   MessageBox(msg, "Calendar History Check", MB_OK|MB_ICONINFORMATION);
}
