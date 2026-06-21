# TASKS_FIX.md — Fix & Completion Tasks
> Lanjutan dari TASKS.md — berdasarkan hasil code review repo
> Semua fix harus dikerjakan secara berurutan

---

## CATATAN PENTING SEBELUM MULAI

**File `svelte/src/lib/api.ts`** — meskipun project dipilih JavaScript,
SvelteKit dengan `allowJs: true` di jsconfig.json tetap bisa handle `.ts` file.
**Jangan rename**, biarkan tetap `api.ts`. Vite + SvelteKit akan handle transpile otomatis.

---

## FIX 1 — Tambah endpoint `/config` di FastAPI

**File:** `python/api/server.py`

Tambahkan Pydantic model dan 2 endpoint baru di bawah endpoint `/backtest/runs/{run_id}/progress` yang sudah ada:

```
Tambahkan Pydantic model ConfigUpdateRequest:
{
  symbol: str (optional, default None)
  lot_size: float (optional, default None)
  confidence_threshold: int (optional, default None)
  sessions: dict (optional, default None) — contoh: {"London": true, "NewYork": true}
  max_daily_loss: float (optional, default None)
  llm_model: str (optional, default None)
}
Semua field optional menggunakan typing.Optional dengan default None.

Tambahkan GET /config:
- Ambil config terbaru dari MongoDB collection "config"
- Query: db["config"].find_one({"_id": "agent_config"})
- Jika tidak ada dokumen → return default values:
  {
    "symbol": "XAUUSD",
    "lot_size": 0.01,
    "confidence_threshold": 70,
    "sessions": {"London": true, "NewYork": true, "Overlap": true, "Asia": false},
    "max_daily_loss": 50.0,
    "llm_model": "google/gemini-2.0-flash-001"
  }
- Return hasil sebagai dict (serialize dengan _serialize_doc yang sudah ada)

Tambahkan POST /config:
- Body: ConfigUpdateRequest
- Ambil hanya field yang tidak None dari request
- Upsert ke MongoDB:
  db["config"].update_one(
    {"_id": "agent_config"},
    {"$set": {field: value, "updated_at": datetime.now(timezone.utc)}},
    upsert=True
  )
- Return: {"success": True, "updated_fields": [list field yang diupdate]}

JANGAN ubah kode lain di server.py, hanya tambahkan di bagian bawah sebelum helper function _serialize_doc.
```

---

## FIX 2 — Tambah method config di MongoClient

**File:** `python/core/mongo_client.py`

Tambahkan 2 method baru di class MongoClient, letakkan setelah method `get_backtest_run`:

```
Tambahkan property _config:
  @property
  def _config(self) -> Collection:
      if self._db is None:
          raise RuntimeError("MongoClient belum connect()")
      return self._db["config"]

Tambahkan method get_config(self) -> dict:
  - Query: self._config.find_one({"_id": "agent_config"})
  - Jika None → return default config dict (sama seperti di FIX 1)
  - Return hasil query sebagai dict

Tambahkan method upsert_config(self, updates: dict[str, Any]) -> bool:
  - update_one({"_id": "agent_config"}, {"$set": updates}, upsert=True)
  - Return True jika berhasil
  - Wrap dengan try/except PyMongoError, return False jika error
```

---

## FIX 3 — Update Config page di SvelteKit

**File:** `svelte/src/routes/config/+page.svelte`

Ganti SELURUH isi file dengan implementasi baru:

