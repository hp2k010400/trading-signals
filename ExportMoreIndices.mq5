//+------------------------------------------------------------------+
//| ExportMoreIndices.mq5 -- keyword-search export for additional     |
//| equity indices, following the discovery that news-breakout works  |
//| decisively on indices (DAX PF 1.99, UK100 PF 2.19, US30 PF 1.25)  |
//| but not FX. More index instruments = more trade frequency and     |
//| monthly P&L for that same real edge.                              |
//|                                                                    |
//| Searches for: France 40 (CAC40), Japan 225 (Nikkei), Australia    |
//| 200, Europe 50 (STOXX), US2000 (Russell), Hong Kong 50, China     |
//| A50, Switzerland 20, Spain 35 -- common index offerings not       |
//| already in our set (DAX, NAS100, SP500, US30, UK100).            |
//|                                                                    |
//| Same keyword-search approach as ExportLesserTraded.mq5 -- doesn't |
//| assume exact broker ticker names, scans everything and matches.  |
//+------------------------------------------------------------------+
#property script_show_inputs
#property copyright "More Indices Export"

input int BarsToExport = 4000000;   // set high -- broker-side depth is the real limit, not this

string OutputFileName(string key) { return key + "_M1_ftmo.csv"; }

bool ContainsKeyword(string haystack, string needle)
{
   string h = haystack; string n = needle;
   StringToUpper(h); StringToUpper(n);
   return (StringFind(h, n) >= 0);
}

void OnStart()
{
   Print("=== More Indices M1 Data Export ===");

   string keys[9]     = {"FRA40",   "JP225",   "AUS200", "EU50",   "US2000",  "HK50", "CHINA50", "SWI20", "ESP35"};
   string keyword0[9] = {"FRA40",   "JP225",   "AUS200", "EU50",   "US2000",  "HK50", "CHINA50", "SWI20", "ESP35"};
   string keyword1[9] = {"FRANCE40","JAPAN225","AUS200", "EUSTX50","USA2000", "HK50", "CHINA50", "SWISS20","SPAIN35"};
   string keyword2[9] = {"CAC",     "NIKKEI",  "ASX200", "STOXX50","RUSSELL", "HKG50","CN50",   "SMI",   "IBEX"};

   int total = SymbolsTotal(false);
   Print("Terminal reports ", total, " total symbols available.");

   int exported = 0;

   for(int k = 0; k < 9; k++)
   {
      string matches[];
      int nmatch = 0;
      ArrayResize(matches, total);

      for(int i = 0; i < total; i++)
      {
         string symname = SymbolName(i, false);
         bool hit = ContainsKeyword(symname, keyword0[k]);
         if(!hit) hit = ContainsKeyword(symname, keyword1[k]);
         if(!hit) hit = ContainsKeyword(symname, keyword2[k]);
         if(hit) { matches[nmatch] = symname; nmatch++; }
      }

      if(nmatch == 0)
      {
         Print("NOT FOUND: ", keys[k], " -- no symbol matched keywords [",
               keyword0[k], ", ", keyword1[k], ", ", keyword2[k], "]");
         continue;
      }

      Print(keys[k], ": found ", nmatch, " candidate symbol(s):");
      for(int m = 0; m < nmatch; m++) Print("    candidate ", m, ": ", matches[m]);

      string sym = matches[0];
      if(!SymbolSelect(sym, true))
      {
         Print("SKIP: ", sym, " -- could not select symbol");
         continue;
      }

      MqlRates rates[];
      int copied = CopyRates(sym, PERIOD_M1, 0, BarsToExport, rates);
      if(copied <= 0)
      {
         Print("SKIP: ", sym, " -- 0 bars returned");
         continue;
      }

      string fname = OutputFileName(keys[k]);
      int fh = FileOpen(fname, FILE_WRITE|FILE_CSV|FILE_ANSI, ',');
      if(fh == INVALID_HANDLE) { Print("ERROR: cannot write ", fname); continue; }

      FileWrite(fh, "time", "open", "high", "low", "close");
      int dig = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      for(int i = 0; i < copied; i++)
      {
         FileWrite(fh, (long)rates[i].time,
            DoubleToString(rates[i].open,  dig), DoubleToString(rates[i].high,  dig),
            DoubleToString(rates[i].low,   dig), DoubleToString(rates[i].close, dig));
      }
      FileClose(fh);

      Print("OK  ", sym, " -> ", fname, ": ", copied, " bars");
      exported++;
   }

   string path = TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\";
   Print("=== Done: ", exported, "/9 files exported ===");
   Print("Location: ", path);

   MessageBox(
      "Export complete: " + IntegerToString(exported) + "/9 files saved.\n\n" +
      "Check the Journal tab for any NOT FOUND lines (indices this\n" +
      "broker doesn't offer) and candidate symbol names found.\n\nLocation:\n" + path,
      "More Indices Export", MB_OK|MB_ICONINFORMATION);
}
