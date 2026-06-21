"""
FastAPI Server — TASK 5.1
Expose REST API endpoints untuk SvelteKit dashboard.

CORS: allow localhost:5173 (SvelteKit dev)
"""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from core.mt5_client import MT5Client
from core.mongo_client import MongoClient

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
agent_running: bool = False
last_cycle_at: datetime | None = None


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class BacktestStartRequest(BaseModel):
    symbol: str = "XAUUSD"
    timeframe: str = "M15"
    months_back: int = 6
    lot_size: float = 0.01


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
    """Return status agent + account info."""
    global agent_running, last_cycle_at, mt5_client

    account = {"balance": 0.0, "equity": 0.0, "free_margin": 0.0}
    open_positions_count = 0

    if mt5_client and mt5_client.is_connected:
        account = mt5_client.get_account_info()
        positions = mt5_client.get_open_positions()
        open_positions_count = len(positions)

    return {
        "agent_running": agent_running,
        "last_cycle_at": last_cycle_at.isoformat() if last_cycle_at else None,
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
    """Trigger backtest engine secara async. Return run_id."""
    global mongo_client
    if mongo_client is None:
        raise HTTPException(500, "MongoDB not connected")

    import asyncio
    from backtest.engine import BacktestEngine

    # Insert backtest run record
    run_id = mongo_client.insert_backtest_run({
        "symbol": req.symbol,
        "timeframe": req.timeframe,
        "months_back": req.months_back,
        "lot_size": req.lot_size,
        "status": "starting",
    })

    # Kick off backtest in background task
    engine = BacktestEngine()
    asyncio.create_task(
        engine.run(run_id, req.symbol, req.months_back)
    )

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