```
Gunakan import { fetchConfig, updateConfig } dari '$lib/api'

State yang diperlukan (gunakan Svelte 5 $state runes):
- symbol: string = 'XAUUSD'
- lotSize: number = 0.01
- confidenceThreshold: number = 70
- sessions: object = { London: true, NewYork: true, Overlap: true, Asia: false }
- maxDailyLoss: number = 50
- llmModel: string = 'google/gemini-2.0-flash-001'
- loading: boolean = true
- saving: boolean = false
- message: string = ''
- messageType: string = '' (nilai: 'success' | 'error')

$effect untuk load config saat halaman dibuka:
- Panggil fetchConfig()
- Map response ke state variables
- Set loading = false
- Jika error: tampilkan pesan error, set loading = false

Function saveConfig():
- Set saving = true
- Buat object config dari semua state
- Panggil updateConfig(config)
- Jika berhasil: messageType = 'success', message = '✅ Config berhasil disimpan'
- Jika error: messageType = 'error', message = '❌ Gagal menyimpan: ' + error.message
- Set saving = false
- setTimeout 3 detik → clear message

HAPUS semua kode yang menggunakan localStorage.

Template HTML: gunakan struktur yang sama seperti sebelumnya
(symbol input, lot size input, confidence slider, session checkboxes,
max daily loss, llm model dropdown, save button)

Tambahkan loading skeleton saat loading = true:
- Tampilkan div dengan class "animate-pulse" dan beberapa gray bars
- Sembunyikan form saat loading

Tombol Save:
- disabled saat saving = true
- Text: saving ? '💾 Menyimpan...' : '💾 Save Configuration'

Daftar model LLM untuk dropdown (sama seperti sebelumnya):
- google/gemini-2.0-flash-001
- google/gemini-2.5-pro-preview
- anthropic/claude-3-haiku
- meta-llama/llama-3-8b-instruct
- openai/gpt-4o-mini

Di bagian bawah halaman, tambahkan section "Current Config from API"
yang menampilkan raw JSON config yang diload (collapsible, toggle dengan button)
```

---

## FIX 4 — Tambah Equity Curve Chart di Backtest Page

**File:** `svelte/src/routes/backtest/+page.svelte`

Tambahkan komponen chart equity curve menggunakan SVG native (tidak perlu install library chart):

```
Tambahkan state baru:
- selectedRun: object | null = null (untuk menampilkan detail run)
- showDetail: boolean = false

Tambahkan function selectRun(run):
- Set selectedRun = run
- Set showDetail = true

Tambahkan function closeDetail():
- Set showDetail = false
- Set selectedRun = null

Tambahkan function drawEquityCurve(equityCurve, initialBalance):
- Input: array of {candle_index, equity, event}
- Output: SVG path string untuk line chart

  Algorithm:
  1. Filter equity_curve: ambil 1 data point per 50 candle (downsampling)
     untuk performa. Selalu include first dan last.
  2. Tentukan minEquity dan maxEquity dari data
  3. Padding: minEquity - 5%, maxEquity + 5%
  4. Map setiap point ke koordinat SVG (viewBox 600x200):
     x = (index / total) * 580 + 10
     y = 190 - ((equity - minEquity) / range) * 180
  5. Build SVG polyline points string: "x1,y1 x2,y2 ..."
  6. Return object: { points, minEquity, maxEquity, initialBalance }

Di section "Past Runs", di setiap run card:
- Tambahkan tombol "📊 View Detail" di pojok kanan
- Onclick: selectRun(run)

Tambahkan section "Run Detail" yang muncul saat showDetail = true:
  Tampilkan:
  1. Header: symbol, months_back, status, tanggal
  2. Stats grid (sama seperti yang sudah ada di run card)
  3. Equity Curve Chart:
     <svg viewBox="0 0 600 220" class="w-full" style="background: #111827; border-radius: 8px;">
       <!-- Garis horizontal baseline (initial balance) -->
       <line x1="10" y1={yBaseline} x2="590" y2={yBaseline} stroke="#374151" stroke-width="1" stroke-dasharray="4 2" />
       <!-- Label min/max/initial di kiri -->
       <text x="5" y="15" fill="#6B7280" font-size="9">{maxEquity.toFixed(0)}</text>
       <text x="5" y="195" fill="#6B7280" font-size="9">{minEquity.toFixed(0)}</text>
       <!-- Equity line: warna hijau jika profit, merah jika loss dari initial -->
       <polyline
         points={chartData.points}
         fill="none"
         stroke={finalEquity >= initialBalance ? '#10B981' : '#EF4444'}
         stroke-width="1.5"
       />
     </svg>
  4. Breakdown by session: bar chart sederhana menggunakan div width percentage
  5. Breakdown by direction: BUY vs SELL count
  6. List 5 best trades dan 5 worst trades
  7. Tombol "Close" untuk kembali

Styling: gunakan Tailwind classes yang sudah ada di project (bg-gray-900, border-gray-800, dll)
```

---

## FIX 5 — Tambah Date Range Filter di Trades Page

**File:** `svelte/src/routes/trades/+page.svelte`

