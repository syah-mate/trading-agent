# AI Trading Agent System — Task List for Copilot
> Stack: Python (Windows) + SvelteKit + MongoDB + OpenRouter + MetaTrader 5
> Timeframe: M15 | Strategy: Volume Profile + Liquidity Sweep

---

## PROJECT STRUCTURE

```
trading-agent/
├── python/                        # Python backend (wajib Windows)
│   ├── main.py                    # Entry point
│   ├── config.py                  # Semua konstanta & env vars
│   ├── agents/
│   │   ├── orchestrator.py        # Master agent loop
│   │   ├── volume_profile.py      # Sub-agent 1
│   │   ├── liquidity_sweep.py     # Sub-agent 2
│   │   ├── evaluator.py           # Confluence checker
│   │   ├── position_monitor.py    # Dynamic management agent
│   │   └── mt5_executor.py        # Order execution
│   ├── core/
│   │   ├── mt5_client.py          # MT5 connection wrapper
│   │   ├── openrouter_client.py   # OpenRouter API wrapper
│   │   └── mongo_client.py        # MongoDB connection
│   ├── backtest/
│   │   ├── engine.py              # Backtest loop engine
│   │   └── reporter.py            # Generate backtest result
│   └── api/
│       └── server.py              # FastAPI — expose endpoints ke SvelteKit
│
└── svelte/                        # SvelteKit dashboard
    ├── src/
    │   ├── routes/
    │   │   ├── +page.svelte           # Dashboard utama
    │   │   ├── trades/+page.svelte    # History trades
    │   │   ├── backtest/+page.svelte  # Backtest runner & hasil
    │   │   └── config/+page.svelte    # Konfigurasi agent
    │   ├── lib/
    │   │   ├── api.ts                 # Fetch ke FastAPI Python
    │   │   ├── mongo.ts               # Direct MongoDB (server-side)
    │   │   └── components/
    │   │       ├── EquityCurve.svelte
    │   │       ├── TradeCard.svelte
    │   │       ├── AgentStatus.svelte
    │   │       └── ReplayViewer.svelte
    └── ...
```

---

## PHASE 1 — Python Core Infrastructure

### TASK 1.1 — Setup project & dependencies
```
Buat file python/requirements.txt dengan dependencies:
- MetaTrader5
- pymongo
- fastapi
- uvicorn
- python-dotenv
- httpx (async HTTP untuk OpenRouter)
- asyncio

Buat python/.env.example:
- MT5_LOGIN=
- MT5_PASSWORD=
- MT5_SERVER=
- OPENROUTER_API_KEY=
- MONGO_URI=
- MONGO_DB_NAME=trading_agent
- SYMBOL=EURUSD
- TIMEFRAME=M15
- LOT_SIZE=0.1
- MAX_DAILY_LOSS=50.0
- CONFIDENCE_THRESHOLD=70
```

### TASK 1.2 — MT5 Client (`python/core/mt5_client.py`)
```
Buat class MT5Client dengan methods:

- connect() → bool
  Konek ke MT5 terminal dengan credentials dari .env
  Return True jika berhasil

- disconnect()
  Shutdown koneksi MT5

- get_candles(symbol, timeframe, count) → list[dict]
  Gunakan mt5.copy_rates_from_pos()
  Return list of {time, open, high, low, close, tick_volume}
  Timeframe default: mt5.TIMEFRAME_M15

- get_current_price(symbol) → dict
  Gunakan mt5.symbol_info_tick()
  Return {bid, ask, last}

- get_open_positions() → list[dict]
  Gunakan mt5.positions_get()
  Return list posisi aktif

- get_account_info() → dict
  Return {balance, equity, margin, free_margin}
```

### TASK 1.3 — OpenRouter Client (`python/core/openrouter_client.py`)
```
Buat class OpenRouterClient dengan methods:

- __init__()
  Load OPENROUTER_API_KEY dari env
  Base URL: https://openrouter.ai/api/v1/chat/completions
  Default model: google/gemini-2.0-flash-001 (cepat & murah)

- async chat(system_prompt: str, user_prompt: str) → str
  Kirim request ke OpenRouter
  Return response text

- async chat_json(system_prompt: str, user_prompt: str) → dict
  Sama seperti chat() tapi parse response sebagai JSON
  Handle error jika bukan valid JSON
  Retry 1x jika gagal parse
```

