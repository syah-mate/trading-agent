"""
Orchestrator v2.1 — Always-In Strategy Loop

Setiap 3 candle M15 baru:
1. Ambil data candle (200 candle)
2. Jika ADA posisi aktif → SKIP (tunggu semua posisi closed)
3. Jika TIDAK ada posisi → WAJIB ENTRY via TradingAgent LLM
4. Tidak ada STANDBY — selalu open posisi dengan setup terbaik
5. Rule-based fallback untuk null prices (current price + ATR)

Semua analisis dilakukan oleh SATU LLM call melalui TradingAgent.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from core.mt5_client import MT5Client, detect_session, calculate_atr
from core.openrouter_client import OpenRouterClient, DEFAULT_MODEL
from core.mongo_client import MongoClient
from agents.trading_agent import TradingAgent
from agents.mt5_executor import MT5Executor
from config import (
    SYMBOL, TIMEFRAME, LOT_SIZE, CANDLES_COUNT,
    CONFIDENCE_THRESHOLD,
)

logger = logging.getLogger(__name__)

# Jumlah candle baru sebelum menjalankan agent
CANDLE_INTERVAL = 1  # M5 scalp: cek setiap candle baru


class Orchestrator:
    """Master loop — simplified single-agent architecture."""

    def __init__(self) -> None:
        # Core clients
        self._mt5 = MT5Client()
        self._llm = OpenRouterClient()
        self._mongo = MongoClient()

        # Single agent
        self._agent = TradingAgent(self._llm)

        # Executor
        self._executor = MT5Executor(symbol=SYMBOL, lot_size=LOT_SIZE)

        # State
        self._running: bool = False
        self._last_agent_candle_time: datetime | None = None
        self._candles_since_last_run: int = 0

    # ------------------------------------------------------------------
    # Main Loop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start main loop."""
        logger.info("=" * 60)
        logger.info("Orchestrator v2.0 — Single Agent Mode Starting")
        logger.info("Candle interval: every %d M15 candles", CANDLE_INTERVAL)
        logger.info("=" * 60)

        # Connect
        if not self._mt5.connect():
            logger.error("Gagal konek MT5 — exiting")
            return

        if not self._mongo.connect():
            logger.error("Gagal konek MongoDB — exiting")
            self._mt5.disconnect()
            return

        # Load LLM model dari user config (terpusat dari /config)
        config = self._mongo.get_config()
        llm_model = config.get("llm_model", DEFAULT_MODEL)
        self._llm.set_model(llm_model)
        logger.info("Orchestrator: LLM model dari config = %s", llm_model)

        self._running = True
        logger.info("Orchestrator: semua koneksi OK, mulai main loop")

        try:
            while self._running:
                try:
                    # Cek flag dari MongoDB
                    if not self._is_running_flag():
                        logger.info("Orchestrator: agent dihentikan via dashboard — waiting...")
                        await asyncio.sleep(30)
                        continue

                    await self._wait_for_candle_interval()

                    # Session filter: hanya entry di London & NY open
                    if not self._is_valid_session():
                        logger.info("Orchestrator: bukan sesi aktif — skip cycle")
                        continue

                    await self.run_cycle()
                except Exception as e:
                    logger.error("Orchestrator cycle error: %s", e, exc_info=True)
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
        """Jalankan 1 siklus evaluasi trading.

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

        current_price_data = self._mt5.get_current_price(SYMBOL)
        current_price = (current_price_data["bid"] + current_price_data["ask"]) / 2
        logger.debug("Current %s: %.4f", SYMBOL, current_price)

        # STEP 2: Cek posisi aktif via MT5
        open_positions = self._mt5.get_open_positions()

        if open_positions:
            logger.info(
                "Cycle: %d posisi aktif — SKIP (tidak ada monitoring)",
                len(open_positions),
            )
            # Tetap log status
            for pos in open_positions:
                entry = float(pos.get("price_open", 0))
                sl = float(pos.get("sl", 0))
                tp = float(pos.get("tp", 0))
                pnl = self._calc_pnl(pos, current_price)
                logger.info(
                    "  Pos #%d: %s entry=%.4f sl=%.4f tp=%.4f pnl=%+.2f",
                    pos.get("ticket"),
                    "BUY" if pos.get("type") in (0, "BUY") else "SELL",
                    entry, sl, tp, pnl,
                )

            cycle_result = {
                "status": "holding",
                "positions": len(open_positions),
                "reason": "Posisi aktif — menunggu SL/TP",
            }
        else:
            # STEP 3: Tidak ada posisi → WAJIB ENTRY (v2.1 always-in)
            logger.info("Cycle: tidak ada posisi — evaluasi sinyal via TradingAgent...")

            atr = calculate_atr(candles, period=14)

            # Get account info
            account = self._mt5.get_account_info()
            balance = account.get("balance", 10000.0)

            # Load risk percent from config
            config = self._mongo.get_config()
            risk_percent = float(config.get("risk_percent", 1.0))

            agent_result = await self._agent.analyze(
                candles=candles,
                position=None,
                session=session,
                atr=atr,
                symbol=SYMBOL,
                balance=balance,
                risk_percent=risk_percent,
            )

            # v3.0: Cek apakah agent memutuskan STANDBY
            decision = agent_result.get("decision", "ENTRY")

            if decision == "STANDBY":
                reason = agent_result.get("reason", "")
                logger.info("Orchestrator: agent STANDBY — %s", reason)

                self._mongo.insert_log({
                    "type": "standby",
                    "cycle_at": cycle_start,
                    "session": session,
                    "reason": reason,
                })

                cycle_result = {
                    "status": "standby",
                    "reason": reason,
                }
            else:
                # ENTRY: isi null prices jika perlu
                agent_result = self._fill_missing_prices(
                    agent_result, candles, current_price, atr, balance, risk_percent,
                )

                # Log signal
                self._mongo.insert_log({
                    "type": "agent_decision",
                    "cycle_at": cycle_start,
                    "session": session,
                    "decision": agent_result,
                })

                # Simpan signal ke MongoDB
                self._mongo.insert_signal(agent_result)

                # v3.0: Eksekusi trade (hanya untuk ENTRY)
                direction = agent_result.get("direction")
                confidence = agent_result.get("confidence", 0)
                logger.info(
                    ">>> OPENING %s confidence=%d <<<", direction, confidence,
                )

                trade = self._executor.open_position(agent_result)

                if "error" in trade:
                    logger.error("Eksekusi trade gagal: %s", trade["error"])
                    cycle_result = {
                        "status": "execution_failed",
                        "error": trade["error"],
                    }
                else:
                    # Simpan trade ke MongoDB
                    trade["symbol"] = SYMBOL
                    trade["confidence"] = confidence
                    trade["entry_reason"] = agent_result.get("reason", "")
                    trade["session"] = session
                    trade["bias_htf"] = agent_result.get("bias_htf")
                    trade["rr_ratio_t1"] = agent_result.get("rr_ratio_t1")
                    trade["rr_ratio_t2"] = agent_result.get("rr_ratio_t2")
                    trade["tp2_price"] = agent_result.get("tp2_price")
                    self._mongo.insert_trade(trade)

                    cycle_result = {
                        "status": "trade_opened",
                        "ticket": trade.get("ticket"),
                        "direction": trade.get("direction"),
                        "confidence": confidence,
                    }

                    logger.info(
                        ">>> TRADE OPENED: ticket=%d %s entry=%.4f sl=%.4f tp=%.4f <<<",
                        trade.get("ticket"), direction,
                        trade.get("entry_price"),
                        trade.get("sl"),
                        trade.get("tp"),
                    )

        # Update status
        self._mongo.insert_log({
            "type": "cycle_summary",
            "cycle_at": cycle_start,
            "session": session,
            "result": cycle_result,
        })

        # Update last_cycle_at di config (single source of truth)
        self._mongo.upsert_config({"last_cycle_at": cycle_start})

        logger.info("--- Cycle end: %s ---", cycle_result.get("status"))
        return cycle_result

    # ------------------------------------------------------------------
    # Session Validator (v3.0)
    # ------------------------------------------------------------------

    @staticmethod
    def _is_valid_session() -> bool:
        """Cek apakah saat ini adalah sesi London atau NY (WIB = UTC+7).

        London Open: 14:00–17:00 WIB = 07:00–10:00 UTC
        New York Open: 19:00–22:00 WIB = 12:00–15:00 UTC

        Returns:
            True jika sesi valid untuk entry
        """
        from datetime import datetime, timezone as tz
        now_utc = datetime.now(tz.utc)
        hour_utc = now_utc.hour

        is_london = 7 <= hour_utc < 10
        is_newyork = 12 <= hour_utc < 15

        if is_london:
            logger.info("Session: London Open ✅ (boleh entry)")
            return True
        elif is_newyork:
            logger.info("Session: New York Open ✅ (boleh entry)")
            return True
        else:
            logger.info("Session: Di luar sesi aktif (Asia/transisi) — SKIP entry")
            return False

    # ------------------------------------------------------------------
    # Wait for candle interval
    # ------------------------------------------------------------------

    def _is_running_flag(self) -> bool:
        """Cek apakah agent_running = True di MongoDB config."""
        try:
            config = self._mongo.get_config()
            return config.get("agent_running", False)
        except Exception:
            return True  # default: running

    async def _wait_for_candle_interval(self) -> None:
        """Tunggu sampai CANDLE_INTERVAL candle M15 baru tersedia.

        Cek setiap 30 detik apakah candle baru sudah terbentuk.
        """
        while self._running:
            # Ambil candle terbaru
            candles = self._mt5.get_candles(SYMBOL, TIMEFRAME, 5)
            if len(candles) < 2:
                await asyncio.sleep(30)
                continue

            latest_candle_time = candles[-1].get("time")

            if self._last_agent_candle_time is None:
                # Pertama kali — catat candle saat ini
                self._last_agent_candle_time = latest_candle_time
                self._candles_since_last_run = 0
                logger.info(
                    "Orchestrator: initial candle tracked — %s",
                    latest_candle_time,
                )
                await asyncio.sleep(30)
                continue

            if latest_candle_time != self._last_agent_candle_time:
                # Candle baru!
                self._candles_since_last_run += 1
                self._last_agent_candle_time = latest_candle_time

                if self._candles_since_last_run >= CANDLE_INTERVAL:
                    self._candles_since_last_run = 0
                    logger.info(
                        "Orchestrator: %d candles elapsed — running agent",
                        CANDLE_INTERVAL,
                    )
                    return

            await asyncio.sleep(30)

    # ------------------------------------------------------------------
    # Fallback Price Filler (v2.1 — always-in)
    # ------------------------------------------------------------------

    @staticmethod
    def _fill_missing_prices(
        agent_result: dict[str, Any],
        candles: list[dict[str, Any]],
        current_price: float,
        atr: float,
        balance: float,
        risk_percent: float,
    ) -> dict[str, Any]:
        """Isi null prices dengan rule-based fallback agar trade tetap bisa dibuka.

        Rules:
        - entry_price = current_price
        - SL = ATR × 1.5 dari entry (searah bias)
        - TP1 = ATR × 1.5 dari entry (RR ~1:1)
        - TP2 = ATR × 3.0 dari entry (RR ~1:2)
        - lot_size = kalkulasi risk-based dari balance & SL distance
        - direction = dari bias_htf, atau dari price vs mid-range
        """
        result = dict(agent_result)
        direction = result.get("direction")
        bias_htf = result.get("bias_htf", "")

        # Tentukan direction jika null
        if direction not in ("BUY", "SELL"):
            # Fallback: bandingkan current price vs mid-range 100 candle
            all_highs = [float(c["high"]) for c in candles[-100:]]
            all_lows = [float(c["low"]) for c in candles[-100:]]
            mid_range = (max(all_highs) + min(all_lows)) / 2
            if current_price > mid_range:
                direction = "BUY"
                bias_htf = "BULLISH"
            else:
                direction = "SELL"
                bias_htf = "BEARISH"
            result["direction"] = direction
            result["bias_htf"] = bias_htf
            logger.info(
                "_fill_missing_prices: direction auto-detected → %s (price %.2f vs mid %.2f)",
                direction, current_price, mid_range,
            )

        # Fill entry_price
        if result.get("entry_price") is None:
            result["entry_price"] = round(current_price, 5)
            logger.info("_fill_missing_prices: entry_price = current_price = %.5f", current_price)

        entry = float(result["entry_price"])
        sl_mult = 1.5
        tp1_mult = 1.5
        tp2_mult = 3.0

        # Fill SL
        if result.get("sl_price") is None:
            if direction == "BUY":
                result["sl_price"] = round(entry - atr * sl_mult, 5)
            else:
                result["sl_price"] = round(entry + atr * sl_mult, 5)
            logger.info("_fill_missing_prices: sl_price = %.5f (ATR×%.1f)", result["sl_price"], sl_mult)

        # Fill TP1
        if result.get("tp1_price") is None:
            if direction == "BUY":
                result["tp1_price"] = round(entry + atr * tp1_mult, 5)
            else:
                result["tp1_price"] = round(entry - atr * tp1_mult, 5)
            logger.info("_fill_missing_prices: tp1_price = %.5f (ATR×%.1f)", result["tp1_price"], tp1_mult)

        # Fill TP2
        if result.get("tp2_price") is None:
            if direction == "BUY":
                result["tp2_price"] = round(entry + atr * tp2_mult, 5)
            else:
                result["tp2_price"] = round(entry - atr * tp2_mult, 5)
            logger.info("_fill_missing_prices: tp2_price = %.5f (ATR×%.1f)", result["tp2_price"], tp2_mult)

        # Fill RR ratios
        sl = float(result["sl_price"])
        tp1 = float(result["tp1_price"])
        tp2 = float(result["tp2_price"])

        if result.get("rr_ratio_t1") is None:
            r = abs(entry - sl)
            r1 = abs(tp1 - entry)
            result["rr_ratio_t1"] = round(r1 / r, 2) if r > 0 else 1.0

        if result.get("rr_ratio_t2") is None:
            r = abs(entry - sl)
            r2 = abs(tp2 - entry)
            result["rr_ratio_t2"] = round(r2 / r, 2) if r > 0 else 2.0

        # Fill lot_size
        if result.get("lot_size") is None:
            risk_amount = balance * (risk_percent / 100.0)
            sl_distance = abs(entry - sl)
            # XAUUSD: 1 lot = $100 per $1 move (100 oz × $1)
            # lot = risk_amount / (sl_distance × 100)
            if sl_distance > 0:
                lot = risk_amount / (sl_distance * 100)
                lot = max(0.01, round(lot, 2))  # min 0.01 lot
            else:
                lot = 0.01
            result["lot_size"] = lot
            logger.info(
                "_fill_missing_prices: lot_size = %.2f (risk=$%.2f, sl_distance=%.4f)",
                lot, risk_amount, sl_distance,
            )

        # Fill risk_percent
        if result.get("risk_percent") is None:
            result["risk_percent"] = risk_percent

        return result

    @staticmethod
    def _calc_pnl(position: dict[str, Any], current_price: float) -> float:
        """Hitung floating PnL posisi dalam USD (XAUUSD).

        Formula: PnL = price_diff × volume × 100
        Karena 1 lot XAUUSD = 100 oz, setiap $1 move = $100 per lot.
        """
        direction = 1 if position.get("type") in (0, "BUY") else -1
        entry = float(position.get("price_open", 0))
        volume = float(position.get("volume", 0.01))
        price_diff = (current_price - entry) * direction
        return price_diff * volume * 100
