import time
from dotenv import load_dotenv
load_dotenv()
from core.mongo_client import MongoClient

m = MongoClient()
m.connect()

print("Watching backtest progress... (Ctrl+C to stop)")
while True:
    run = list(m._db['backtest_runs'].find().sort('created_at', -1).limit(1))
    if run:
        r = run[0]
        print(f"status={r.get('status')} progress={r.get('progress_pct')}% trades={r.get('trades_found', 0)} candle={r.get('current_candle', 0)} error={r.get('error', '')}")
    time.sleep(2)