### TASK 1.4 — MongoDB Client (`python/core/mongo_client.py`)
```
Buat class MongoClient dengan collections:
- signals     → semua signal yang dievaluasi
- trades      → semua trade yang dieksekusi
- agent_logs  → log per cycle
- backtest_runs → hasil backtest

Methods:
- insert_signal(data: dict) → str (inserted_id)
- insert_trade(data: dict) → str
- insert_log(data: dict)
- update_trade(ticket: int, update: dict)
- get_trades(filter: dict, limit: int) → list
- get_signals(filter: dict, limit: int) → list
- insert_backtest_run(data: dict) → str
- update_backtest_run(run_id: str, update: dict)
```

---

## PHASE 2 — Trading Sub-Agents

### TASK 2.1 — Volume Profile Agent (`python/agents/volume_profile.py`)
```
Buat class VolumeProfileAgent dengan method:

- analyze(candles: list[dict]) → dict

Logic:
1. Dari candles (M15, minimal 100 candle), hitung distribusi volume per price level
   - Round price ke 4 desimal sebagai price level key
   - Akumulasi tick_volume per level
2. Temukan POC (Point of Control) = price level dengan volume tertinggi
3. Tentukan Value Area (70% dari total volume):
   - Mulai dari POC, expand ke atas dan bawah
   - Stop saat sudah cover 70% total volume
   - VAH = batas atas value area
   - VAL = batas bawah value area
4. Temukan HVN (High Volume Nodes) = levels dengan volume > 70% dari max
5. Temukan LVN (Low Volume Nodes) = levels dengan volume < 30% dari max

Return:
{
  "poc": float,
  "vah": float,
  "val": float,
  "hvn_zones": [float, ...],
  "lvn_zones": [float, ...],
  "total_volume": float,
  "candle_count": int
}
```

### TASK 2.2 — Liquidity Sweep Agent (`python/agents/liquidity_sweep.py`)
```
Buat class LiquiditySweepAgent dengan method:

- analyze(candles: list[dict]) → dict

Logic:
1. Ambil candles[-40:-20] sebagai "struktur lama"
   - swing_high = max(high) dari struktur lama
   - swing_low = min(low) dari struktur lama
2. Ambil candles[-20:] sebagai "candle recent"
3. Deteksi BULLISH SWEEP (setup BUY):
   - Ada candle yang low-nya break bawah swing_low
   - Candle tersebut atau candle berikutnya close DI ATAS swing_low
   - Artinya: liquidity di bawah swept, lalu harga balik naik
4. Deteksi BEARISH SWEEP (setup SELL):
   - Ada candle yang high-nya break atas swing_high
   - Candle tersebut atau berikutnya close DI BAWAH swing_high
   - Artinya: liquidity di atas swept, lalu harga balik turun
5. Hitung "candles_since_sweep" = berapa candle sejak sweep terjadi
   (sweep terlalu lama = sinyal basi, idealnya < 5 candle)

Return:
{
  "sweep_detected": bool,
  "direction": "BUY" | "SELL" | null,
  "sweep_level": float | null,
  "swing_high": float,
  "swing_low": float,
  "current_price": float,
  "candles_since_sweep": int | null,
  "sweep_candle_index": int | null
}
```

### TASK 2.3 — Evaluator Agent (`python/agents/evaluator.py`)
```
Buat class EvaluatorAgent dengan method:

- async evaluate(vp_result: dict, sweep_result: dict, candles: list, session: str) → dict

Logic:
1. Siapkan context untuk LLM:
   - VP data: POC, VAH, VAL, HVN zones
   - Sweep data: direction, sweep_level, candles_since_sweep
   - Current price
   - Session (London/NY/Asia/Other)
   - Last 5 candle OHLCV
   - ATR(14) dari candles terakhir

2. Buat system prompt:
   "Kamu adalah evaluator trading profesional yang ahli dalam Volume Profile dan Liquidity Sweep.
    Tugasmu mengevaluasi apakah ada confluence yang valid untuk entry.
    Respond HANYA dengan JSON, tidak ada teks lain."

3. Buat user prompt dengan semua context di atas, minta output:
{
  "is_valid": bool,
  "confidence": int (0-100),
  "direction": "BUY" | "SELL" | null,
  "entry_reason": str,
  "sl_price": float | null,
  "tp1_price": float | null,
  "tp2_price": float | null,
  "rejection_reason": str | null
}

4. SL logic yang diberikan ke LLM sebagai konteks:
   - BUY: SL di bawah sweep low - ATR*0.5
   - SELL: SL di atas sweep high + ATR*0.5
   - TP1: POC
   - TP2: VAH (untuk BUY) atau VAL (untuk SELL)

5. Filter tambahan sebelum kirim ke LLM:
   - Jika sweep_detected = False → langsung return is_valid: false, skip LLM
   - Jika candles_since_sweep > 5 → langsung return is_valid: false (sinyal basi)
   - Jika session = "Asia" dan bukan pair Asia → pertimbangkan skip

Return hasil dari LLM + tambahkan field:
- "evaluated_at": timestamp
- "session": session
- "atr": float
```

