"""
Config — TASK 4.4
Load semua env vars dengan python-dotenv, ekspor sebagai konstanta.
"""

import os
from dotenv import load_dotenv

load_dotenv(override=True)

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
# Default model — harus konsisten dengan DEFAULT_MODEL di core/openrouter_client.py
# Override via MongoDB config (llm_model) atau .env (OPENROUTER_MODEL)
OPENROUTER_MODEL: str = os.getenv(
    "OPENROUTER_MODEL", "google/gemini-2.5-flash-lite"
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
TIMEFRAME: str = os.getenv("TIMEFRAME", "M5")
LOT_SIZE: float = float(os.getenv("LOT_SIZE", "0.01"))
MAX_DAILY_LOSS: float = float(os.getenv("MAX_DAILY_LOSS", "50.0"))
CONFIDENCE_THRESHOLD: int = int(os.getenv("CONFIDENCE_THRESHOLD", "70"))

# ---------------------------------------------------------------------------
# Orchestrator Settings (v2.0)
# ---------------------------------------------------------------------------
CANDLES_COUNT: int = 200  # Jumlah candle untuk analisis
CANDLE_INTERVAL: int = 1  # M5 scalp: cek setiap candle baru

# ---------------------------------------------------------------------------
# M5 Scalp Strategy Settings (v3.0)
# ---------------------------------------------------------------------------
MAX_SL_PIPS: float = 10.0         # Maksimum SL = 10 pip untuk modal kecil
MIN_RR_RATIO: float = 0.8         # Minimum RR sebelum entry
MAX_TRADES_PER_SESSION: int = 2   # Maksimum 2 trade per sesi
MAX_DAILY_LOSS_PCT: float = 10.0  # Stop trading jika daily loss ≥ 10% modal

# ---------------------------------------------------------------------------
# Trading Parameters — dibaca dari MongoDB config, ini hanya default fallback
# ---------------------------------------------------------------------------

# Lot size (fixed)
LOT_FIX: float = float(os.getenv("LOT_FIX", "0.01"))

# TP config
# tp_mode: "fixed" = pakai tp_pips dari user, "ai" = AI yang tentukan
TP_MODE: str = os.getenv("TP_MODE", "fixed")   # "fixed" | "ai"
TP_PIPS: float = float(os.getenv("TP_PIPS", "10.0"))  # pip, hanya berlaku jika tp_mode=fixed

# SL config
# sl_mode: "fixed" = pakai sl_pips dari user, "ai" = AI yang tentukan
SL_MODE: str = os.getenv("SL_MODE", "ai")      # "fixed" | "ai"
SL_PIPS: float = float(os.getenv("SL_PIPS", "10.0"))  # pip, hanya berlaku jika sl_mode=fixed

# Konversi pip ke price distance untuk XAUUSDc
# 1 pip = $0.10 move → distance = pips * 0.10
XAUUSD_PIP_VALUE: float = 0.10
