//+------------------------------------------------------------------+
//| ExportH1Data.mq5 — exports H1 bars for all 5 symbols to CSV     |
//| Run once as a Script in MT5, then upload CSVs to Codespaces      |
//+------------------------------------------------------------------+
#property script_show_inputs
#property copyright "6botV2 Data Export"

input int BarsToExport = 50000;  // 50k H1 bars = ~6 years per symbol

void OnStart()
{
   string symbols[] = {"EURUSD", "GBPUSD", "GER40.cash", "US100.cash", "US500.cash",
                       "UK100.cash", "XAUUSD", "USDJPY"};
   int exported = 0;

   Print("=== 6botV2 H1 Data Export ===");

   for(int s = 0; s < ArraySize(symbols); s++)
   {
      string sym = symbols[s];

      MqlRates rates[];
      int copied = CopyRates(sym, PERIOD_H1, 0, BarsToExport, rates);

      if(copied <= 0)
      {
         Print("SKIP: ", sym, " — no data (add to Market Watch first)");
         continue;
      }

      string fname = sym;
      StringReplace(fname, ".", "_");
      fname += "_H1.csv";

      int fh = FileOpen(fname, FILE_WRITE|FILE_CSV|FILE_ANSI, ',');
      if(fh == INVALID_HANDLE)
      {
         Print("ERROR: Cannot write ", fname, " — handle invalid");
         continue;
      }

      FileWrite(fh, "time", "open", "high", "low", "close");

      int dig = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      for(int i = 0; i < copied; i++)
      {
         FileWrite(fh,
            (long)rates[i].time,
            DoubleToString(rates[i].open,  dig),
            DoubleToString(rates[i].high,  dig),
            DoubleToString(rates[i].low,   dig),
            DoubleToString(rates[i].close, dig));
      }

      FileClose(fh);
      Print("OK  ", sym, ": ", copied, " bars  →  ", fname);
      exported++;
   }

   string path = TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\";
   Print("=== Done: ", exported, "/", ArraySize(symbols), " files ===");
   Print("Location: ", path);

   MessageBox(
      "Export complete!  " + IntegerToString(exported) + "/" +
      IntegerToString(ArraySize(symbols)) + " files saved.\n\n" +
      "Location:\n" + path + "\n\n" +
      "Upload all *_H1.csv files to your\nCodespaces trading-signals folder.",
      "6botV2 Data Export", MB_OK|MB_ICONINFORMATION);
}