---

## PHASE 3 — Position Monitor & Executor

### TASK 3.1 — MT5 Executor (`python/agents/mt5_executor.py`)
```
Buat class MT5Executor dengan methods:

- open_position(signal: dict) → dict
  Gunakan mt5.order_send() dengan:
  - action: TRADE_ACTION_DEAL
  - symbol: dari config
  - volume: LOT_SIZE dari config
  - type: ORDER_TYPE_BUY atau SELL sesuai signal["direction"]
  - price: mt5.symbol_info_tick().ask (BUY) atau .bid (SELL)
  - sl: signal["sl_price"]
  - tp: signal["tp1_price"] (TP pertama)
  - comment: "AI_AGENT_" + timestamp
  Return: {ticket, entry_price, sl, tp, direction, opened_at}

- close_position(ticket: int, percentage: int = 100) → bool
  Jika percentage < 100: partial close dengan volume dikurangi
  Gunakan mt5.order_send() dengan TRADE_ACTION_DEAL arah berlawanan

- modify_sl(ticket: int, new_sl: float) → bool
  Gunakan mt5.order_send() dengan TRADE_ACTION_SLTP
  Update SL dari posisi aktif

- modify_tp(ticket: int, new_tp: float) → bool
  Sama seperti modify_sl tapi untuk TP
```

### TASK 3.2 — Position Monitor Agent (`python/agents/position_monitor.py`)
```
Buat class PositionMonitorAgent dengan method:

- async monitor(position: dict, candles: list, vp_result: dict, sweep_result: dict) → dict

Logic:
1. Hitung metrics dari posisi aktif:
   - floating_pnl: (current_price - entry) * direction * lot
   - current_rr: floating_pnl / initial_risk (dalam R)
   - candles_elapsed: berapa M15 candle sejak open
   - current_atr: ATR(14) terbaru

2. Siapkan context untuk LLM:
   - Semua data posisi (entry, sl, tp, direction, floating_pnl, current_rr)
   - VP terbaru (POC, VAH, VAL) — mungkin sudah bergeser dari saat entry
   - Sweep terbaru — apakah ada sweep berlawanan?
   - Last 5 candle OHLCV
   - Session saat ini
   - Berapa candle sudah berlalu

3. System prompt:
   "Kamu adalah manajer posisi trading profesional. Evaluasi apakah posisi aktif harus
    dihold, SL-nya dipindah, di-partial close, atau ditutup penuh.
    Berikan keputusan berdasarkan Price Action, Volume Profile, dan manajemen risiko.
    Respond HANYA dengan JSON."

4. Minta output dari LLM:
{
  "decision": "hold" | "move_sl" | "partial_close" | "close_all",
  "new_sl": float | null,
  "new_tp": float | null,
  "close_percentage": int | null,
  "reasoning": str  ← WAJIB, disimpan ke MongoDB untuk audit
}

5. Eksekusi keputusan via MT5Executor:
   - move_sl → executor.modify_sl()
   - partial_close → executor.close_position(percentage)
   - close_all → executor.close_position(100)
   - hold → tidak ada aksi

Return: keputusan LLM + hasil eksekusi + timestamp
```

---

## PHASE 4 — Orchestrator & Main Loop

