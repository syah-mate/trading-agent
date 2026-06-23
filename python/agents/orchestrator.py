"""
Orchestrator v3.1 — S/R Real-Time Tick Loop

Dua asyncio task paralel:
1. _candle_loop() — update S/R levels setiap candle baru close (M5/M15)
2. _tick_loop()  — poll harga setiap 2 detik, trigger AI saat harga touch S/R

Direction deterministik: support→BUY, resistance→SELL.
AI hanya bertindak sebagai validator konfirmasi.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from core.mt5_client import MT5Client, detect_session, calculate_atr
from core.openrouter_client import OpenRouterClient, DEFAULT_MODEL
from core.mongo_client import MongoClient
from core.sr_detector import SRDetector, SRLevel
from agents.trading_agent import TradingAgent
from agents.mt5_executor import MT5Executor
from config import (
    SYMBOL, TIMEFRAME, LOT_SIZE, CANDLES_COUNT,
    CONFIDENCE_THRESHOLD,
)

logger = logging.getLogger(__name__)


class Orchestrator:
    """Master loop — S/R real-time tick loop architecture v3.1."""

    def __init__(self) -> None:
        # Core clients
        self._mt5 = MT5Client()
        self._llm = OpenRouterClient()
        self._mongo = MongoClient()

        # Single agent
        self._agent = TradingAgent(self._llm)

        # Executor
        self._executor = MT5Executor(symbol=SYMBOL, lot_size=LOT_SIZE)

        # S/R Detector
        self._sr_detector = SRDetector()

        # Shared state antar tasks
        self._running: bool = False
        self._last_candle_time: datetime | None = None
        self._m15_candles: list[dict] = []    # di-update oleh candle loop
        self._m5_candles: list[dict] = []     # di-update oleh candle loop
        self._sr_levels_ready: bool = False   # True setelah candle loop pertama selesai

        # Cooldown: hindari multiple trigger di level yang sama
        self._last_trigger_time: datetime | None = None
        self._last_trigger_price: float | None = None

    # ------------------------------------------------------------------
    # Main Loop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start dua loop paralel: candle loop + tick loop."""
        logger.info("=" * 60)
        logger.info("Orchestrator v3.1 — S/R Real-Time Mode Starting")
        logger.info("=" * 60)

        if not self._mt5.connect():
            logger.error("Gagal konek MT5 — exiting")
            return

        if not self._mongo.connect():
            logger.error("Gagal konek MongoDB — exiting")
            self._mt5.disconnect()
            return

        config = self._mongo.get_config()
        llm_model = config.get("llm_model", DEFAULT_MODEL)
        self._llm.set_model(llm_model)
        logger.info("LLM model: %s", llm_model)

        self._running = True

        try:
            await asyncio.gather(
                self._candle_loop(),
                self._tick_loop(),
            )
        except KeyboardInterrupt:
            logger.info("Orchestrator: KeyboardInterrupt")
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

    # ------------------------------------------------------------------
    # Candle Loop — update S/R levels setiap candle baru
    # ------------------------------------------------------------------

    async def _candle_loop(self) -> None:
        """Loop: update candle data dan S/R levels setiap candle M5 baru close.

        Poll setiap 30 detik. Saat candle baru terdeteksi:
        1. Ambil M5 candles terbaru (200 candle)
        2. Downsample ke M15 untuk S/R detection
        3. Update SRDetector dengan data M15 terbaru
        """
        logger.info("Candle loop started")

        while self._running:
            try:
                if not self._is_running_flag():
                    await asyncio.sleep(30)
                    continue

                candles_m5 = self._mt5.get_candles(SYMBOL, "M5", 200)
                if len(candles_m5) < 50:
                    await asyncio.sleep(30)
                    continue

                latest_time = candles_m5[-1].get("time")

                if latest_time != self._last_candle_time:
                    self._last_candle_time = latest_time
                    self._m5_candles = candles_m5

                    # Downsample ke M15 untuk S/R detection
                    m15 = self._agent._downsample_to_m15(candles_m5)
                    self._m15_candles = m15

                    # Update S/R detector
                    self._sr_detector.update(m15)
                    self._sr_levels_ready = True

                    summary = self._sr_detector.summary()
                    logger.info(
                        "Candle loop: new candle %s | S/R: %d fresh levels (%d support, %d resistance)",
                        latest_time,
                        summary["fresh_levels"],
                        len(summary["supports"]),
                        len(summary["resistances"]),
                    )

                    # Simpan S/R summary ke MongoDB untuk dashboard
                    self._mongo.upsert_config({"sr_levels": summary, "last_cycle_at": latest_time})

            except Exception as e:
                logger.error("Candle loop error: %s", e, exc_info=True)

            await asyncio.sleep(30)

        logger.info("Candle loop stopped")

    # ------------------------------------------------------------------
    # Tick Loop — poll harga real-time, trigger AI saat touch S/R
    # ------------------------------------------------------------------

    async def _tick_loop(self) -> None:
        """Loop: poll harga setiap 2 detik, trigger AI konfirmasi saat harga menyentuh S/R fresh.

        Flow saat touch terdeteksi:
        1. Cek session filter (London/NY only)
        2. Cek cooldown (hindari trigger berulang di level sama)
        3. Cek apakah ada posisi aktif (skip jika ada)
        4. Panggil TradingAgent.analyze() sebagai validator
        5. Jika ENTRY → open posisi
        """
        logger.info("Tick loop started — polling every 2 seconds")

        # Tunggu candle loop selesai inisialisasi
        while self._running and not self._sr_levels_ready:
            await asyncio.sleep(1)

        logger.info("Tick loop: S/R levels ready, mulai monitoring harga")

        TRIGGER_COOLDOWN_SECONDS = 300  # 5 menit

        while self._running:
            try:
                if not self._is_running_flag():
                    await asyncio.sleep(5)
                    continue

                # 1. Ambil harga terkini
                price_data = self._mt5.get_current_price(SYMBOL)
                if not price_data or price_data.get("bid", 0) == 0:
                    await asyncio.sleep(2)
                    continue

                current_price = (price_data["bid"] + price_data["ask"]) / 2
                now = datetime.now(timezone.utc)

                # 2. Session filter
                if not self._is_valid_session():
                    await asyncio.sleep(10)  # cek setiap 10 detik saat non-session
                    continue

                # 3. Cek posisi aktif — skip jika sedang holding
                open_positions = self._mt5.get_open_positions()
                if open_positions:
                    await asyncio.sleep(2)
                    continue

                # 4. Cek S/R touch
                if not self._m5_candles:
                    await asyncio.sleep(2)
                    continue

                touched_levels = self._sr_detector.check_touch(current_price, candle_time=now)

                if not touched_levels:
                    await asyncio.sleep(2)
                    continue

                # Ambil level terdekat
                sr_level = min(touched_levels, key=lambda lv: abs(lv.price - current_price))

                # 5. Cooldown check
                if self._last_trigger_time is not None:
                    elapsed = (now - self._last_trigger_time).total_seconds()
                    if elapsed < TRIGGER_COOLDOWN_SECONDS:
                        logger.debug(
                            "Tick loop: cooldown aktif (%.0fs tersisa)",
                            TRIGGER_COOLDOWN_SECONDS - elapsed,
                        )
                        await asyncio.sleep(2)
                        continue

                logger.info(
                    "Tick loop: TOUCH DETECTED! price=%.4f level=%.4f (%s) — calling AI validator...",
                    current_price, sr_level.price, sr_level.kind,
                )

                self._last_trigger_time = now
                self._last_trigger_price = current_price

                # 6. Panggil AI untuk validasi
                await self._handle_sr_touch(sr_level, current_price, now)

            except Exception as e:
                logger.error("Tick loop error: %s", e, exc_info=True)

            await asyncio.sleep(2)

        logger.info("Tick loop stopped")

    # ------------------------------------------------------------------
    # SR Touch Handler — AI validation + eksekusi
    # ------------------------------------------------------------------

    async def _handle_sr_touch(
        self,
        sr_level: "SRLevel",
        current_price: float,
        now: datetime,
    ) -> None:
        """Handle saat harga menyentuh level S/R — validasi via AI, eksekusi jika ENTRY.

        Direction sudah deterministik:
            support   → BUY
            resistance → SELL
        """
        session = detect_session(now)

        if not self._m5_candles:
            logger.warning("_handle_sr_touch: m5_candles belum ada, skip")
            return

        atr = calculate_atr(self._m5_candles, period=14)
        account = self._mt5.get_account_info()
        balance = account.get("balance", 30.0)

        config = self._mongo.get_config()
        risk_percent = float(config.get("risk_percent", 1.0))

        # Panggil AI sebagai validator
        agent_result = await self._agent.analyze(
            candles=self._m5_candles,
            position=None,
            session=session,
            atr=atr,
            symbol=SYMBOL,
            balance=balance,
            risk_percent=risk_percent,
            sr_level=sr_level.to_dict(),
        )

        decision = agent_result.get("decision", "STANDBY")

        # Log ke MongoDB
        self._mongo.insert_log({
            "type": "sr_validation",
            "triggered_at": now,
            "sr_level": sr_level.to_dict(),
            "current_price": current_price,
            "session": session,
            "decision": decision,
            "confidence": agent_result.get("confidence", 0),
            "reason": agent_result.get("reason", ""),
        })

        if decision != "ENTRY":
            logger.info(
                "_handle_sr_touch: AI STANDBY — %s",
                agent_result.get("reason", ""),
            )
            return

        # ENTRY: tentukan direction dari jenis level
        direction = "BUY" if sr_level.kind == "support" else "SELL"
        agent_result["direction"] = direction
        agent_result["entry_price"] = current_price

        # Isi harga yang belum diisi (TP $1, SL dari AI atau ATR fallback)
        agent_result = self._fill_missing_prices(
            agent_result, self._m5_candles, current_price, atr, balance, risk_percent,
        )

        # Guard RR
        if agent_result.get("_skip_low_rr"):
            logger.info("_handle_sr_touch: RR terlalu rendah — skip")
            return

        confidence = agent_result.get("confidence", 0)
        logger.info(
            ">>> OPENING %s at %.4f confidence=%d (S/R level %.4f %s) <<<",
            direction, current_price, confidence, sr_level.price, sr_level.kind,
        )

        trade = self._executor.open_position(agent_result)

        if "error" in trade:
            logger.error("Eksekusi trade gagal: %s", trade["error"])
            return

        trade["symbol"] = SYMBOL
        trade["confidence"] = confidence
        trade["entry_reason"] = agent_result.get("reason", "")
        trade["session"] = session
        trade["sr_level"] = sr_level.to_dict()
        trade["bias_htf"] = agent_result.get("bias_htf")
        trade["rr_ratio_t1"] = agent_result.get("rr_ratio_t1")

        self._mongo.insert_trade(trade)
        self._mongo.insert_signal(agent_result)

        logger.info(
            ">>> TRADE OPENED: ticket=%d %s entry=%.4f sl=%.4f tp=%.4f <<<",
            trade.get("ticket", 0), direction,
            trade.get("entry_price", 0),
            trade.get("sl", 0),
            trade.get("tp", 0),
        )

    # ------------------------------------------------------------------
    # Deprecated methods (dipertahankan untuk backward compatibility)
    # ------------------------------------------------------------------

    async def run_cycle(self) -> dict[str, Any]:
        """Deprecated — gunakan tick loop + _handle_sr_touch. Dipertahankan untuk API compatibility."""
        logger.warning("run_cycle() dipanggil langsung — method ini deprecated di v3.1")
        return {"status": "deprecated", "message": "Gunakan tick loop. Lihat _handle_sr_touch."}

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
        """Deprecated — gunakan _candle_loop() di v3.1. Dipertahankan untuk backward compatibility."""
        logger.warning("_wait_for_candle_interval() dipanggil — method ini deprecated di v3.1")
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

        Rules v3.1:
        - entry_price = current_price
        - SL = ATR × 1.5 dari entry (searah bias) atau dari AI
        - TP1 = fixed $1 target (1.0 / (lot × 100) distance)
        - No TP2 (dihapus per design v3.1)
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

        # Fill SL
        if result.get("sl_price") is None:
            if direction == "BUY":
                result["sl_price"] = round(entry - atr * sl_mult, 5)
            else:
                result["sl_price"] = round(entry + atr * sl_mult, 5)
            logger.info("_fill_missing_prices: sl_price = %.5f (ATR×%.1f)", result["sl_price"], sl_mult)

        # Fill TP1 — FIXED $1 target untuk 0.01 lot XAUUSD
        # $1 = tp_distance × lot × 100  →  tp_distance = 1.0 / (lot × 100)
        lot_for_calc = float(result.get("lot_size") or 0.01)
        tp_distance = 1.0 / (lot_for_calc * 100)   # untuk 0.01 lot = $1.00 move

        if result.get("tp1_price") is None:
            if direction == "BUY":
                result["tp1_price"] = round(entry + tp_distance, 5)
            else:
                result["tp1_price"] = round(entry - tp_distance, 5)
            logger.info(
                "_fill_missing_prices: tp1_price = %.5f (fixed $1 target, distance=%.4f)",
                result["tp1_price"], tp_distance,
            )

        # Tidak ada TP2 (dihapus per design v3.1)
        result.pop("tp2_price", None)
        result.pop("rr_ratio_t2", None)

        # Fill RR ratio (SL vs TP $1)
        sl = float(result["sl_price"])
        tp1 = float(result["tp1_price"])
        if result.get("rr_ratio_t1") is None:
            risk = abs(entry - sl)
            reward = abs(tp1 - entry)
            result["rr_ratio_t1"] = round(reward / risk, 2) if risk > 0 else 1.0

        # Guard: jika RR < 0.8, skip entry
        rr = result.get("rr_ratio_t1", 0)
        if rr < 0.8:
            logger.warning(
                "_fill_missing_prices: RR terlalu rendah (%.2f < 0.8) — tandai SKIP",
                rr,
            )
            result["_skip_low_rr"] = True

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
