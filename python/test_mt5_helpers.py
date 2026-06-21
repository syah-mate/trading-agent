"""Quick smoke test for mt5_client helpers (no MT5 required)."""
import sys
sys.path.insert(0, '.')
from core.mt5_client import detect_session, calculate_atr, _resolve_timeframe
from datetime import datetime, timezone, timedelta

# Test detect_session
tests = [
    (3, 'Asia'), (6, 'Asia'), (7, 'London'), (12, 'Overlap'),
    (15, 'Overlap'), (16, 'New York'), (20, 'New York'), (22, 'Other')
]
print('=== detect_session ===')
all_ok = True
for hour, expected in tests:
    dt = datetime(2026, 6, 21, hour, 0, tzinfo=timezone.utc)
    result = detect_session(dt)
    ok = result == expected
    if not ok:
        all_ok = False
    status = 'OK' if ok else f'FAIL (got {result})'
    print(f'  {hour:02d}:00 UTC -> {result} (expected {expected}) [{status}]')

# Test calculate_atr
print()
print('=== calculate_atr ===')
base = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
candles = []
for i in range(20):
    candles.append({
        'time': base + timedelta(hours=i),
        'open': 2000.0 + i,
        'high': 2002.0 + i,
        'low': 1998.0 + i,
        'close': 2001.0 + i,
        'tick_volume': 100,
        'spread': 5,
    })
atr = calculate_atr(candles, period=14)
print(f'  ATR(14) from {len(candles)} candles: {atr:.4f}')

# Edge case: too few candles
atr_short = calculate_atr(candles[:5], period=14)
print(f'  ATR(14) with only 5 candles: {atr_short}')

# Test _resolve_timeframe
print()
print('=== _resolve_timeframe ===')
import MetaTrader5 as mt5
print(f'  M15 -> {_resolve_timeframe("M15")} (expected {mt5.TIMEFRAME_M15})')
print(f'  h1  -> {_resolve_timeframe("h1")}  (expected {mt5.TIMEFRAME_H1})')
print(f'  D1  -> {_resolve_timeframe("D1")}  (expected {mt5.TIMEFRAME_D1})')
print()
print('All tests passed!' if all_ok else 'Some tests FAILED!')