### TASK 4.1 — Orchestrator (`python/agents/orchestrator.py`)
```
Buat class Orchestrator dengan method:

- async run_cycle()
  Satu siklus penuh (dipanggil tiap candle M15 baru):

  STEP 1: Ambil data
  - candles = mt5_client.get_candles(count=200)
  - current_price = mt5_client.get_current_price()
  - session = detect_session(current_time)  ← London/NY/Asia/Other

  STEP 2: Jalankan sub-agents PARALEL (asyncio.gather)
  - vp_result = await vp_agent.analyze(candles)
  - sweep_result = await ls_agent.analyze(candles)

  STEP 3: Log hasil sub-agents ke MongoDB (agent_logs collection)

  STEP 4: Cek posisi aktif
  - open_positions = mt5_client.get_open_positions()
  - Jika ada posisi aktif:
    → Jalankan position_monitor.monitor() untuk setiap posisi
    → Simpan keputusan monitoring ke MongoDB (update trade record)
    → SKIP evaluasi sinyal baru (tidak double entry)

  STEP 5: Jika tidak ada posisi aktif
  - eval_result = await evaluator.evaluate(vp_result, sweep_result, candles, session)
  - Simpan eval_result ke signals collection
  - Jika eval_result["is_valid"] = True dan confidence >= CONFIDENCE_THRESHOLD:
    → trade = executor.open_position(eval_result)
    → Simpan trade ke trades collection
    → Log ke agent_logs

- async start()
  Loop utama:
  - Konek MT5
  - Tunggu candle M15 baru (cek setiap 10 detik apakah menit berubah kelipatan 15)
  - Jalankan run_cycle()
  - Handle error: jika MT5 disconnect → reconnect, lanjut
  - Simpan status loop ke MongoDB untuk monitoring dashboard
```

### TASK 4.2 — Helper: Session Detection (`python/core/mt5_client.py`)
```
Tambahkan function detect_session(dt: datetime) → str:
- London: 07:00 - 16:00 UTC
- New York: 12:00 - 21:00 UTC
- London+NY overlap: 12:00 - 16:00 UTC (paling volatile, prioritas tinggi)
- Asia: 00:00 - 07:00 UTC
- Other: sisanya
```

### TASK 4.3 — Helper: ATR Calculator (`python/core/mt5_client.py`)
```
Tambahkan function calculate_atr(candles: list, period: int = 14) → float:
- True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
- ATR = average TR dari N candle terakhir
```

### TASK 4.4 — Config & Entry Point
```
Buat python/config.py:
- Load semua env vars dengan python-dotenv
- Ekspor sebagai konstanta: SYMBOL, LOT_SIZE, CONFIDENCE_THRESHOLD, dll

Buat python/main.py:
- Inisialisasi semua clients dan agents
- Panggil orchestrator.start()
- Handle KeyboardInterrupt dengan graceful shutdown
```

---

## PHASE 5 — FastAPI Server

### TASK 5.1 — API Server (`python/api/server.py`)
```
Buat FastAPI app dengan endpoints:

GET /status
Return: {
  "agent_running": bool,
  "last_cycle_at": timestamp,
  "open_positions": int,
  "account": {balance, equity, free_margin}
}

GET /trades?limit=50&skip=0
Return: list trade dari MongoDB, sort by opened_at DESC

GET /trades/{ticket}
Return: 1 trade lengkap + semua monitoring decisions

GET /signals?limit=50
Return: list signal evaluasi (valid & rejected)

GET /backtest/runs
Return: list semua backtest run

GET /backtest/runs/{run_id}
Return: 1 backtest run lengkap dengan semua trades

POST /backtest/start
Body: {symbol, timeframe, months_back, lot_size}
Trigger backtest engine secara async
Return: {run_id}

GET /backtest/runs/{run_id}/progress
Return: {status, progress_pct, trades_found, current_candle}

CORS: allow localhost:5173 (SvelteKit dev)
```

---

## PHASE 6 — Backtest Engine

### TASK 6.1 — Backtest Engine (`python/backtest/engine.py`)
```
Buat class BacktestEngine dengan method:

- async run(run_id: str, symbol: str, months_back: int = 6)

PENTING — Anti-lookahead rules:
- Load semua historical candles dari MT5 sekaligus
- Process SEQUENTIAL, candle by candle
- VP dihitung dari candles[0:i] saja (bukan full data)
- Tidak boleh ada akses ke candles[i+1] saat processing candle[i]

Logic per candle:
1. candles_so_far = all_candles[0:i]
2. Jika < 100 candle → skip (belum cukup data untuk VP)
3. Hitung vp_result dari candles_so_far
4. Hitung sweep_result dari candles_so_far
5. Jika ada virtual_position aktif:
   a. Panggil LLM untuk position monitoring
   b. Simpan keputusan + reasoning
   c. Eksekusi virtual (update virtual_position)
   d. Cek apakah SL/TP kena di candle ini
6. Jika tidak ada virtual_position:
   a. Evaluasi confluence via LLM
   b. Jika valid → buka virtual_position
   c. Simpan signal ke backtest record

Virtual Position:
{
  direction, entry_price, sl, tp1, tp2,
  lot_size, opened_at_candle_index,
  monitoring_log: [  ← append setiap candle
    {candle_index, decision, reasoning, price_at_decision}
  ]
}

Setelah loop selesai:
- Hitung statistik: win_rate, avg_rr, max_drawdown, profit_factor
- Simpan ke MongoDB backtest_runs collection
- Update status run_id menjadi "completed"

Rate limiting LLM calls:
- Panggil LLM untuk monitor HANYA setiap 3 candle (bukan tiap candle)
- Kecuali: ada sweep baru berlawanan → panggil LLM langsung
- Ini mencegah cost meledak di 17000+ candle
```

