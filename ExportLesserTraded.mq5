//+------------------------------------------------------------------+
//| ExportLesserTraded.mq5 -- exports M1 bars for the 7 lesser-traded |
//| instruments. ExportM1Data.mq5 silently skipped all 7 of these,   |
//| almost certainly because FTMO uses different exact ticker names  |
//| than assumed (e.g. "NATGAS.cash" may not exist on this broker).  |
//|                                                                    |
//| This script does NOT guess one fixed name per instrument. It      |
//| scans EVERY symbol the terminal knows about (not just Market      |
//| Watch) and matches by keyword, so it finds the real ticker        |
//| whatever suffix/format FTMO uses. It prints every candidate it    |
//| considered to the Journal, so if something still isn't found we   |
//| can see exactly what symbol names are actually available.         |
//|                                                                    |
//| Output filenames match what the Python backtest scripts expect,   |
//| regardless of the broker's raw ticker name.                       |
//+------------------------------------------------------------------+
#property script_show_inputs
#property copyright "Lesser-Traded Data Export"

input int BarsToExport = 300000;

struct Target
{
   string key;         // canonical name used in output filename
   string keywords[3]; // substrings to search for (case-insensitive), first non-empty ones used
};

string OutputFileName(string key)
{
   return key + "_M1_ftmo.csv";
}

bool ContainsKeyword(string haystack, string needle)
{
   string h = haystack;
   string n = needle;
   StringToUpper(h);
   StringToUpper(n);
   return (StringFind(h, n) >= 0);
}

void OnStart()
{
   Print("=== Lesser-Traded M1 Data Export ===");

   // canonical key -> keywords to search for among ALL broker symbol names
   string keys[7]      = {"NATGAS_cash", "UK100_cash", "AUDNZD", "AUDCAD", "AUDCHF", "USDCHF", "USDCAD"};
   string keyword0[7]  = {"NATGAS",      "UK100",      "AUDNZD", "AUDCAD", "AUDCHF", "USDCHF", "USDCAD"};
   string keyword1[7]  = {"NGAS",        "UKX",        "",       "",       "",       "",       ""};
   string keyword2[7]  = {"GAS",         "FTSE",       "",       "",       "",       "",       ""};

   int total = SymbolsTotal(false);   // ALL symbols the terminal knows, not just Market Watch
   Print("Terminal reports ", total, " total symbols available.");

   int exported = 0;

   for(int k = 0; k < 7; k++)
   {
      string matches[];
      int nmatch = 0;
      ArrayResize(matches, total);

      for(int i = 0; i < total; i++)
      {
         string symname = SymbolName(i, false);
         bool hit = ContainsKeyword(symname, keyword0[k]);
         if(!hit && keyword1[k] != "") hit = ContainsKeyword(symname, keyword1[k]);
         if(!hit && keyword2[k] != "") hit = ContainsKeyword(symname, keyword2[k]);
         if(hit)
         {
            matches[nmatch] = symname;
            nmatch++;
         }
      }

      if(nmatch == 0)
      {
         Print("NOT FOUND: ", keys[k], " -- no symbol name on this broker matched keywords [",
               keyword0[k], ", ", keyword1[k], ", ", keyword2[k], "]");
         continue;
      }

      Print(keys[k], ": found ", nmatch, " candidate symbol(s): ");
      for(int m = 0; m < nmatch; m++)
         Print("    candidate ", m, ": ", matches[m]);

      // use the first candidate found
      string sym = matches[0];

      if(!SymbolSelect(sym, true))
      {
         Print("SKIP: ", sym, " -- could not select symbol into Market Watch");
         continue;
      }

      MqlRates rates[];
      int copied = CopyRates(sym, PERIOD_M1, 0, BarsToExport, rates);

      if(copied <= 0)
      {
         Print("SKIP: ", sym, " -- selected OK but 0 bars returned (broker may need a moment to cache history, or try again after scrolling this symbol's M1 chart back in the terminal)");
         continue;
      }

      string fname = OutputFileName(keys[k]);
      int fh = FileOpen(fname, FILE_WRITE|FILE_CSV|FILE_ANSI, ',');
      if(fh == INVALID_HANDLE)
      {
         Print("ERROR: cannot write ", fname);
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

      Print("OK  ", sym, " -> ", fname, ": ", copied, " bars");
      exported++;
   }

   string path = TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\";
   Print("=== Done: ", exported, "/7 files exported ===");
   Print("Location: ", path);

   MessageBox(
      "Export complete: " + IntegerToString(exported) + "/7 files saved.\n\n" +
      "Check the Journal/Experts tab for full details on any NOT FOUND\n" +
      "or SKIP lines (missing data for some instruments).\n\n" +
      "Location:\n" + path,
      "Lesser-Traded Data Export", MB_OK|MB_ICONINFORMATION);
}