Tambahkan filter tanggal di section Filters yang sudah ada:

```
Tambahkan 2 state baru:
- filterDateFrom: string = '' (format: YYYY-MM-DD, dari <input type="date">)
- filterDateTo: string = '' (format: YYYY-MM-DD)

Update $derived filteredTrades untuk include date filter:
  Tambahkan kondisi:
  - Jika filterDateFrom tidak kosong:
    opened_at dari trade harus >= new Date(filterDateFrom)
  - Jika filterDateTo tidak kosong:
    opened_at dari trade harus <= new Date(filterDateTo + 'T23:59:59')
  Gunakan: new Date(trade.opened_at) untuk compare

Di template HTML, di dalam div filter yang sudah ada, tambahkan setelah filter select:
  <div class="flex items-center gap-2">
    <label class="text-xs text-gray-500">From:</label>
    <input
      type="date"
      bind:value={filterDateFrom}
      class="bg-gray-900 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-gray-300"
    />
  </div>
  <div class="flex items-center gap-2">
    <label class="text-xs text-gray-500">To:</label>
    <input
      type="date"
      bind:value={filterDateTo}
      class="bg-gray-900 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-gray-300"
    />
  </div>
  <button
    onclick={() => { filterDateFrom = ''; filterDateTo = ''; filterDirection = ''; filterResult = ''; }}
    class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs text-gray-400 transition-colors"
  >
    Reset Filters
  </button>

Jangan ubah bagian lain di file ini.
```

---

## FIX 6 — Tambah Start/Stop Agent Toggle di Dashboard

**File 1:** `python/api/server.py`

Tambahkan 2 endpoint baru setelah endpoint `/config`:

```
POST /agent/start:
- Set agent_running = True di variable global
- Simpan flag ke MongoDB: db["config"].update_one(
    {"_id": "agent_config"},
    {"$set": {"agent_running": True}},
    upsert=True
  )
- Return: {"success": True, "agent_running": True}

POST /agent/stop:
- Set agent_running = False di variable global
- Simpan flag ke MongoDB: db["config"].update_one(
    {"_id": "agent_config"},
    {"$set": {"agent_running": False}},
    upsert=True
  )
- Return: {"success": True, "agent_running": False}

CATATAN: agent_running di sini adalah flag di database.
Python orchestrator perlu cek flag ini di setiap cycle (lihat FIX 7).
```

**File 2:** `svelte/src/lib/api.ts`

Tambahkan 2 function baru di bagian bawah file, setelah updateConfig:

```typescript
export async function startAgent() {
  return fetchJSON(`${API_BASE}/agent/start`, { method: 'POST' });
}

export async function stopAgent() {
  return fetchJSON(`${API_BASE}/agent/stop`, { method: 'POST' });
}
```

**File 3:** `svelte/src/routes/+page.svelte`

Tambahkan toggle start/stop di section Agent Status:

```
Import startAgent, stopAgent dari '$lib/api'
Tambahkan state: toggling: boolean = false

Tambahkan function toggleAgent():
- Set toggling = true
- Jika status.agent_running: panggil stopAgent()
- Jika tidak: panggil startAgent()
- Reload status dengan fetchStatus()
- Set toggling = false

Di dalam card "Status" yang sudah ada (yang menampilkan Running/Stopped),
tambahkan tombol di bawah text status:
  <button
    onclick={toggleAgent}
    disabled={toggling}
    class="mt-3 w-full px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
           {status?.agent_running
             ? 'bg-red-900/30 border border-red-700 text-red-300 hover:bg-red-900/50'
             : 'bg-emerald-900/30 border border-emerald-700 text-emerald-300 hover:bg-emerald-900/50'}"
  >
    {toggling ? '...' : status?.agent_running ? '⏹ Stop Agent' : '▶ Start Agent'}
  </button>

Jangan ubah bagian lain di dashboard page.
```

---

## FIX 7 — Orchestrator Baca Flag Running dari MongoDB

**File:** `python/agents/orchestrator.py`

Update method `start()` dan tambahkan method `_is_running_flag()`:

