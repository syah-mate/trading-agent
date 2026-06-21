"""
Jalankan: python debug_backtest.py
Ini simulate persis apa yang dilakukan backtest engine
tanpa FastAPI, supaya kita lihat error yang sebenarnya.
"""
import asyncio
import logging
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

async def main():
    print("=== Step 1: Import BacktestEngine ===")
    from backtest.engine import BacktestEngine
    print("OK")

    print("=== Step 2: Init engine ===")
    engine = BacktestEngine()
    print("OK")

    print("=== Step 3: Connect MT5 ===")
    ok = engine._mt5.connect()
    print(f"MT5 connect: {ok}")

    print("=== Step 4: Connect MongoDB ===")
    ok = engine._mongo.connect()
    print(f"Mongo connect: {ok}")

    print("=== Step 5: Load candles langsung ===")
    candles = engine._load_historical_candles("XAUUSDc", 1, "M15")
    print(f"Candles loaded: {len(candles)}")

    if len(candles) == 0:
        print("ERROR: Candles kosong! Backtest tidak bisa jalan.")
        return

    print("=== Step 6: Semua OK, run backtest dengan run_id dummy ===")
    # Insert dummy run ke mongo
    run_id = engine._mongo.insert_backtest_run({
        "symbol": "XAUUSDc",
        "timeframe": "M15",
        "months_back": 1,
        "lot_size": 0.01,
        "status": "starting",
    })
    print(f"run_id: {run_id}")

    print("=== Step 7: Jalankan engine.run() ===")
    await engine.run(run_id, "XAUUSDc", 1, "M15")
    print("=== SELESAI ===")

asyncio.run(main())