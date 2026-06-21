"""
Backtest Engine — TASK 6.1
Backtest strategy secara sequential (anti-lookahead).

PENTING:
- Load semua historical candles, process candle by candle
- VP dihitung dari candles[0:i] saja
- LLM call dibatasi: monitor setiap 3 candle
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from core.mt5_client import MT5Client, detect_session, calculate_atr
from core.openrouter_client import OpenRouterClient
from core.mongo_client import MongoClient
from agents.volume_profile import VolumeProfileAgent
from agents.liquidity_sweep import LiquiditySweepAgent
from agents.evaluator import EvaluatorAgent
from backtest.reporter import generate_stats

logger = logging.getLogger(__name__)

# Rate limiting untuk LLM monitor: setiap N candle
MONITOR_INTERVAL = 3


class BacktestEngine:
    """Backtest engine — run strategy pada historical data."""

    def __init__(self) -> None:
        self._mt5 = MT5Client()
        self._llm = OpenRouterClient()
        self._mongo = MongoClient()
        self._vp_agent = VolumeProfileAgent()
        self._ls_agent = LiquiditySweepAgent()
        self._evaluator = EvaluatorAgent(self._llm)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(
        self,
        run_id: str,
        symbol: str = "XAUUSD",
        months_back: int = 6,
    ) -> None:
        """Jalankan backtest.

        Args:
            run_id: MongoDB _id untuk backtest run record
            symbol: simbol trading
            months_back: berapa bulan ke belakang
        """
        logger.info("=" * 60)
        logger.info("Backtest: run_id=%s symbol=%s months=%d", run_id, symbol, months_back)
        logger.info("=" * 60)

        # Connect
        if not self._mt5.connect():
            self._mongo.update_backtest_run(run_id, {"status": "error", "error": "MT5 connect failed"})
            return
        if not self._mongo.connect():
            self._mongo.update_backtest_run(run_id, {"status": "error", "error": "MongoDB connect failed"})
            return

        self._mongo.update_backtest_run(run_id, {"status": "running", "progress_pct": 0})

        try:
            # Load ALL historical candles
            all_candles = self._load_historical_candles(symbol, months_back)
            total_candles = len(all_candles)

            if total_candles < 120:
                self._mongo.update_backtest_run(run_id, {
                    "status": "error",
                    "error": f"Hanya {total_candles} candle tersedia (min 120)",
                })
                return

            logger.info("Backtest: %d candles loaded", total_candles)

            # State
            virtual_trades: list[dict[str, Any]] = []
            virtual_position: dict[str, Any] | None = None
            equity_curve: list[dict[str, Any]] = []
            initial_balance = 10000.0
            current_balance = initial_balance

            # For rate-limiting LLM monitor calls
            last_monitor_candle: int = -999

            # Process candle by candle (anti-lookahead!)
            for i in range(100, total_candles):  # Mulai dari candle 100 (min VP)
                candles_so_far = all_candles[0:i + 1]
                current_candle = all_candles[i]

                # Progress update setiap 500 candle
                if i % 500 == 0:
                    pct = int(i / total_candles * 100)
                    self._mongo.update_backtest_run(run_id, {
                        "progress_pct": pct,
                        "current_candle": i,
                        "trades_found": len(virtual_trades),
                    })
                    logger.info("Backtest progress: %d/%d (%d%%)", i, total_candles, pct)

                # Hitung VP & Sweep dari candles_so_far SAJA
                vp_result = self._vp_agent.analyze(candles_so_far)
                sweep_result = self._ls_agent.analyze(candles_so_far)

                session = detect_session(current_candle.get("time", datetime.now(timezone.utc)))

                # --- Jika ada virtual position ---
                if virtual_position is not None:
                    # Cek SL / TP hit
                    exit_reason = self._check_exit(
                        virtual_position, current_candle, all_candles, i
                    )

                    if exit_reason:
                        # Tutup posisi
                        virtual_position["closed_at_candle"] = i
                        virtual_position["exit_reason"] = exit_reason
                        virtual_position["exit_price"] = float(current_candle["close"])
                        virtual_position["exit_time"] = current_candle.get("time")

                        # Hitung PnL
                        pnl = self._calculate_pnl(virtual_position)
                        virtual_position["pnl"] = pnl
                        current_balance += pnl
                        virtual_position["balance_after"] = current_balance

                        virtual_trades.append(virtual_position)
                        equity_curve.append({
                            "candle_index": i,
                            "equity": current_balance,
                            "event": f"close_{exit_reason}",
                        })

                        logger.info(
                            "Backtest: CLOSE trade #%d at candle %d reason=%s pnl=%.2f",
                            len(virtual_trades), i, exit_reason, pnl,
                        )

                        virtual_position = None
                    else:
                        # Monitor posisi (LLM, tapi rate-limited)
                        should_monitor = (
                            (i - last_monitor_candle) >= MONITOR_INTERVAL
                            or self._has_opposite_sweep(virtual_position, sweep_result)
                        )

                        if should_monitor:
                            last_monitor_candle = i
                            try:
                                decision = await self._virtual_monitor(
                                    virtual_position, candles_so_far, vp_result, sweep_result
                                )
                                virtual_position.setdefault("monitoring_log", []).append({
                                    "candle_index": i,
                                    "decision": decision.get("decision"),
                                    "reasoning": decision.get("reasoning", ""),
                                    "price_at_decision": float(current_candle["close"]),
                                })

                                # Eksekusi virtual
                                if decision.get("decision") == "move_sl":
                                    new_sl = decision.get("new_sl")
                                    if new_sl:
                                        virtual_position["sl"] = float(new_sl)
                                elif decision.get("decision") == "close_all":
                                    # Close via monitor decision
                                    virtual_position["closed_at_candle"] = i
                                    virtual_position["exit_reason"] = "llm_close_all"
                                    virtual_position["exit_price"] = float(current_candle["close"])
                                    virtual_position["exit_time"] = current_candle.get("time")
                                    pnl = self._calculate_pnl(virtual_position)
                                    virtual_position["pnl"] = pnl
                                    current_balance += pnl
                                    virtual_position["balance_after"] = current_balance
                                    virtual_trades.append(virtual_position)
                                    virtual_position = None
                                    equity_curve.append({
                                        "candle_index": i,
                                        "equity": current_balance,
                                        "event": "close_llm",
                                    })
                            except Exception as e:
                                logger.error("Backtest monitor error at candle %d: %s", i, e)

                    # Update equity curve (holding)
                    if virtual_position is not None:
                        unrealized = self._calculate_unrealized_pnl(
                            virtual_position, float(current_candle["close"])
                        )
                        equity_curve.append({
                            "candle_index": i,
                            "equity": current_balance + unrealized,
                            "event": "hold",
                        })

                # --- Jika tidak ada virtual position ---
                else:
                    try:
                        eval_result = await self._evaluator.evaluate(
                            vp_result, sweep_result, candles_so_far, session
                        )

                        if eval_result.get("is_valid") and eval_result.get("confidence", 0) >= 60:
                            # Buka virtual position
                            virtual_position = self._create_virtual_position(
                                eval_result, current_candle, i
                            )
                            equity_curve.append({
                                "candle_index": i,
                                "equity": current_balance,
                                "event": f"open_{eval_result.get('direction', 'N/A')}",
                            })
                            logger.info(
                                "Backtest: OPEN %s at candle %d price=%.4f",
                                eval_result.get("direction"), i,
                                virtual_position["entry_price"],
                            )
                    except Exception as e:
                        logger.error("Backtest eval error at candle %d: %s", i, e)

                    equity_curve.append({
                        "candle_index": i,
                        "equity": current_balance,
                        "event": "scan",
                    })

            # --- Backtest selesai ---
            # Tutup posisi yang masih terbuka di akhir
            if virtual_position is not None:
                virtual_position["closed_at_candle"] = total_candles - 1
                virtual_position["exit_reason"] = "end_of_data"
                virtual_position["exit_price"] = float(all_candles[-1]["close"])
                virtual_position["exit_time"] = all_candles[-1].get("time")
                pnl = self._calculate_pnl(virtual_position)
                virtual_position["pnl"] = pnl
                virtual_trades.append(virtual_position)

            # Generate stats
            stats = generate_stats(virtual_trades, initial_balance, equity_curve)

            # Simpan ke MongoDB
            self._mongo.update_backtest_run(run_id, {
                "status": "completed",
                "progress_pct": 100,
                "trades_found": len(virtual_trades),
                "current_candle": total_candles,
                "stats": stats,
                "trades": virtual_trades,
                "equity_curve": equity_curve,
                "completed_at": datetime.now(timezone.utc),
            })

            logger.info("=" * 60)
            logger.info("Backtest COMPLETED: %d trades, win_rate=%.1f%%, profit_factor=%.2f",
                        stats["total_trades"], stats["win_rate"], stats["profit_factor"])
            logger.info("=" * 60)

        except Exception as e:
            logger.error("Backtest fatal error: %s", e, exc_info=True)
            self._mongo.update_backtest_run(run_id, {
                "status": "error",
                "error": str(e)[:500],
            })
        finally:
            self._mongo.disconnect()
            self._mt5.disconnect()
            await self._llm.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_historical_candles(self, symbol: str, months_back: int) -> list[dict[str, Any]]:
        """Load historical candles dari MT5."""
        import MetaTrader5 as mt5

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=months_back * 30)

        tf = mt5.TIMEFRAME_M15
        rates = mt5.copy_rates_range(symbol, tf, start, end)

        if rates is None or len(rates) == 0:
            logger.error("Backtest: tidak ada data historical untuk %s", symbol)
            return []

        result: list[dict[str, Any]] = []
        for r in rates:
            result.append({
                "time": datetime.fromtimestamp(r["time"], tz=timezone.utc),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "tick_volume": int(r["tick_volume"]),
                "spread": int(r["spread"]) if "spread" in r.dtype.names else 0,
            })
        return result

    def _check_exit(
        self,
        position: dict[str, Any],
        current_candle: dict[str, Any],
        all_candles: list[dict[str, Any]],
        candle_idx: int,
    ) -> str | None:
        """Cek apakah SL atau TP kena di candle ini.

        Candle punya high/low — cek apakah harga menyentuh SL/TP.
        """
        direction = position["direction"]
        sl = position.get("sl", 0)
        tp = position.get("tp", 0)
        high = float(current_candle["high"])
        low = float(current_candle["low"])

        if direction == "BUY":
            if sl > 0 and low <= sl:
                return "sl_hit"
            if tp > 0 and high >= tp:
                return "tp_hit"
        else:
            if sl > 0 and high >= sl:
                return "sl_hit"
            if tp > 0 and low <= tp:
                return "tp_hit"

        return None

    def _calculate_pnl(self, position: dict[str, Any]) -> float:
        """Hitung PnL dalam currency."""
        entry = position.get("entry_price", 0)
        exit_price = position.get("exit_price", 0)
        direction = position.get("direction", "BUY")
        lot_size = position.get("lot_size", 0.01)

        if direction == "BUY":
            pips = (exit_price - entry) * 10000
        else:
            pips = (entry - exit_price) * 10000

        return pips * lot_size * 10  # aproksimasi: 1 pip = $10 per 0.1 lot

    def _calculate_unrealized_pnl(self, position: dict[str, Any], current_price: float) -> float:
        """Hitung unrealized PnL."""
        entry = position.get("entry_price", 0)
        direction = position.get("direction", "BUY")
        lot_size = position.get("lot_size", 0.01)

        if direction == "BUY":
            pips = (current_price - entry) * 10000
        else:
            pips = (entry - current_price) * 10000

        return pips * lot_size * 10

    def _create_virtual_position(
        self,
        signal: dict[str, Any],
        candle: dict[str, Any],
        candle_idx: int,
    ) -> dict[str, Any]:
        """Buat virtual position dari sinyal."""
        return {
            "direction": signal.get("direction", "BUY"),
            "entry_price": float(candle["close"]),
            "sl": signal.get("sl_price", 0),
            "tp": signal.get("tp1_price", 0),
            "tp2": signal.get("tp2_price", 0),
            "lot_size": 0.01,
            "opened_at_candle": candle_idx,
            "opened_at_time": candle.get("time"),
            "confidence": signal.get("confidence", 0),
            "entry_reason": signal.get("entry_reason", ""),
            "session": signal.get("session", ""),
            "monitoring_log": [],
        }

    def _has_opposite_sweep(
        self,
        position: dict[str, Any],
        sweep_result: dict[str, Any],
    ) -> bool:
        """Cek apakah ada sweep berlawanan arah."""
        sweep_dir = sweep_result.get("direction")
        pos_dir = position.get("direction")
        if sweep_dir and pos_dir and sweep_dir != pos_dir:
            candles_since = sweep_result.get("candles_since_sweep", 99)
            return candles_since is not None and candles_since <= 3
        return False

    async def _virtual_monitor(
        self,
        position: dict[str, Any],
        candles: list[dict[str, Any]],
        vp_result: dict[str, Any],
        sweep_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Virtual position monitor — panggil LLM."""
        session = detect_session(datetime.now(timezone.utc))
        atr = calculate_atr(candles, period=14)

        # Build simplified metrics
        current_price = float(candles[-1]["close"])
        entry = position["entry_price"]
        direction = position["direction"]

        if direction == "BUY":
            pnl_pips = (current_price - entry) * 10000
        else:
            pnl_pips = (entry - current_price) * 10000

        floating_pnl = pnl_pips * 0.01 * 10

        if position.get("sl", 0) > 0:
            initial_risk = abs(entry - position["sl"])
        else:
            initial_risk = atr * 1.5

        if initial_risk > 0:
            current_rr = (current_price - entry) * (1 if direction == "BUY" else -1) / initial_risk
        else:
            current_rr = 0.0

        candles_elapsed = len(candles) - position["opened_at_candle"]

        last5 = candles[-5:]
        last5_str = "\n".join([
            f"  [{c['time']}] O={c['open']:.4f} H={c['high']:.4f} L={c['low']:.4f} C={c['close']:.4f}"
            for c in last5
        ])

        system_prompt = """Kamu adalah manajer posisi trading profesional. Evaluasi apakah posisi harus
dihold, SL-nya dipindah, atau ditutup. Respond HANYA dengan JSON."""

        user_prompt = f"""Evaluasi posisi:

Direction: {direction}
Entry: {entry:.4f} | SL: {position.get('sl', 0):.4f} | TP: {position.get('tp', 0):.4f}
Floating PnL: ${floating_pnl:.2f} | R:R: {current_rr:.2f}R | Candles: {candles_elapsed}
ATR: {atr:.4f}

VP: POC={vp_result.get('poc', 0):.4f} VAH={vp_result.get('vah', 0):.4f} VAL={vp_result.get('val', 0):.4f}
Sweep: {sweep_result.get('direction')} (since {sweep_result.get('candles_since_sweep')} candles)
Session: {session}

Last 5 candles:
{last5_str}

Output JSON:
{{"decision": "hold"|"move_sl"|"close_all", "new_sl": float|null, "reasoning": "..."}}"""

        try:
            result = await self._llm.chat_json(system_prompt, user_prompt)
            return result
        except Exception:
            return {"decision": "hold", "new_sl": None, "reasoning": "LLM error — hold"}
