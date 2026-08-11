//+------------------------------------------------------------------+
//| CheckUTCOffset.mq5 -- prints the exact broker server -> GMT      |
//| offset directly from MT5, no guessing from screenshots           |
//+------------------------------------------------------------------+
#property copyright "Offset Check"

void OnStart()
{
   datetime server = TimeCurrent();
   datetime gmt    = TimeGMT();
   int offsetSeconds = (int)(server - gmt);
   double offsetHours = offsetSeconds / 3600.0;

   string msg = StringFormat(
      "Server time: %s\nGMT time:    %s\nOffset:      %.2f hours (server - GMT)",
      TimeToString(server, TIME_DATE|TIME_SECONDS),
      TimeToString(gmt, TIME_DATE|TIME_SECONDS),
      offsetHours);

   Print(msg);
   MessageBox(msg, "UTC Offset Check", MB_OK|MB_ICONINFORMATION);
}
