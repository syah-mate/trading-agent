"""
Config — TASK 4.4
Load semua env vars dengan python-dotenv, ekspor sebagai konstanta.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# MT5 Credentials
# ---------------------------------------------------------------------------
MT5_LOGIN: int = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD: str = os.getenv("MT5_PASSWORD", "")
MT5_SERVER: str = os.getenv("MT5_SERVER", "")

# ---------------------------------------------------------------------------
# OpenRouter
# ---------------------------------------------------------------------------
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL: str = os.getenv(
    "OPENROUTER_MODEL", "google/gemini-2.0-flash-001"
)

# ---------------------------------------------------------------------------
# MongoDB
# ---------------------------------------------------------------------------
MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "trading_agent")

# ---------------------------------------------------------------------------
# Trading Parameters
# ---------------------------------------------------------------------------
SYMBOL: str = os.getenv("SYMBOL", "XAUUSD")
TIMEFRAME: str = os.getenv("TIMEFRAME", "M15")
LOT_SIZE: float = float(os.getenv("LOT_SIZE", "0.01"))
MAX_DAILY_LOSS: float = float(os.getenv("MAX_DAILY_LOSS", "50.0"))
CONFIDENCE_THRESHOLD: int = int(os.getenv("CONFIDENCE_THRESHOLD", "70"))

# ---------------------------------------------------------------------------
# Orchestrator Settings
# ---------------------------------------------------------------------------
CYCLE_INTERVAL_SECONDS: int = 10  # Cek candle baru setiap N detik
CANDLES_COUNT: int = 200  # Jumlah candle untuk analisis
