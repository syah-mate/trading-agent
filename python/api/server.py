"""
FastAPI Server — TASK 5.1
Expose REST API endpoints untuk SvelteKit dashboard.

CORS: allow localhost:5173 (SvelteKit dev)
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from core.mt5_client import MT5Client
from core.mongo_client import MongoClient
from core.openrouter_client import DEFAULT_MODEL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App init
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AI Trading Agent API",
    version="1.0.0",
    description="REST API untuk SvelteKit dashboard — MT5 + OpenRouter + MongoDB",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global clients (diinisialisasi saat startup)
mt5_client: MT5Client | None = None
mongo_client: MongoClient | None = None

# ---------------------------------------------------------------------------
# Backtest state
# ---------------------------------------------------------------------------
_backtest_lock = threading.Lock()
_backtest_running: bool = False
_backtest_current_run_id: str | None = None


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class BacktestStartRequest(BaseModel):
    symbol: str = "XAUUSD"
    timeframe: str = "M5"          # ← default M5, sinkron dengan live
    months_back: int | None = None
    days_back: int | None = None
    lot_size: float = 0.01
    initial_capital: float = 30.0  # ← default $30 untuk small account


class ConfigUpdateRequest(BaseModel):
    symbol: str | None = None
    lot_size: float | None = None
    confidence_threshold: int | None = None
    sessions: dict | None = None
    max_daily_loss: float | None = None
    llm_model: str | None = None


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup() -> None:
    global mt5_client, mongo_client
    mt5_client = MT5Client()
    mongo_client = MongoClient()
    mongo_client.connect()
    logger.info("FastAPI: startup complete")


@app.on_event("shutdown")
async def shutdown() -> None:
    global mongo_client
    if mongo_client:
        mongo_client.disconnect()
    logger.info("FastAPI: shutdown complete")


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------

@app.get("/status")
async def get_status() -> dict[str, Any]:
    """Return status agent + account info. Baca agent_running dari MongoDB."""
    global mt5_client, mongo_client

    account = {"balance": 0.0, "equity": 0.0, "free_margin": 0.0}
    open_positions_count = 0

    if mt5_client and mt5_client.is_connected:
        account = mt5_client.get_account_info()
        positions = mt5_client.get_open_positions()
        open_positions_count = len(positions)

    # Baca state dari MongoDB — single source of truth
    config = mongo_client.get_config() if mongo_client else {}
    agent_running = config.get("agent_running", False)
    last_cycle_at_raw = config.get("last_cycle_at")
    last_cycle_at_str = last_cycle_at_raw.isoformat() if isinstance(last_cycle_at_raw, datetime) else last_cycle_at_raw

    return {
        "agent_running": agent_running,
        "last_cycle_at": last_cycle_at_str,
        "open_positions": open_positions_count,
        "account": {
            "balance": account.get("balance", 0.0),
            "equity": account.get("equity", 0.0),
            "free_margin": account.get("free_margin", 0.0),
        },
    }


# ---------------------------------------------------------------------------
# GET /trades
# ---------------------------------------------------------------------------

@app.get("/trades")
async def get_trades(
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """Return list trade dari MongoDB."""
    global mongo_client
    if mongo_client is None:
        raise HTTPException(500, "MongoDB not connected")

    trades = mongo_client.get_trades(limit=limit, skip=skip)

    # Convert ObjectId & datetime ke string untuk JSON serialization
    return [_serialize_doc(t) for t in trades]


# ---------------------------------------------------------------------------
# GET /trades/{ticket}
# ---------------------------------------------------------------------------

@app.get("/trades/{ticket}")
async def get_trade_by_ticket(ticket: int) -> dict[str, Any]:
    """Return 1 trade lengkap + monitoring decisions."""
    global mongo_client
    if mongo_client is None:
        raise HTTPException(500, "MongoDB not connected")

    trade = mongo_client.get_trade_by_ticket(ticket)
    if trade is None:
        raise HTTPException(404, f"Trade ticket={ticket} not found")

    return _serialize_doc(trade)


# ---------------------------------------------------------------------------
# GET /signals
# ---------------------------------------------------------------------------

@app.get("/signals")
async def get_signals(
    limit: int = Query(50, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Return list signal evaluasi (valid & rejected)."""
    global mongo_client
    if mongo_client is None:
        raise HTTPException(500, "MongoDB not connected")

    signals = mongo_client.get_signals(limit=limit)
    return [_serialize_doc(s) for s in signals]


