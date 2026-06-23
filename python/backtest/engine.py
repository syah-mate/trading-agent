"""
Backtest Engine v2.0 — Single Agent Mode

Menggunakan TradingAgent yang sama dengan live trading.
Setiap 3 candle → evaluasi sinyal via LLM.
Tidak ada position monitoring (menunggu SL/TP saja).

Support: days_back (10, 20, 30, 60, 90, 180) dan months_back (1-6).
"""

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any

from dotenv import load_dotenv

from core.mt5_client import MT5Client, detect_session, calculate_atr
from core.openrouter_client import OpenRouterClient, DEFAULT_MODEL
from core.mongo_client import MongoClient
from agents.trading_agent import TradingAgent
from backtest.reporter import generate_stats

logger = logging.getLogger(__name__)

EVAL_INTERVAL = 3  # Evaluasi setiap N candle


class BacktestEngine:
    """Backtest engine v2.0 — single agent, 3-candle interval."""

    def __init__(self) -> None:
        self._mt5 = MT5Client()
        self._llm = OpenRouterClient()
        self._mongo = MongoClient()
        self._agent = TradingAgent(self._llm)

    async def run(
        self,
        run_id: str,
        symbol: str = "XAUUSD",
        months_back: int | None = None,
        days_back: int | None = None,
        timeframe: str = "M15",
        initial_capital: float = 10000.0,
    ) -> None:
        """Jalankan backtest.

        Args:
            run_id: MongoDB _id untuk backtest run record
            symbol: simbol trading
            months_back: berapa bulan ke belakang (prioritas)
            days_back: berapa hari ke belakang (jika months_back=None)
            timeframe: timeframe candle
            initial_capital: modal awal dalam USD (default $10,000)
        """
        if months_back is not None and months_back > 0:
            period_label = f"{months_back}mo"
            total_days = months_back * 30
        elif days_back is not None and days_back > 0:
            period_label = f"{days_back}d"
            total_days = days_back
        else:
            period_label = "6mo"
            total_days = 180

        logger.info("=" * 60)
        logger.info("Backtest v2.0: run_id=%s symbol=%s period=%s", run_id, symbol, period_label)
        logger.info("=" * 60)

        if not self._mt5.connect():
            self._mongo.update_backtest_run(run_id, {"status": "error", "error": "MT5 connect failed"})
            return
        if not self._mongo.connect():
            self._mongo.update_backtest_run(run_id, {"status": "error", "error": "MongoDB connect failed"})
            return

        # Load LLM model dari user config (terpusat dari /config)
        config = self._mongo.get_config()
        llm_model = config.get("llm_model", DEFAULT_MODEL)
        self._llm.set_model(llm_model)
        logger.info("Backtest: LLM model dari config = %s", llm_model)

        if not self._llm._api_key:
            msg = "OPENROUTER_API_KEY tidak diset di .env"
            self._mongo.update_backtest_run(run_id, {"status": "error", "error": msg})
            return

        self._mongo.update_backtest_run(run_id, {"status": "running", "progress_pct": 0, "current_candle": 0, "trades_found": 0})

        try:
            all_candles = self._load_historical_candles(symbol, total_days, timeframe)
            total_candles = len(all_candles)
            self._mongo.update_backtest_run(run_id, {"progress_pct": 1, "current_candle": 100, "trades_found": 0})

            if total_candles < 120:
                self._mongo.update_backtest_run(run_id, {"status": "error", "error": f"Hanya {total_candles} candle (min 120)"})
                return

            logger.info("Backtest: %d candles loaded", total_candles)

            virtual_trades: list[dict[str, Any]] = []
            virtual_position: dict[str, Any] | None = None
            equity_curve: list[dict[str, Any]] = []
            current_balance = initial_capital
            candles_since_eval = 0

            for i in range(100, total_candles):
                # Cek cancel flag dari MongoDB setiap 10 candle
                if i % 10 == 0 and self._is_cancelled(run_id):
                    logger.info("Backtest: CANCELLED by user at candle %d/%d", i, total_candles)
                    if virtual_position is not None:
                        virtual_position["closed_at_candle"] = i
                        virtual_position["exit_reason"] = "cancelled"
                        virtual_position["exit_price"] = float(all_candles[i]["close"])
                        virtual_position["exit_time"] = all_candles[i].get("time")
                        virtual_position["pnl"] = self._calc_pnl(virtual_position)
                        virtual_trades.append(virtual_position)
                        virtual_position = None
                    partial_stats = generate_stats(virtual_trades, initial_capital, equity_curve)
                    self._mongo.update_backtest_run(run_id, {
                        "status": "cancelled", "progress_pct": int(i / total_candles * 100),
                        "trades_found": len(virtual_trades), "current_candle": i,
                        "stats": partial_stats, "trades": virtual_trades, "equity_curve": equity_curve,
                        "completed_at": datetime.now(timezone.utc), "period": period_label,
                    })
                    return

                candles_so_far = all_candles[0:i + 1]
                current_candle = all_candles[i]

                if i % 30 == 0:
                    pct = int(i / total_candles * 100)
                    self._mongo.update_backtest_run(run_id, {"progress_pct": pct, "current_candle": i, "trades_found": len(virtual_trades)})
                    logger.info("Backtest progress: %d/%d (%d%%)", i, total_candles, pct)

                session = detect_session(current_candle.get("time", datetime.now(timezone.utc)))

                if virtual_position is not None:
                    exit_reason = self._check_exit(virtual_position, current_candle)
                    if exit_reason:
                        virtual_position["closed_at_candle"] = i
                        virtual_position["exit_reason"] = exit_reason
                        # Gunakan level SL/TP sebagai exit price, BUKAN close candle
                        if exit_reason == "sl_hit":
                            virtual_position["exit_price"] = float(virtual_position["sl"])
                        elif exit_reason == "tp_hit":
                            virtual_position["exit_price"] = float(virtual_position["tp"])
                        else:
                            virtual_position["exit_price"] = float(current_candle["close"])
                        virtual_position["exit_time"] = current_candle.get("time")
                        pnl = self._calc_pnl(virtual_position)
                        virtual_position["pnl"] = pnl
                        current_balance += pnl
                        virtual_position["balance_after"] = current_balance
                        virtual_trades.append(virtual_position)
                        equity_curve.append({"candle_index": i, "equity": current_balance, "event": f"close_{exit_reason}"})
                        logger.info("Backtest: CLOSE #%d at candle %d reason=%s exit=%.4f pnl=%.2f", len(virtual_trades), i, exit_reason, virtual_position["exit_price"], pnl)
                        # Margin call check — stop backtest jika equity habis
                        if current_balance <= 0:
                            logger.warning("Backtest: MARGIN CALL — equity depleted at candle %d/%d", i, total_candles)
                            partial_stats = generate_stats(virtual_trades, initial_capital, equity_curve)
                            self._mongo.update_backtest_run(run_id, {
                                "status": "completed", "progress_pct": int(i / total_candles * 100),
                                "trades_found": len(virtual_trades), "current_candle": i,
                                "stats": partial_stats, "trades": virtual_trades, "equity_curve": equity_curve,
                                "completed_at": datetime.now(timezone.utc), "period": period_label,
                                "margin_call": True,
                            })
                            return
                        virtual_position = None
                        candles_since_eval = 0
                    else:
                        unrealized = self._calc_unrealized_pnl(virtual_position, float(current_candle["close"]))
                        equity_curve.append({"candle_index": i, "equity": current_balance + unrealized, "event": "hold"})
                else:
                    candles_since_eval += 1
                    if candles_since_eval >= EVAL_INTERVAL:
                        candles_since_eval = 0
                        try:
                            atr = calculate_atr(candles_so_far, period=14)
                            agent_result = await self._agent.analyze(
                                candles=candles_so_far, position=None,
                                session=session, atr=atr, symbol=symbol,
                                balance=current_balance, risk_percent=1.0,
                            )
                            if agent_result.get("decision") == "ENTRY" and agent_result.get("confidence", 0) >= 60:
                                virtual_position = self._create_virtual_position(agent_result, current_candle, i)
                                equity_curve.append({"candle_index": i, "equity": current_balance, "event": f"open_{agent_result.get('direction', 'N/A')}"})
                                logger.info("Backtest: OPEN %s at candle %d price=%.4f conf=%d", agent_result.get("direction"), i, virtual_position["entry_price"], agent_result.get("confidence", 0))
                        except Exception as e:
                            logger.error("Backtest agent error at candle %d: %s", i, e)
                    equity_curve.append({"candle_index": i, "equity": current_balance, "event": "scan"})

            if virtual_position is not None:
                virtual_position["closed_at_candle"] = total_candles - 1
                virtual_position["exit_reason"] = "end_of_data"
                virtual_position["exit_price"] = float(all_candles[-1]["close"])
                virtual_position["exit_time"] = all_candles[-1].get("time")
                virtual_position["pnl"] = self._calc_pnl(virtual_position)
                virtual_trades.append(virtual_position)

            stats = generate_stats(virtual_trades, initial_capital, equity_curve)
            self._mongo.update_backtest_run(run_id, {
                "status": "completed", "progress_pct": 100,
                "trades_found": len(virtual_trades), "current_candle": total_candles,
                "stats": stats, "trades": virtual_trades, "equity_curve": equity_curve,
                "completed_at": datetime.now(timezone.utc), "period": period_label,
            })
            logger.info("Backtest COMPLETED: %d trades, win_rate=%.1f%%, pf=%.2f", stats["total_trades"], stats["win_rate"], stats["profit_factor"])

        except Exception as e:
            logger.error("Backtest fatal error: %s", e, exc_info=True)
            self._mongo.update_backtest_run(run_id, {"status": "error", "error": str(e)[:500]})
        finally:
            self._mongo.disconnect()
            self._mt5.disconnect()
            await self._llm.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_historical_candles(self, symbol: str, total_days: int, timeframe: str = "M15") -> list[dict[str, Any]]:
        import MetaTrader5 as mt5
        import time as _time
        load_dotenv(override=True)
        if mt5.terminal_info() is None:
            if not mt5.initialize(login=int(os.getenv("MT5_LOGIN", "0")), password=os.getenv("MT5_PASSWORD", ""), server=os.getenv("MT5_SERVER", "")):
                logger.error("Backtest: mt5.initialize() gagal")
                return []
        if not mt5.symbol_select(symbol, True):
            logger.error("Backtest: symbol_select(%s) gagal", symbol)
            return []
        _time.sleep(0.1)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=total_days)
        tf_map = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1, "MN1": mt5.TIMEFRAME_MN1}
        tf = tf_map.get(timeframe.upper(), mt5.TIMEFRAME_M15)
        rates = mt5.copy_rates_range(symbol, tf, start, end)
        if rates is None or len(rates) == 0:
            logger.error("Backtest: tidak ada data historical untuk %s", symbol)
            return []
        result: list[dict[str, Any]] = []
        for r in rates:
            result.append({"time": datetime.fromtimestamp(r["time"], tz=timezone.utc), "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"]), "tick_volume": int(r["tick_volume"]), "spread": int(r["spread"]) if "spread" in r.dtype.names else 0})
        return result

    def _check_exit(self, position: dict[str, Any], current_candle: dict[str, Any]) -> str | None:
        """Cek apakah SL atau TP tersentuh dalam candle ini.

        Jika keduanya tersentuh dalam candle yang sama, gunakan harga OPEN
        untuk menentukan mana yang lebih dulu tercapai (lebih realistis).
        """
        direction = position["direction"]
        sl = position.get("sl", 0)
        tp = position.get("tp", 0)
        open_p = float(current_candle["open"])
        high = float(current_candle["high"])
        low = float(current_candle["low"])

        if direction == "BUY":
            sl_hit = sl > 0 and low <= sl
            tp_hit = tp > 0 and high >= tp
            if sl_hit and tp_hit:
                # Keduanya kena — tentukan mana yang lebih dulu
                dist_to_sl = open_p - sl
                dist_to_tp = tp - open_p
                return "sl_hit" if dist_to_sl >= dist_to_tp else "tp_hit"
            if sl_hit:
                return "sl_hit"
            if tp_hit:
                return "tp_hit"
        else:
            sl_hit = sl > 0 and high >= sl
            tp_hit = tp > 0 and low <= tp
            if sl_hit and tp_hit:
                dist_to_sl = sl - open_p
                dist_to_tp = open_p - tp
                return "sl_hit" if dist_to_sl >= dist_to_tp else "tp_hit"
            if sl_hit:
                return "sl_hit"
            if tp_hit:
                return "tp_hit"
        return None

    def _create_virtual_position(self, agent_result: dict[str, Any], candle: dict[str, Any], candle_idx: int) -> dict[str, Any]:
        direction = agent_result.get("direction")
        entry_price = agent_result.get("entry_price") or float(candle["close"])
        return {
            "direction": direction,
            "entry_price": float(entry_price),
            "sl": float(agent_result.get("sl_price", 0) or 0),
            "tp": float(agent_result.get("tp1_price", 0) or 0),
            "tp2": float(tp2) if (tp2 := agent_result.get("tp2_price")) else None,
            "opened_at_candle": candle_idx,
            "opened_at": candle.get("time"),
            "entry_reason": agent_result.get("reason", ""),
            "bias_htf": agent_result.get("bias_htf"),
            "confidence": agent_result.get("confidence", 0),
            "rr_ratio_t1": agent_result.get("rr_ratio_t1"),
            "rr_ratio_t2": agent_result.get("rr_ratio_t2"),
            "session": agent_result.get("session", "Other"),
            "volume": 0.01,
        }

    @staticmethod
    def _calc_pnl(position: dict[str, Any]) -> float:
        d = 1 if position["direction"] == "BUY" else -1
        entry = float(position["entry_price"])
        exit_p = float(position.get("exit_price", entry))
        vol = float(position.get("volume", 0.01))
        # XAUUSD: 1 lot = 100 oz, 0.01 lot = 1 oz, $1 move = $1
        return ((exit_p - entry) if d == 1 else (entry - exit_p)) * 100 * vol

    def _is_cancelled(self, run_id: str) -> bool:
        """Cek apakah backtest dicancel user via MongoDB status."""
        try:
            run = self._mongo.get_backtest_run(run_id)
            return run is not None and run.get("status") == "cancelling"
        except Exception:
            return False

    @staticmethod
    def _calc_unrealized_pnl(position: dict[str, Any], current_price: float) -> float:
        d = 1 if position["direction"] == "BUY" else -1
        entry = float(position["entry_price"])
        vol = float(position.get("volume", 0.01))
        # XAUUSD: 1 lot = 100 oz, 0.01 lot = 1 oz, $1 move = $1
        return ((current_price - entry) if d == 1 else (entry - current_price)) * 100 * vol
