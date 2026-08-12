"""
tick_data_quality_validator.py

Phase 2/3 data-engineering deliverable (NOT strategy research). Scans
all collected tick files (ticks_<SYMBOL>_<YYYYMMDD>.csv, written by
TickExporter.mq5), runs the quality checks listed in the tick-data-
collection directive, and produces:

  - TICK_DATA_QUALITY_REPORT.md  (human-readable, per-symbol findings)
  - TICK_DATA_MANIFEST.csv       (machine-readable, one row per symbol)

Checks performed, per symbol:
  - missing ticks / gaps (weekend gaps classified separately from
    same-length-or-longer "possible closure" gaps during the week,
    which get flagged for manual review rather than auto-classified)
  - duplicate ticks (identical time_msc + bid + ask)
  - timestamp anomalies (non-monotonic time_msc)
  - spread anomalies (negative spread, extreme outliers, flatline runs)
  - abnormal price jumps (|log-return| far outside the recent rolling
    tick-to-tick distribution)
  - DST transition dates flagged for manual review (not auto-verdicted
    -- we don't yet have a verified per-instrument local-exchange-hours
    mapping at tick granularity, only the broker-server UTC+3 constant
    used throughout this research programme)
  - symbol-change note (different symbol name = a structurally
    different series -- documented via the manifest, not "fixed")

Run this periodically (e.g. weekly) against whatever ticks_*.csv files
have accumulated in the working directory -- it is safe to run with
zero, partial, or a full history of files.
"""
import pandas as pd
import numpy as np
import glob
import os
import re
import warnings
warnings.filterwarnings('ignore')

FILE_PATTERN = 'ticks_*_*.csv'
GAP_FLAG_MINUTES = 10          # gaps longer than this during a weekday get flagged
JUMP_SIGMA = 10                # |log-return| beyond this many rolling-std gets flagged as abnormal
FLATLINE_RUN_THRESHOLD = 50    # consecutive identical bid+ask ticks flagged as possible stale feed

DST_TRANSITIONS_2016_2030 = []
for year in range(2016, 2031):
    # US: 2nd Sunday March, 1st Sunday Nov. EU/UK: last Sunday March, last Sunday Oct.
    import calendar
    def nth_sunday(y, m, n):
        c = calendar.Calendar()
        sundays = [d for d in c.itermonthdates(y, m) if d.month == m and d.weekday() == 6]
        return sundays[n - 1]
    def last_sunday(y, m):
        c = calendar.Calendar()
        sundays = [d for d in c.itermonthdates(y, m) if d.month == m and d.weekday() == 6]
        return sundays[-1]
    DST_TRANSITIONS_2016_2030.append(('US_spring', nth_sunday(year, 3, 2)))
    DST_TRANSITIONS_2016_2030.append(('US_fall', nth_sunday(year, 11, 1)))
    DST_TRANSITIONS_2016_2030.append(('EU_UK_spring', last_sunday(year, 3)))
    DST_TRANSITIONS_2016_2030.append(('EU_UK_fall', last_sunday(year, 10)))


def find_files():
    files = glob.glob(FILE_PATTERN)
    parsed = []
    pat = re.compile(r'ticks_(.+)_(\d{8})\.csv$')
    for f in files:
        m = pat.match(os.path.basename(f))
        if not m:
            continue
        parsed.append({'file': f, 'symbol': m.group(1), 'date': m.group(2)})
    return pd.DataFrame(parsed)


def load_symbol_ticks(files_for_symbol):
    frames = []
    for f in sorted(files_for_symbol):
        try:
            df = pd.read_csv(f, dtype={'bid': 'float64', 'ask': 'float64', 'last': 'float64',
                                        'volume': 'int64', 'volume_real': 'float64',
                                        'spread_price': 'float64', 'flags': 'int64'})
            df['source_file'] = os.path.basename(f)
            frames.append(df)
        except Exception as e:
            print(f'  WARNING: could not read {f}: {e}')
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df['dt'] = pd.to_datetime(df['time_msc'], unit='ms', utc=True)
    df = df.sort_values('dt').reset_index(drop=True)
    return df


def classify_gap(gap_start, gap_end):
    """Weekend if the gap spans a full Saturday (broker-server date)."""
    d = gap_start.normalize()
    while d <= gap_end.normalize():
        if d.dayofweek == 5:  # Saturday
            return 'weekend'
        d += pd.Timedelta(days=1)
    return 'weekday'


