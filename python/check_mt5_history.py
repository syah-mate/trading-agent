from dotenv import load_dotenv
load_dotenv()
import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta

mt5.initialize()

symbol = "XAUUSDc"
mt5.symbol_select(symbol, True)

end = datetime.now(timezone.utc)
start = end - timedelta(days=30)

rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M15, start, end)

if rates is None:
    print("GAGAL:", mt5.last_error())
else:
    print(f"Berhasil: {len(rates)} candles")
    print("Candle pertama:", rates[0])
    print("Candle terakhir:", rates[-1])

mt5.shutdown()