```
Tambahkan method _is_running_flag(self) -> bool:
  - Query MongoDB: self._mongo._db["config"].find_one({"_id": "agent_config"})
  - Return doc.get("agent_running", True) jika doc ada
  - Default: True (jika tidak ada config, tetap jalan)
  - Wrap dengan try/except, return True jika error

Update method start() — di dalam while self._running loop:
  Sebelum await self._wait_for_new_candle(), tambahkan:
  
  # Cek flag dari MongoDB setiap cycle
  if not self._is_running_flag():
      logger.info("Orchestrator: agent dihentikan via dashboard — waiting...")
      await asyncio.sleep(30)  # tunggu 30 detik, cek lagi
      continue

Ini memungkinkan dashboard bisa stop agent tanpa kill process Python.
Jangan ubah bagian lain di orchestrator.
```

---

## FIX 8 — Tambah summary statistics di Dashboard

**File:** `svelte/src/routes/+page.svelte`

Tambahkan section statistik trading di bawah section Recent Trades:

```
Tambahkan state: stats: object | null = null

Di function loadData(), tambahkan fetch trades untuk hitung stats:
  Setelah [status, signals, trades] = await Promise.all([...]):
  
  // Hitung stats dari trades yang sudah diload
  const closedTrades = trades.filter(t => t.pnl != null);
  if (closedTrades.length > 0) {
    const wins = closedTrades.filter(t => t.pnl > 0);
    stats = {
      total: closedTrades.length,
      wins: wins.length,
      winRate: (wins.length / closedTrades.length * 100).toFixed(1),
      totalPnl: closedTrades.reduce((sum, t) => sum + (t.pnl || 0), 0)
    };
  }

Tambahkan section stats di bawah grid Recent Signals + Recent Trades:

  {#if stats}
    <div class="mt-8 grid grid-cols-2 sm:grid-cols-4 gap-4">
      <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 text-center">
        <div class="text-xs text-gray-500 mb-1">Total Trades</div>
        <div class="text-2xl font-bold">{stats.total}</div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 text-center">
        <div class="text-xs text-gray-500 mb-1">Win Rate</div>
        <div class="text-2xl font-bold text-emerald-400">{stats.winRate}%</div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 text-center">
        <div class="text-xs text-gray-500 mb-1">Wins / Losses</div>
        <div class="text-2xl font-bold">
          <span class="text-emerald-400">{stats.wins}</span>
          <span class="text-gray-600">/</span>
          <span class="text-red-400">{stats.total - stats.wins}</span>
        </div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 text-center">
        <div class="text-xs text-gray-500 mb-1">Total P&L</div>
        <div class="text-2xl font-bold {stats.totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}">
          {formatCurrency(stats.totalPnl)}
        </div>
      </div>
    </div>
  {/if}
```

---

## URUTAN EKSEKUSI FIX

```
[ ] FIX 2 — MongoClient: tambah _config property + get_config + upsert_config
[ ] FIX 1 — FastAPI: tambah GET /config + POST /config (butuh FIX 2)
[ ] FIX 6 (File 1) — FastAPI: tambah POST /agent/start + POST /agent/stop
[ ] FIX 7 — Orchestrator: baca flag running dari MongoDB
[ ] FIX 3 — SvelteKit Config page: ganti localStorage → API
[ ] FIX 6 (File 2) — api.ts: tambah startAgent + stopAgent
[ ] FIX 6 (File 3) — Dashboard: tambah toggle Start/Stop button
[ ] FIX 4 — Backtest page: tambah equity curve chart + detail view
[ ] FIX 5 — Trades page: tambah date range filter
[ ] FIX 8 — Dashboard: tambah summary statistics
```

---

## CATATAN PENTING UNTUK COPILOT

1. **Jangan hapus kode yang sudah ada** — semua fix bersifat additive kecuali FIX 3
2. **FIX 3 adalah satu-satunya yang replace** — ganti seluruh isi config/+page.svelte
3. **Gunakan Svelte 5 runes** — `$state`, `$derived`, `$effect`, bukan Svelte 4 syntax
4. **SVG chart di FIX 4** — gunakan native SVG, tidak perlu install library apapun
5. **Semua Svelte component gunakan** `onclick` **bukan** `on:click` (Svelte 5)
6. **FastAPI endpoints baru** — letakkan SEBELUM function `_serialize_doc` yang ada di bawah
7. **MongoDB `_id: "agent_config"`** — ini string bukan ObjectId, tidak perlu convert