def analyze_symbol(symbol, df):
    result = {'symbol': symbol}
    n = len(df)
    result['num_ticks'] = n
    result['start'] = df['dt'].iloc[0]
    result['end'] = df['dt'].iloc[-1]
    result['num_files'] = df['source_file'].nunique()
    result['num_days_with_data'] = df['dt'].dt.date.nunique()

    # duplicates
    dup_mask = df.duplicated(subset=['time_msc', 'bid', 'ask'], keep='first')
    result['duplicate_ticks'] = int(dup_mask.sum())

    # timestamp monotonicity
    non_monotonic = int((df['time_msc'].diff() < 0).sum())
    result['non_monotonic_count'] = non_monotonic

    # gaps
    deltas = df['dt'].diff()
    gap_mask = deltas > pd.Timedelta(minutes=GAP_FLAG_MINUTES)
    gap_idx = df.index[gap_mask]
    weekend_gaps = 0
    weekday_gaps = []
    typical_weekend_len = pd.Timedelta(hours=48)
    for i in gap_idx:
        gap_start = df['dt'].iloc[i - 1]
        gap_end = df['dt'].iloc[i]
        gap_len = gap_end - gap_start
        cls = classify_gap(gap_start, gap_end)
        if cls == 'weekend':
            weekend_gaps += 1
            if gap_len > typical_weekend_len * 1.5:
                weekday_gaps.append((gap_start, gap_end, gap_len, 'weekend, longer than typical -- review'))
        else:
            weekday_gaps.append((gap_start, gap_end, gap_len, 'weekday gap -- possible closure/feed drop'))
    result['weekend_gaps'] = weekend_gaps
    result['weekday_gaps'] = len(weekday_gaps)
    result['weekday_gap_details'] = weekday_gaps[:20]  # cap for report readability

    # spread anomalies
    neg_spread = int((df['spread_price'] < 0).sum())
    result['negative_spread_ticks'] = neg_spread
    spread_99_9 = df['spread_price'].quantile(0.999)
    extreme_spread = int((df['spread_price'] > spread_99_9 * 3).sum()) if spread_99_9 > 0 else 0
    result['extreme_spread_ticks'] = extreme_spread

    # flatline detection (consecutive identical bid+ask)
    same_as_prev = (df['bid'] == df['bid'].shift(1)) & (df['ask'] == df['ask'].shift(1))
    run_id = (~same_as_prev).cumsum()
    run_lengths = same_as_prev.groupby(run_id).sum()
    longest_flatline = int(run_lengths.max()) if len(run_lengths) else 0
    result['longest_flatline_run'] = longest_flatline

    # abnormal price jumps
    mid = (df['bid'] + df['ask']) / 2
    log_ret = np.log(mid / mid.shift(1)).replace([np.inf, -np.inf], np.nan)
    roll_std = log_ret.rolling(500, min_periods=50).std()
    z = (log_ret / roll_std).abs()
    abnormal_jumps = int((z > JUMP_SIGMA).sum())
    result['abnormal_jumps'] = abnormal_jumps
    result['max_abs_log_return'] = float(log_ret.abs().max()) if log_ret.notna().any() else np.nan

    # DST transitions falling within the collected range
    start_d, end_d = df['dt'].iloc[0].date(), df['dt'].iloc[-1].date()
    relevant_dst = [d for label, d in DST_TRANSITIONS_2016_2030 if start_d <= d <= end_d]
    result['dst_transitions_in_range'] = len(relevant_dst)

    return result


