"""Smoke test for Volume Profile & Liquidity Sweep agents."""
import sys
sys.path.insert(0, '.')
import random
from datetime import datetime, timezone, timedelta
from agents.volume_profile import VolumeProfileAgent
from agents.liquidity_sweep import LiquiditySweepAgent

random.seed(42)
base = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
candles = []
price = 2650.0
for i in range(200):
    change = random.uniform(-5, 5)
    high = price + abs(change) + random.uniform(0, 2)
    low = price - abs(change) - random.uniform(0, 2)
    close = price + change
    vol = random.randint(50, 500)
    candles.append({
        'time': base + timedelta(minutes=15 * i),
        'open': price,
        'high': high,
        'low': low,
        'close': close,
        'tick_volume': vol,
        'spread': 5,
    })
    price = close

all_lows = [c['low'] for c in candles]
all_highs = [c['high'] for c in candles]
print(f'Generated {len(candles)} candles')
print(f'Price range: {min(all_lows):.2f} - {max(all_highs):.2f}')

# Test Volume Profile
vp = VolumeProfileAgent()
result = vp.analyze(candles)
print()
print('=== Volume Profile ===')
print(f'POC: {result["poc"]:.4f}')
print(f'VAH: {result["vah"]:.4f}')
print(f'VAL: {result["val"]:.4f}')
print(f'HVN Zones: {len(result["hvn_zones"])}')
print(f'LVN Zones: {len(result["lvn_zones"])}')
print(f'Total Volume: {result["total_volume"]:.0f}')

# Test Liquidity Sweep with manual sweep scenario
sweep_candles = [dict(c) for c in candles]
# Bullish sweep at index -5
sweep_candles[-5] = {
    **sweep_candles[-5],
    'low': sweep_candles[-30]['low'] - 5,
    'close': sweep_candles[-30]['low'] + 3,
}
# Bearish sweep at index -3
sweep_candles[-3] = {
    **sweep_candles[-3],
    'high': sweep_candles[-30]['high'] + 5,
    'close': sweep_candles[-30]['high'] - 3,
}

ls = LiquiditySweepAgent()
result2 = ls.analyze(sweep_candles)
print()
print('=== Liquidity Sweep ===')
print(f'Sweep Detected: {result2["sweep_detected"]}')
print(f'Direction: {result2["direction"]}')
sl = result2['sweep_level']
print(f'Sweep Level: {sl:.4f}' if sl else 'Sweep Level: None')
print(f'Swing High: {result2["swing_high"]:.4f}')
print(f'Swing Low: {result2["swing_low"]:.4f}')
print(f'Candles Since Sweep: {result2["candles_since_sweep"]}')
print(f'Current Price: {result2["current_price"]:.4f}')

print()
print('All agent tests passed!')
