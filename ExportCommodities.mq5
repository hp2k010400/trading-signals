//+------------------------------------------------------------------+
//| ExportCommodities.mq5 -- keyword-search export for Oil/Silver/    |
//| Copper, following the discovery that NATGAS (a commodity, not an  |
//| index) still showed a real signal (PF 1.41) in the news-breakout  |
//| strategy despite FX being decisively rejected. WTI/Brent Crude    |
//| Oil in particular has almost the exact same mechanism as NatGas   |
//| (a weekly EIA report -- Crude Oil Inventories -- plus general     |
//| news sensitivity), so it's the most natural next test.            |
//|                                                                    |
//| Searches for: WTI Crude Oil, Brent Crude Oil, Silver, Copper,     |
//| Platinum, Palladium, and the US Dollar Index (a basket, not a     |
//| single pair -- might behave more like an index than an efficient  |
//| single FX pair).                                                   |
//| Same keyword-search approach as ExportLesserTraded.mq5 -- doesn't |
//| assume exact broker ticker names.                                 |
//+------------------------------------------------------------------+
#property script_show_inputs
#property copyright "Commodities Export"

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
   Print("=== Commodities / DXY M1 Data Export ===");

   string keys[7]     = {"WTIOIL", "BRENTOIL", "SILVER",  "COPPER", "PLATINUM", "PALLADIUM", "USDINDEX"};
   string keyword0[7] = {"USOIL",  "UKOIL",    "XAGUSD",  "COPPER", "XPTUSD",   "XPDUSD",    "DXY"};
   string keyword1[7] = {"WTI",    "BRENT",    "SILVER",  "XCUUSD", "PLATINUM", "PALLADIUM", "USDX"};
   string keyword2[7] = {"CRUDE",  "UKOUSD",   "XAG",     "HG",     "XPT",      "XPD",       "USDOLLAR"};

   int total = SymbolsTotal(false);
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
   Print("=== Done: ", exported, "/7 files exported ===");
   Print("Location: ", path);

   MessageBox(
      "Export complete: " + IntegerToString(exported) + "/7 files saved.\n\n" +
      "Check the Journal tab for any NOT FOUND lines and candidate\n" +
      "symbol names found.\n\nLocation:\n" + path,
      "Commodities Export", MB_OK|MB_ICONINFORMATION);
}