### TASK 6.2 — Backtest Reporter (`python/backtest/reporter.py`)
```
Buat function generate_stats(trades: list) → dict:
- total_trades: int
- winning_trades: int
- losing_trades: int
- win_rate: float (%)
- avg_win_rr: float
- avg_loss_rr: float
- profit_factor: float (gross_profit / gross_loss)
- max_drawdown: float (%)
- max_drawdown_duration: int (candles)
- equity_curve: list[{candle_index, equity}]  ← untuk chart di SvelteKit
- best_trade: dict
- worst_trade: dict
- trades_by_session: {London: int, NY: int, Asia: int, Overlap: int}
- trades_by_direction: {BUY: int, SELL: int}
```

---

## PHASE 7 — SvelteKit Dashboard

### TASK 7.1 — Setup SvelteKit project
```
Init SvelteKit project dengan:
- TypeScript
- Tailwind CSS
- Bun sebagai runtime

Buat lib/api.ts:
- Base URL ke FastAPI (default: http://localhost:8000)
- Function fetchStatus(), fetchTrades(), fetchSignals()
- Function startBacktest(params), fetchBacktestRun(runId)
- Semua menggunakan fetch() biasa (bukan realtime)
```

### TASK 7.2 — Dashboard Utama (`routes/+page.svelte`)
```
Tampilkan:
1. Agent Status Card
   - Running/Stopped indicator
   - Last cycle timestamp
   - Open positions count
   - Account: balance, equity, free margin

2. Recent Signals (last 10)
   - Timestamp, direction, confidence, valid/rejected
   - Rejection reason jika ada

3. Recent Trades (last 5)
   - Symbol, direction, entry, SL, TP
   - Status: open/closed
   - P&L jika sudah closed

Data di-fetch saat halaman dibuka (server-side load function)
Tambahkan tombol "Refresh" untuk fetch ulang manual
```

### TASK 7.3 — Trade History Page (`routes/trades/+page.svelte`)
```
Tampilkan tabel semua trades dengan kolom:
- Ticket, Symbol, Direction, Entry, SL, TP
- Opened At, Closed At, Duration
- Exit Reason (SL hit / TP hit / LLM close_all / partial)
- P&L (pips & currency)
- R:R Actual

Klik 1 trade → buka modal detail:
- Semua info trade
- Monitoring log: timeline keputusan LLM per candle
  Format: [candle timestamp] → decision | reasoning
  (Ini adalah "reasoning" yang disimpan dari position_monitor)

Filter: by direction, by date range, by result (win/loss)
```

### TASK 7.4 — Backtest Page (`routes/backtest/+page.svelte`)
```
Section 1 — Run Backtest
Form input:
- Symbol (default EURUSD)
- Months back (1-6, slider)
- Lot size
- Confidence threshold
Tombol "Run Backtest" → POST /backtest/start
Setelah submit: polling GET /backtest/runs/{run_id}/progress setiap 3 detik
Tampilkan progress bar + status text

Section 2 — Backtest Results (setelah selesai atau pilih run lama)
Statistics cards:
- Win Rate, Total Trades, Profit Factor
- Max Drawdown, Avg R:R Win, Avg R:R Loss

Equity Curve Chart:
- Line chart dari equity_curve data
- Gunakan library recharts atau chart.js via CDN

Trades Table (sama seperti trade history, tapi untuk virtual trades backtest):
- Bisa klik untuk lihat monitoring log + reasoning LLM per candle

Section 3 — Replay Mode (bonus, implementasi terakhir)
Pilih 1 trade dari backtest
Tampilkan candle by candle dengan:
- Posisi entry (garis horizontal)
- SL & TP saat ini (update jika LLM move_sl)
- Di sebelah kanan: reasoning LLM untuk candle tersebut
- Tombol Next Candle / Play Auto
```

