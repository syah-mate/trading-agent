"""
Orchestrator — TASK 4.1
Master agent loop: jalankan sub-agents, evaluasi sinyal, eksekusi trade.

Siklus per candle M15:
1. Ambil data → candles, price, session
2. Jalankan VP + LS agents secara parallel
3. Jika ada posisi aktif → monitor (skip evaluasi sinyal baru)
4. Jika tidak ada posisi → evaluasi sinyal → eksekusi jika valid
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from core.mt5_client import MT5Client, detect_session, calculate_atr
from core.openrouter_client import OpenRouterClient
from core.mongo_client import MongoClient
from agents.volume_profile import VolumeProfileAgent
from agents.liquidity_sweep import LiquiditySweepAgent
from agents.evaluator import EvaluatorAgent
from agents.mt5_executor import MT5Executor
from agents.position_monitor import PositionMonitorAgent
from config import (
    SYMBOL, TIMEFRAME, LOT_SIZE, CANDLES_COUNT,
    CONFIDENCE_THRESHOLD, CYCLE_INTERVAL_SECONDS,
)

logger = logging.getLogger(__name__)


class Orchestrator:
    """Master agent — mengatur siklus trading penuh."""

    def __init__(self) -> None:
        # Core clients
        self._mt5 = MT5Client()
        self._llm = OpenRouterClient()
        self._mongo = MongoClient()

        # Agents
        self._vp_agent = VolumeProfileAgent()
        self._ls_agent = LiquiditySweepAgent()
        self._evaluator = EvaluatorAgent(self._llm)
        self._executor = MT5Executor(symbol=SYMBOL, lot_size=LOT_SIZE)
        self._monitor = PositionMonitorAgent(self._llm, self._executor)

        # State
        self._running: bool = False
        self._last_candle_time: datetime | None = None
        self._last_cycle_at: datetime | None = None

    # ------------------------------------------------------------------
    # Main Loop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start main loop — konek ke MT5 & MongoDB, lalu loop forever."""
        logger.info("=" * 60)
        logger.info("Orchestrator starting...")
        logger.info("=" * 60)

        # Connect
        if not self._mt5.connect():
            logger.error("Gagal konek MT5 — exiting")
            return

        if not self._mongo.connect():
            logger.error("Gagal konek MongoDB — exiting")
            self._mt5.disconnect()
            return

        self._running = True
        logger.info("Orchestrator: semua koneksi OK, mulai main loop")

        try:
            while self._running:
                try:
                    await self._wait_for_new_candle()
                    await self.run_cycle()
                except Exception as e:
                    logger.error("Orchestrator cycle error: %s", e, exc_info=True)
                    # Brief pause sebelum retry
                    await asyncio.sleep(5)
        except KeyboardInterrupt:
            logger.info("Orchestrator: KeyboardInterrupt diterima")
        finally:
            await self._shutdown()

    async def stop(self) -> None:
        """Graceful stop."""
        self._running = False

    async def _shutdown(self) -> None:
        """Cleanup semua koneksi."""
        logger.info("Orchestrator: shutting down...")
        self._mongo.disconnect()
        self._mt5.disconnect()
        await self._llm.close()
        logger.info("Orchestrator: shutdown complete")

    # ------------------------------------------------------------------
    # Cycle
    # ------------------------------------------------------------------

    async def run_cycle(self) -> dict[str, Any]:
        """Jalankan 1 siklus trading penuh.

        Returns:
            dict — ringkasan cycle untuk logging
        """
        cycle_start = datetime.now(timezone.utc)
        session = detect_session(cycle_start)

        logger.info("--- Cycle start: %s [%s] ---", cycle_start.isoformat(), session)

        # STEP 1: Ambil data
        candles = self._mt5.get_candles(SYMBOL, TIMEFRAME, CANDLES_COUNT)
        if len(candles) < 100:
            logger.warning("Cycle: hanya %d candle, skip", len(candles))
            return {"status": "skip", "reason": "insufficient_candles"}

        current_price = self._mt5.get_current_price(SYMBOL)
        logger.debug("Current %s: bid=%.4f ask=%.4f", SYMBOL, current_price["bid"], current_price["ask"])

        # STEP 2: Jalankan sub-agents PARALEL
        vp_result, sweep_result = await asyncio.gather(
            asyncio.to_thread(self._vp_agent.analyze, candles),
            asyncio.to_thread(self._ls_agent.analyze, candles),
        )

        # STEP 3: Log hasil sub-agents
        self._mongo.insert_log({
            "type": "sub_agents",
            "cycle_at": cycle_start,
            "session": session,
            "vp": {
                "poc": vp_result.get("poc"),
                "vah": vp_result.get("vah"),
                "val": vp_result.get("val"),
            },
            "sweep": {
                "detected": sweep_result.get("sweep_detected"),
                "direction": sweep_result.get("direction"),
                "level": sweep_result.get("sweep_level"),
                "candles_since": sweep_result.get("candles_since_sweep"),
            },
        })

        # STEP 4: Cek posisi aktif
        open_positions = self._mt5.get_open_positions()

        if open_positions:
            logger.info("Cycle: %d posisi aktif — monitoring...", len(open_positions))
            await self._monitor_positions(open_positions, candles, vp_result, sweep_result)
            cycle_result = {"status": "monitored", "positions": len(open_positions)}
        else:
            # STEP 5: Evaluasi sinyal baru
            logger.info("Cycle: tidak ada posisi — evaluasi sinyal...")
            cycle_result = await self._evaluate_and_trade(
                vp_result, sweep_result, candles, session
            )

        self._last_cycle_at = cycle_start

        # Update status di MongoDB
        self._mongo.insert_log({
            "type": "cycle_summary",
            "cycle_at": cycle_start,
            "session": session,
            "result": cycle_result,
        })

        logger.info("--- Cycle end: %s ---", cycle_result.get("status"))
        return cycle_result

    # ------------------------------------------------------------------
    # Position Monitoring
    # ------------------------------------------------------------------

    async def _monitor_positions(
        self,
        positions: list[dict[str, Any]],
        candles: list[dict[str, Any]],
        vp_result: dict[str, Any],
        sweep_result: dict[str, Any],
    ) -> None:
        """Monitor semua posisi aktif via LLM."""
        for position in positions:
            try:
                decision = await self._monitor.monitor(
                    position, candles, vp_result, sweep_result
                )
                # Simpan ke MongoDB
                self._mongo.append_monitoring_log(
                    ticket=position["ticket"],
                    log_entry=decision,
                )
                # Update trade record
                self._mongo.update_trade(
                    ticket=position["ticket"],
                    update={
                        "last_monitored_at": decision.get("monitored_at"),
                        "last_decision": decision.get("decision"),
                        "last_reasoning": decision.get("reasoning"),
                    },
                )
            except Exception as e:
                logger.error("Monitor posisi ticket=%d error: %s", position.get("ticket"), e)

    # ------------------------------------------------------------------
    # Signal Evaluation & Trade Execution
    # ------------------------------------------------------------------

    async def _evaluate_and_trade(
        self,
        vp_result: dict[str, Any],
        sweep_result: dict[str, Any],
        candles: list[dict[str, Any]],
        session: str,
    ) -> dict[str, Any]:
        """Evaluasi sinyal baru, eksekusi jika valid."""
        # Evaluasi via LLM
        eval_result = await self._evaluator.evaluate(
            vp_result, sweep_result, candles, session
        )

        # Simpan signal ke MongoDB
        self._mongo.insert_signal(eval_result)

        if not eval_result.get("is_valid"):
            return {
                "status": "no_signal",
                "reason": eval_result.get("rejection_reason", "Sinyal tidak valid"),
            }

        confidence = eval_result.get("confidence", 0)
        if confidence < CONFIDENCE_THRESHOLD:
            logger.info(
                "Signal valid tapi confidence %d < threshold %d — skip",
                confidence, CONFIDENCE_THRESHOLD,
            )
            return {
                "status": "low_confidence",
                "confidence": confidence,
                "threshold": CONFIDENCE_THRESHOLD,
            }

        # Eksekusi trade!
        logger.info(">>> OPENING POSITION: %s confidence=%d <<<", eval_result.get("direction"), confidence)

        trade = self._executor.open_position(eval_result)

        if "error" in trade:
            logger.error("Eksekusi trade gagal: %s", trade["error"])
            return {"status": "execution_failed", "error": trade["error"]}

        # Simpan trade ke MongoDB
        trade["symbol"] = SYMBOL
        trade["confidence"] = confidence
        trade["entry_reason"] = eval_result.get("entry_reason", "")
        trade["session"] = session
        self._mongo.insert_trade(trade)

        return {
            "status": "trade_opened",
            "ticket": trade.get("ticket"),
            "direction": trade.get("direction"),
            "confidence": confidence,
        }

    # ------------------------------------------------------------------
    # Wait for new candle
    # ------------------------------------------------------------------

    async def _wait_for_new_candle(self) -> None:
        """Tunggu sampai candle M15 baru terbentuk.

        Cek setiap CYCLE_INTERVAL_SECONDS detik apakah menit sudah
        berubah ke kelipatan 15 (0, 15, 30, 45).
        """
        while self._running:
            now = datetime.now(timezone.utc)
            minute = now.minute
            second = now.second

            # Cek apakah ini menit kelipatan 15
            if minute % 15 == 0:
                # Cek apakah ini candle baru (beda dari last_candle_time)
                candle_time = now.replace(second=0, microsecond=0)
                if self._last_candle_time is None or candle_time > self._last_candle_time:
                    self._last_candle_time = candle_time
                    return  # Candle baru, lanjutkan cycle

            # Tunggu
            await asyncio.sleep(CYCLE_INTERVAL_SECONDS)
