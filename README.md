# AI Trading Agent System

> Stack: Python (Windows) + SvelteKit + MongoDB + OpenRouter + MetaTrader 5
> Timeframe: M15 | Strategy: Volume Profile + Liquidity Sweep

Sistem trading agent berbasis AI yang menganalisis market menggunakan **Volume Profile** dan **Liquidity Sweep**, mengevaluasi confluence sinyal via **LLM (OpenRouter)**, dan mengeksekusi trade di **MetaTrader 5**.

---

## 📋 Requirements

- **Python 3.10+** di Windows (MT5 library Windows-only)
- **MetaTrader 5** terminal terinstall & login ke akun (demo/live)
- **MongoDB** (Atlas atau lokal)
- **OpenRouter API key** (untuk LLM calls)
- **Node.js + Bun** (untuk SvelteKit dashboard)

---

## 🚀 Cara Run

### 1. Python Backend

```bash
cd python

# Install dependencies
pip install -r requirements.txt

# Copy & isi environment variables
cp .env.example .env
# Edit .env dengan kredensial MT5, OpenRouter, MongoDB

# Jalankan agent
python main.py
```

### 2. SvelteKit Dashboard

```bash
cd svelte

# Install dependencies
bun install

# Jalankan dev server
bun dev
# Dashboard tersedia di http://localhost:5173
```

### 3. API Server (FastAPI)

```bash
cd python
uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
# API tersedia di http://localhost:8000
# Docs: http://localhost:8000/docs
```

---

## 📊 Cara Backtest

1. Buka dashboard → halaman **Backtest**
2. Isi parameter (symbol, months back, lot size)
3. Klik **Run Backtest**
4. Tunggu proses (10-30 menit untuk 6 bulan data, tergantung jumlah LLM calls)
5. Lihat hasil: win rate, profit factor, equity curve

---

## 📁 Project Structure

```
trading-agent/
├── python/                        # Python backend
│   ├── main.py                    # Entry point
│   ├── config.py                  # Environment constants
│   ├── core/
│   │   ├── mt5_client.py          # MT5 connection wrapper
│   │   ├── openrouter_client.py   # OpenRouter API (async)
│   │   └── mongo_client.py        # MongoDB operations
│   ├── agents/
│   │   ├── orchestrator.py        # Master agent loop
│   │   ├── volume_profile.py      # Volume Profile analysis
│   │   ├── liquidity_sweep.py     # Liquidity Sweep detection
│   │   ├── evaluator.py           # LLM confluence evaluation
│   │   ├── position_monitor.py    # Dynamic position management
│   │   └── mt5_executor.py        # Order execution
│   ├── backtest/
│   │   ├── engine.py              # Backtest engine (anti-lookahead)
│   │   └── reporter.py            # Statistics generator
│   └── api/
│       └── server.py              # FastAPI REST endpoints
│
└── svelte/                        # SvelteKit dashboard
    └── src/
        ├── routes/
        │   ├── +page.svelte           # Dashboard utama
        │   ├── trades/+page.svelte    # Trade history
        │   ├── backtest/+page.svelte  # Backtest UI
        │   └── config/+page.svelte    # Configuration
        └── lib/
            └── api.ts                 # API client
```

---

## ⚙️ Environment Variables

| Variable | Description | Default |
|---|---|---|
| `MT5_LOGIN` | MT5 account login | — |
| `MT5_PASSWORD` | MT5 account password | — |
| `MT5_SERVER` | MT5 broker server | — |
| `OPENROUTER_API_KEY` | OpenRouter API key | — |
| `MONGO_URI` | MongoDB connection string | `mongodb://localhost:27017` |
| `MONGO_DB_NAME` | Database name | `trading_agent` |
| `SYMBOL` | Trading symbol | `XAUUSD` |
| `TIMEFRAME` | Candle timeframe | `M15` |
| `LOT_SIZE` | Trade volume | `0.01` |
| `CONFIDENCE_THRESHOLD` | Min confidence % untuk entry | `70` |
| `MAX_DAILY_LOSS` | Max daily loss ($) | `50.0` |

---

## ⚠️ Penting

1. **Demo account dulu** — pastikan sistem berjalan benar di MT5 demo minimal 1 minggu sebelum live
2. **MT5 tidak thread-safe** — semua MT5 calls harus dari thread yang sama
3. **Backtest sequential** — engine didesain anti-lookahead (candle by candle)
4. **LLM reasoning disimpan** — setiap keputusan monitor disimpan untuk audit & replay

---

## 🔧 Tech Stack

| Component | Technology |
|---|---|
| Backend | Python 3.10+ |
| Trading | MetaTrader5 Python API |
| LLM | OpenRouter (Gemini Flash, Claude, GPT) |
| Database | MongoDB |
| API | FastAPI + Uvicorn |
| Frontend | SvelteKit 5 + Tailwind CSS |
| Runtime | Bun |