### TASK 7.5 — Config Page (`routes/config/+page.svelte`)
```
Form untuk update config (simpan ke MongoDB, Python baca saat cycle):
- Symbol
- Lot size
- Confidence threshold (slider 50-100)
- Session filter (checkbox: London, NY, Asia, Overlap)
- Max daily loss ($)
- LLM model selector (dropdown OpenRouter models)

Tambahkan Start/Stop agent toggle
(POST ke FastAPI endpoint yang set flag di MongoDB,
 Python orchestrator cek flag ini setiap cycle)
```

---

## PHASE 8 — Integration & Polish

### TASK 8.1 — Error handling & logging
```
Di Python:
- Semua LLM call di-wrap try/except
- Jika LLM return JSON tidak valid: retry 1x, jika gagal lagi → skip cycle, log error
- Jika MT5 disconnect: reconnect loop setiap 30 detik, max 5x
- Jika order_send gagal: log error ke MongoDB, tidak retry otomatis

Di SvelteKit:
- Semua fetch ke FastAPI di-wrap try/catch
- Tampilkan error state yang jelas jika API tidak bisa diakses
- Loading skeleton saat fetch berlangsung
```

### TASK 8.2 — Environment & deployment notes
```
Buat README.md dengan instruksi:

REQUIREMENT:
- Python 3.10+ di Windows (MT5 library Windows only)
- MetaTrader 5 terminal terinstall & login
- MongoDB Atlas atau lokal
- OpenRouter API key
- Node.js + Bun untuk SvelteKit

CARA RUN:
1. cd python && pip install -r requirements.txt
2. Copy .env.example ke .env, isi semua values
3. python main.py  ← jalankan di Windows

4. cd svelte && bun install
5. bun dev  ← dashboard bisa di Windows atau komputer lain

CARA BACKTEST:
- Buka dashboard → halaman Backtest
- Isi parameter → Run
- Tunggu proses (bisa 10-30 menit untuk 6 bulan data karena LLM calls)
```

---

## URUTAN EKSEKUSI YANG DISARANKAN

```
[x] TASK 1.1 — Setup project structure & env
[x] TASK 1.2 — MT5Client (test koneksi dulu)
[x] TASK 1.3 — OpenRouterClient (test LLM call)
[x] TASK 1.4 — MongoClient
[ ] TASK 2.1 — VolumeProfileAgent
[ ] TASK 2.2 — LiquiditySweepAgent
[ ] TASK 4.2 — detect_session helper
[ ] TASK 4.3 — calculate_atr helper
[ ] TASK 2.3 — EvaluatorAgent (butuh OpenRouter + VP + LS)
[ ] TASK 3.1 — MT5Executor
[ ] TASK 3.2 — PositionMonitorAgent
[ ] TASK 4.1 — Orchestrator
[ ] TASK 4.4 — main.py entry point
[ ] TASK 5.1 — FastAPI server
[ ] TEST: jalankan live di akun DEMO MT5 dulu minimal 1 minggu
[ ] TASK 6.1 — Backtest Engine
[ ] TASK 6.2 — Backtest Reporter
[ ] TASK 7.1 — SvelteKit setup
[ ] TASK 7.2 — Dashboard page
[ ] TASK 7.3 — Trade history page
[ ] TASK 7.4 — Backtest page
[ ] TASK 7.5 — Config page
[ ] TASK 8.1 — Error handling
[ ] TASK 8.2 — README & deployment notes
[ ] TASK 7.4 (bonus) — Replay Mode
```

---

## CATATAN PENTING UNTUK COPILOT

1. **Semua LLM call harus async** — gunakan httpx.AsyncClient, bukan requests
2. **Backtest wajib sequential** — JANGAN gunakan parallel processing untuk loop candle, ini menyebabkan lookahead bias
3. **Reasoning dari LLM wajib disimpan** — field "reasoning" di setiap keputusan monitoring, ini krusial untuk replay mode
4. **MT5 library tidak thread-safe** — semua MT5 calls harus dari thread yang sama, gunakan asyncio.run_in_executor jika perlu
5. **LLM output selalu validasi** — jangan langsung percaya float dari LLM, validasi range SL/TP masuk akal sebelum kirim ke MT5
6. **Backtest LLM throttle** — panggil LLM monitor setiap 3 candle, BUKAN setiap candle, untuk hemat cost
7. **Demo account dulu** — pastikan sistem berjalan benar di MT5 demo minimal 1 minggu sebelum live
