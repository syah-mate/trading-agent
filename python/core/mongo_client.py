"""
MongoDB Client — Wrapper untuk database operations.
TASK 1.4 — Collections: signals, trades, agent_logs, backtest_runs.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from pymongo import MongoClient as PyMongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError
from bson import ObjectId

logger = logging.getLogger(__name__)


class MongoClient:
    """Wrapper untuk operasi MongoDB trading database.

    Collections:
    - signals       → semua signal yang dievaluasi
    - trades        → semua trade yang dieksekusi
    - agent_logs    → log per cycle
    - backtest_runs → hasil backtest

    Usage:
        db = MongoClient()
        db.insert_signal({"direction": "BUY", ...})
    """

    def __init__(self, uri: str | None = None, db_name: str | None = None) -> None:
        load_dotenv()
        self._uri: str = uri or os.getenv("MONGO_URI", "mongodb://localhost:27017")
        self._db_name: str = db_name or os.getenv("MONGO_DB_NAME", "trading_agent")
        self._client: PyMongoClient | None = None
        self._db: Database | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Buka koneksi ke MongoDB."""
        try:
            self._client = PyMongoClient(self._uri, serverSelectionTimeoutMS=5000)
            # Test koneksi
            self._client.admin.command("ping")
            self._db = self._client[self._db_name]
            logger.info("MongoClient: terkoneksi ke %s / %s", self._uri, self._db_name)
            return True
        except PyMongoError as e:
            logger.error("MongoClient: gagal konek — %s", e)
            self._client = None
            self._db = None
            return False

    def disconnect(self) -> None:
        """Tutup koneksi MongoDB."""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None
            logger.info("MongoClient: disconnected")

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._db is not None

    # ------------------------------------------------------------------
    # Collection accessors
    # ------------------------------------------------------------------

    @property
    def _signals(self) -> Collection:
        if self._db is None:
            raise RuntimeError("MongoClient belum connect()")
        return self._db["signals"]

    @property
    def _trades(self) -> Collection:
        if self._db is None:
            raise RuntimeError("MongoClient belum connect()")
        return self._db["trades"]

    @property
    def _agent_logs(self) -> Collection:
        if self._db is None:
            raise RuntimeError("MongoClient belum connect()")
        return self._db["agent_logs"]

    @property
    def _backtest_runs(self) -> Collection:
        if self._db is None:
            raise RuntimeError("MongoClient belum connect()")
        return self._db["backtest_runs"]

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def insert_signal(self, data: dict[str, Any]) -> str:
        """Insert signal evaluasi ke collection signals.

        Returns:
            str — inserted_id sebagai string
        """
        data.setdefault("created_at", datetime.now(timezone.utc))
        result = self._signals.insert_one(data)
        return str(result.inserted_id)

    def get_signals(
        self,
        filter: dict[str, Any] | None = None,
        limit: int = 50,
        skip: int = 0,
    ) -> list[dict[str, Any]]:
        """Ambil signals dengan filter, sort by created_at DESC."""
        filter = filter or {}
        cursor = (
            self._signals.find(filter)
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )
        return list(cursor)

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    def insert_trade(self, data: dict[str, Any]) -> str:
        """Insert trade ke collection trades.

        Returns:
            str — inserted_id sebagai string
        """
        data.setdefault("opened_at", datetime.now(timezone.utc))
        data.setdefault("status", "open")
        data.setdefault("monitoring_log", [])
        result = self._trades.insert_one(data)
        return str(result.inserted_id)

    def update_trade(self, ticket: int, update: dict[str, Any]) -> bool:
        """Update trade berdasarkan ticket number.

        Returns:
            bool — True jika ada dokumen yang diupdate
        """
        update.setdefault("updated_at", datetime.now(timezone.utc))
        result = self._trades.update_one({"ticket": ticket}, {"$set": update})
        return result.modified_count > 0

    def append_monitoring_log(self, ticket: int, log_entry: dict[str, Any]) -> bool:
        """Append entry ke monitoring_log array di trade document."""
        log_entry.setdefault("timestamp", datetime.now(timezone.utc))
        result = self._trades.update_one(
            {"ticket": ticket},
            {"$push": {"monitoring_log": log_entry}},
        )
        return result.modified_count > 0

    def get_trades(
        self,
        filter: dict[str, Any] | None = None,
        limit: int = 50,
        skip: int = 0,
    ) -> list[dict[str, Any]]:
        """Ambil trades dengan filter, sort by opened_at DESC."""
        filter = filter or {}
        cursor = (
            self._trades.find(filter)
            .sort("opened_at", -1)
            .skip(skip)
            .limit(limit)
        )
        return list(cursor)

    def get_trade_by_ticket(self, ticket: int) -> dict[str, Any] | None:
        """Ambil 1 trade berdasarkan ticket number."""
        return self._trades.find_one({"ticket": ticket})

    # ------------------------------------------------------------------
    # Agent Logs
    # ------------------------------------------------------------------

    def insert_log(self, data: dict[str, Any]) -> str:
        """Insert log entry ke agent_logs collection."""
        data.setdefault("created_at", datetime.now(timezone.utc))
        result = self._agent_logs.insert_one(data)
        return str(result.inserted_id)

    def get_logs(
        self,
        filter: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Ambil agent logs, sort by created_at DESC."""
        filter = filter or {}
        cursor = (
            self._agent_logs.find(filter)
            .sort("created_at", -1)
            .limit(limit)
        )
        return list(cursor)

    # ------------------------------------------------------------------
    # Backtest Runs
    # ------------------------------------------------------------------

    def insert_backtest_run(self, data: dict[str, Any]) -> str:
        """Insert backtest run, return run_id sebagai string."""
        data.setdefault("created_at", datetime.now(timezone.utc))
        data.setdefault("status", "pending")
        result = self._backtest_runs.insert_one(data)
        return str(result.inserted_id)

    def update_backtest_run(self, run_id: str, update: dict[str, Any]) -> bool:
        """Update backtest run by _id."""
        update.setdefault("updated_at", datetime.now(timezone.utc))
        try:
            result = self._backtest_runs.update_one(
                {"_id": ObjectId(run_id)}, {"$set": update}
            )
            return result.modified_count > 0
        except Exception:
            return False

    def get_backtest_runs(
        self,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Ambil semua backtest runs, sort by created_at DESC."""
        cursor = (
            self._backtest_runs.find()
            .sort("created_at", -1)
            .limit(limit)
        )
        return list(cursor)

    def get_backtest_run(self, run_id: str) -> dict[str, Any] | None:
        """Ambil 1 backtest run by _id."""
        try:
            return self._backtest_runs.find_one({"_id": ObjectId(run_id)})
        except Exception:
            return None
