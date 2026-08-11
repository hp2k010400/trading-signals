//+------------------------------------------------------------------+
//| ExportM1Data.mq5 — exports M1 bars for all 8 NEWGOATv1 symbols   |
//| Run once as a Script in MT5, then upload CSVs to Codespaces      |
//| Output format matches what the Python backtest scripts expect:  |
//| time (unix seconds), open, high, low, close                     |
//+------------------------------------------------------------------+
#property script_show_inputs
#property copyright "NEWGOATv1 Data Export"

input int BarsToExport = 300000;  // MT5 will return however much M1 history it actually has cached

void OnStart()
{
   string symbols[] = {"GER40.cash", "US100.cash", "US500.cash", "US30.cash",
                        "EURUSD", "GBPUSD", "USDJPY", "XAUUSD"};
   int exported = 0;

   Print("=== NEWGOATv1 M1 Data Export ===");

   for(int s = 0; s < ArraySize(symbols); s++)
   {
      string sym = symbols[s];

      if(!SymbolSelect(sym, true))
      {
         Print("SKIP: ", sym, " — could not select symbol");
         continue;
      }

      MqlRates rates[];
      int copied = CopyRates(sym, PERIOD_M1, 0, BarsToExport, rates);

      if(copied <= 0)
      {
         Print("SKIP: ", sym, " — no data (add to Market Watch first)");
         continue;
      }

      string fname = sym;
      StringReplace(fname, ".", "_");
      fname += "_M1_ftmo.csv";

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
      Print("OK  ", sym, ": ", copied, " bars  ->  ", fname);
      exported++;
   }

   string path = TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\";
   Print("=== Done: ", exported, "/", ArraySize(symbols), " files ===");
   Print("Location: ", path);

   MessageBox(
      "Export complete!  " + IntegerToString(exported) + "/" +
      IntegerToString(ArraySize(symbols)) + " files saved.\n\n" +
      "Location:\n" + path + "\n\n" +
      "Upload all *_M1_ftmo.csv files to your\nCodespaces trading-signals folder.",
      "NEWGOATv1 Data Export", MB_OK|MB_ICONINFORMATION);
}