def write_report(results, files_df):
    lines = ['# Tick Data Quality Report', '',
             f'Generated from {len(files_df)} files across {files_df["symbol"].nunique() if len(files_df) else 0} symbols.',
             '']
    if not results:
        lines.append('No tick data files found yet (looking for `ticks_<SYMBOL>_<YYYYMMDD>.csv` in the working directory).')
        lines.append('This is expected before data collection begins -- run this script again once TickExporter.mq5 has been collecting for a while.')
        with open('TICK_DATA_QUALITY_REPORT.md', 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return

    for r in results:
        lines.append(f'## {r["symbol"]}')
        lines.append('')
        lines.append(f'- Range: {r["start"]} -> {r["end"]}  ({r["num_days_with_data"]} days with data, {r["num_files"]} daily files)')
        lines.append(f'- Total ticks: {r["num_ticks"]:,}')
        lines.append(f'- Duplicate ticks (identical time_msc+bid+ask): {r["duplicate_ticks"]}')
        lines.append(f'- Non-monotonic timestamps: {r["non_monotonic_count"]}')
        lines.append(f'- Weekend gaps (expected): {r["weekend_gaps"]}')
        lines.append(f'- Weekday/anomalous gaps (>{GAP_FLAG_MINUTES}min, needs review): {r["weekday_gaps"]}')
        if r['weekday_gap_details']:
            lines.append('  | start | end | length | note |')
            lines.append('  |---|---|---|---|')
            for gs, ge, gl, note in r['weekday_gap_details']:
                lines.append(f'  | {gs} | {ge} | {gl} | {note} |')
        lines.append(f'- Negative-spread ticks (should be 0, broker feed error if not): {r["negative_spread_ticks"]}')
        lines.append(f'- Extreme spread outliers (>3x the 99.9th pctile): {r["extreme_spread_ticks"]}')
        lines.append(f'- Longest flatline run (identical consecutive bid+ask): {r["longest_flatline_run"]}'
                      + (' -- ABOVE THRESHOLD, possible stale feed period, review' if r['longest_flatline_run'] > FLATLINE_RUN_THRESHOLD else ''))
        lines.append(f'- Abnormal price jumps (|log-ret| > {JUMP_SIGMA} sigma of rolling local std): {r["abnormal_jumps"]}'
                      + (f' (max |log-ret| seen: {r["max_abs_log_return"]:.5f})' if not np.isnan(r['max_abs_log_return']) else ''))
        lines.append(f'- DST transition dates within collected range (manual review, not auto-verdicted): {r["dst_transitions_in_range"]}')
        lines.append('')

    lines.append('## Notes')
    lines.append('- Symbol/contract changes are not auto-detected here -- a renamed symbol shows up as a')
    lines.append('  structurally separate series in the manifest (different `symbol` value), not something')
    lines.append('  this validator merges or "fixes." Treat any such split as a manual decision point.')
    lines.append('- Weekday/anomalous gaps and DST transition dates are flagged for manual review, not')
    lines.append('  auto-classified as errors -- some may be legitimate (public holidays, broker maintenance')
    lines.append('  windows) rather than data quality problems.')

    with open('TICK_DATA_QUALITY_REPORT.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def write_manifest(results):
    rows = []
    for r in results:
        rows.append({
            'symbol': r['symbol'],
            'start_date': r['start'].date() if not pd.isna(r['start']) else '',
            'end_date': r['end'].date() if not pd.isna(r['end']) else '',
            'num_ticks': r['num_ticks'],
            'num_days_with_data': r['num_days_with_data'],
            'num_files': r['num_files'],
            'weekend_gaps': r['weekend_gaps'],
            'weekday_anomalous_gaps': r['weekday_gaps'],
            'duplicate_ticks': r['duplicate_ticks'],
            'non_monotonic_timestamps': r['non_monotonic_count'],
            'negative_spread_ticks': r['negative_spread_ticks'],
            'extreme_spread_ticks': r['extreme_spread_ticks'],
            'longest_flatline_run': r['longest_flatline_run'],
            'abnormal_jumps': r['abnormal_jumps'],
        })
    pd.DataFrame(rows).to_csv('TICK_DATA_MANIFEST.csv', index=False)


def main():
    files_df = find_files()
    print(f'Found {len(files_df)} tick files.')
    if len(files_df) == 0:
        write_report([], files_df)
        pd.DataFrame(columns=['symbol', 'start_date', 'end_date', 'num_ticks', 'num_days_with_data',
                               'num_files', 'weekend_gaps', 'weekday_anomalous_gaps', 'duplicate_ticks',
                               'non_monotonic_timestamps', 'negative_spread_ticks', 'extreme_spread_ticks',
                               'longest_flatline_run', 'abnormal_jumps']).to_csv('TICK_DATA_MANIFEST.csv', index=False)
        print('No tick files found. Wrote placeholder TICK_DATA_QUALITY_REPORT.md and empty TICK_DATA_MANIFEST.csv.')
        return

    results = []
    for symbol, g in files_df.groupby('symbol'):
        print(f'  Processing {symbol}: {len(g)} files...')
        df = load_symbol_ticks(g['file'].tolist())
        if df is None or len(df) == 0:
            print(f'    (no readable data)')
            continue
        r = analyze_symbol(symbol, df)
        results.append(r)
        print(f'    {r["num_ticks"]:,} ticks, {r["weekday_gaps"]} anomalous gaps, '
              f'{r["negative_spread_ticks"]} negative-spread ticks, {r["abnormal_jumps"]} abnormal jumps')

    write_report(results, files_df)
    write_manifest(results)
    print('\nWrote TICK_DATA_QUALITY_REPORT.md and TICK_DATA_MANIFEST.csv')


if __name__ == '__main__':
    main()