# ---------------------------------------------------------------------------
# GET /backtest/runs
# ---------------------------------------------------------------------------

@app.get("/backtest/runs")
async def get_backtest_runs() -> list[dict[str, Any]]:
    """Return semua backtest runs."""
    global mongo_client
    if mongo_client is None:
        raise HTTPException(500, "MongoDB not connected")

    runs = mongo_client.get_backtest_runs()
    return [_serialize_doc(r) for r in runs]


# ---------------------------------------------------------------------------
# GET /backtest/runs/{run_id}
# ---------------------------------------------------------------------------

@app.get("/backtest/runs/{run_id}")
async def get_backtest_run(run_id: str) -> dict[str, Any]:
    """Return 1 backtest run lengkap."""
    global mongo_client
    if mongo_client is None:
        raise HTTPException(500, "MongoDB not connected")

    run = mongo_client.get_backtest_run(run_id)
    if run is None:
        raise HTTPException(404, f"Backtest run {run_id} not found")

    return _serialize_doc(run)


# ---------------------------------------------------------------------------
# POST /backtest/start
# ---------------------------------------------------------------------------

@app.post("/backtest/start")
async def start_backtest(req: BacktestStartRequest) -> dict[str, Any]:
    """Trigger backtest engine secara async. Return run_id.
    
    Hanya 1 backtest yang boleh berjalan pada satu waktu.
    Jika sudah ada backtest aktif, return 409 Conflict.
    """
    global mongo_client, _backtest_running, _backtest_current_run_id
    if mongo_client is None:
        raise HTTPException(500, "MongoDB not connected")

    # Cek apakah ada backtest yang sedang berjalan
    with _backtest_lock:
        if _backtest_running:
            raise HTTPException(
                status_code=409,
                detail=f"Backtest sedang berjalan (run_id={_backtest_current_run_id}). "
                       f"Hentikan dulu via POST /backtest/stop/{_backtest_current_run_id}"
            )
        _backtest_running = True
        _backtest_current_run_id = None  # akan diisi setelah insert

    # Insert backtest run record
    period_label = f"{req.months_back}mo" if req.months_back else f"{req.days_back}d" if req.days_back else "6mo"
    run_id = mongo_client.insert_backtest_run({
        "symbol": req.symbol,
        "timeframe": req.timeframe,
        "months_back": req.months_back,
        "days_back": req.days_back,
        "period": period_label,
        "lot_size": req.lot_size,
        "initial_capital": req.initial_capital,
        "status": "starting",
    })

    with _backtest_lock:
        _backtest_current_run_id = run_id

    # Kick off backtest in background thread (MT5 tidak support async)
    def _run_in_thread():
        global _backtest_running, _backtest_current_run_id
        import asyncio as _aio
        loop = _aio.new_event_loop()
        _aio.set_event_loop(loop)
        try:
            from backtest.engine import BacktestEngine as _Engine
            _engine = _Engine()
            loop.run_until_complete(
                _engine.run(run_id, req.symbol, req.months_back, req.days_back, req.timeframe, req.initial_capital)
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Backtest thread error: %s", e, exc_info=True)
        finally:
            loop.close()
            # Reset flag setelah selesai (baik sukses maupun error)
            with _backtest_lock:
                _backtest_running = False
                _backtest_current_run_id = None
            logging.getLogger(__name__).info("Backtest selesai — flag direset")

    thread = threading.Thread(target=_run_in_thread, daemon=True)
    thread.start()

    return {"run_id": run_id, "status": "started"}


# ---------------------------------------------------------------------------
# GET /backtest/runs/{run_id}/progress
# ---------------------------------------------------------------------------

@app.get("/backtest/runs/{run_id}/progress")
async def get_backtest_progress(run_id: str) -> dict[str, Any]:
    """Return progress backtest."""
    global mongo_client
    if mongo_client is None:
        raise HTTPException(500, "MongoDB not connected")

    run = mongo_client.get_backtest_run(run_id)
    if run is None:
        raise HTTPException(404, f"Backtest run {run_id} not found")

    return {
        "status": run.get("status", "unknown"),
        "progress_pct": run.get("progress_pct", 0),
        "trades_found": run.get("trades_found", 0),
        "current_candle": run.get("current_candle", 0),
    }


# ---------------------------------------------------------------------------
# POST /backtest/stop/{run_id}
# ---------------------------------------------------------------------------

@app.post("/backtest/stop/{run_id}")
async def stop_backtest(run_id: str) -> dict[str, Any]:
    """Set flag cancelling pada backtest run. Engine akan deteksi & berhenti."""
    global mongo_client
    if mongo_client is None:
        raise HTTPException(500, "MongoDB not connected")

    run = mongo_client.get_backtest_run(run_id)
    if run is None:
        raise HTTPException(404, f"Backtest run {run_id} not found")

    if run.get("status") != "running":
        raise HTTPException(400, f"Backtest tidak dalam status running (current: {run.get('status')})")

    mongo_client.update_backtest_run(run_id, {"status": "cancelling"})
    return {"success": True, "run_id": run_id, "message": "Cancelling — backtest akan berhenti dalam beberapa detik"}


# ---------------------------------------------------------------------------
# GET /backtest/status
# ---------------------------------------------------------------------------

@app.get("/backtest/status")
async def get_backtest_status() -> dict[str, Any]:
    """Return apakah ada backtest yang sedang berjalan saat ini."""
    global _backtest_running, _backtest_current_run_id
    return {
        "is_running": _backtest_running,
        "current_run_id": _backtest_current_run_id,
    }


# ---------------------------------------------------------------------------
# GET /config
# ---------------------------------------------------------------------------

@app.get("/config")
async def get_config() -> dict[str, Any]:
    """Return agent config dari MongoDB."""
    global mongo_client
    if mongo_client is None:
        raise HTTPException(500, "MongoDB not connected")

    config = mongo_client.get_config()
    if not config:
        config = {
            "symbol": "XAUUSD",
            "lot_size": 0.01,
            "confidence_threshold": 70,
            "sessions": {"London": True, "NewYork": True, "Overlap": True, "Asia": False},
            "max_daily_loss": 50.0,
            "llm_model": DEFAULT_MODEL,
        }
    return _serialize_doc(config)


# ---------------------------------------------------------------------------
# POST /config
# ---------------------------------------------------------------------------

@app.post("/config")
async def update_config(req: ConfigUpdateRequest) -> dict[str, Any]:
    """Update agent config di MongoDB."""
    global mongo_client
    if mongo_client is None:
        raise HTTPException(500, "MongoDB not connected")

    # Ambil hanya field yang tidak None
    updates = {k: v for k, v in req.model_dump().items() if v is not None}

    if not updates:
        return {"success": True, "updated_fields": []}

    ok = mongo_client.upsert_config(updates)
    if not ok:
        raise HTTPException(500, "Gagal upsert config ke MongoDB")

    return {"success": True, "updated_fields": list(updates.keys())}


# ---------------------------------------------------------------------------
# POST /agent/start
# ---------------------------------------------------------------------------

@app.post("/agent/start")
async def start_agent() -> dict[str, Any]:
    """Set agent_running = True di MongoDB (single source of truth)."""
    global mongo_client
    if mongo_client is None:
        raise HTTPException(500, "MongoDB not connected")

    mongo_client.upsert_config({"agent_running": True})
    return {"success": True, "agent_running": True}


# ---------------------------------------------------------------------------
# POST /agent/stop
# ---------------------------------------------------------------------------

@app.post("/agent/stop")
async def stop_agent() -> dict[str, Any]:
    """Set agent_running = False di MongoDB (single source of truth)."""
    global mongo_client
    if mongo_client is None:
        raise HTTPException(500, "MongoDB not connected")

    mongo_client.upsert_config({"agent_running": False})
    return {"success": True, "agent_running": False}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _serialize_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Convert ObjectId & datetime ke string agar JSON-serializable."""
    result: dict[str, Any] = {}
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, list):
            result[key] = [
                _serialize_doc(item) if isinstance(item, dict) else
                str(item) if isinstance(item, ObjectId) else
                item.isoformat() if isinstance(item, datetime) else
                item
                for item in value
            ]
        else:
            result[key] = value
    return result
