"""
Backtest Engine v3.0 — Sinkron dengan Live Trading

Menggunakan TradingAgent & rules yang SAMA dengan live trading:
- Timeframe: M5 (default)
- Session filter: hanya London, New York, Overlap
- Eval interval: setiap 1 candle M5
- Daily loss limit: max -10% per hari
- Max 2 trade per sesi per hari
- Candle window: 200 candle terakhir (hemat token LLM)

Support: days_back dan months_back.
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
from core.sr_detector import SRDetector
from agents.trading_agent import TradingAgent
from backtest.reporter import generate_stats

logger = logging.getLogger(__name__)

# Session yang valid untuk entry (sinkron dengan orchestrator._is_valid_session)
VALID_SESSIONS = {"London", "New York", "Overlap"}


def _downsample_m5_to_m15(candles: list[dict]) -> list[dict]:
    """Downsample candle M5 ke M15 berdasarkan boundary 15 menit.

    Salinan dari TradingAgent._downsample_to_m15 — diekstrak sebagai
    standalone function agar bisa dipakai di backtest tanpa import agent.
    """
    from collections import defaultdict
    from datetime import datetime as _dt

    if len(candles) < 3:
        return candles

    groups: dict[tuple, list[dict]] = defaultdict(list)

    for candle in candles:
        dt = candle.get("time")
        if isinstance(dt, str):
            try:
                dt = _dt.fromisoformat(dt.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
        if dt is None:
            continue

        slot_minute = (dt.minute // 15) * 15
        key = (dt.year, dt.month, dt.day, dt.hour, slot_minute)
        groups[key].append(candle)

    m15: list[dict] = []
    for key in sorted(groups.keys()):
        chunk = groups[key]
        if not chunk:
            continue
        chunk_sorted = sorted(
            chunk,
            key=lambda c: c["time"].isoformat() if hasattr(c.get("time"), "isoformat") else str(c.get("time", "")),
        )
        m15.append({
            "time": chunk_sorted[0]["time"],
            "open": float(chunk_sorted[0]["open"]),
            "high": max(float(c["high"]) for c in chunk_sorted),
            "low": min(float(c["low"]) for c in chunk_sorted),
            "close": float(chunk_sorted[-1]["close"]),
            "tick_volume": sum(int(c.get("tick_volume", 0)) for c in chunk_sorted),
        })

    return m15


class BacktestEngine:
    """Backtest engine v3.0 — single agent, sinkron dengan live trading.

    Perubahan dari v2.0:
    - Timeframe default M5 (bukan M15)
    - Session filter aktif (hanya London, NY, Overlap)
    - Eval interval = 1 candle (sinkron dengan live)
    - Daily loss limit enforcement
    """

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
        timeframe: str = "M5",        # ← default M5, sinkron dengan live
        initial_capital: float = 10000.0,
    ) -> None:
        """Jalankan backtest.

        Args:
            run_id: MongoDB _id untuk backtest run record
            symbol: simbol trading
            months_back: berapa bulan ke belakang (prioritas)
            days_back: berapa hari ke belakang (jika months_back=None)
            timeframe: timeframe candle (default M5)
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
        logger.info("Backtest v3.0: run_id=%s symbol=%s period=%s", run_id, symbol, period_label)
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

        # Baca trading params dari MongoDB config
        from config import LOT_FIX, TP_MODE, TP_PIPS, SL_MODE, SL_PIPS, XAUUSD_PIP_VALUE

        lot_fix  = float(config.get("lot_fix",  LOT_FIX))
        tp_mode  = str(config.get("tp_mode",  TP_MODE)).lower()
        tp_pips  = float(config.get("tp_pips",  TP_PIPS))
        sl_mode  = str(config.get("sl_mode",  SL_MODE)).lower()
        sl_pips  = float(config.get("sl_pips",  SL_PIPS))
        pip_val  = XAUUSD_PIP_VALUE  # 0.10

        logger.info(
            "Backtest params: lot=%.2f | TP=%s(%.1f pip) | SL=%s(%.1f pip)",
            lot_fix, tp_mode, tp_pips, sl_mode, sl_pips,
        )

        # Baca timeframe dari MongoDB config jika tidak di-override caller
        # Priority: parameter caller → MongoDB config → default "M5"
        if timeframe == "M5":  # hanya override jika masih default
            timeframe = config.get("timeframe", "M5").upper()

        # Baca max_daily_loss_pct dari MongoDB config
        max_daily_loss_pct = float(config.get("max_daily_loss_pct", 10.0))  # default 10%

        logger.info("Backtest: timeframe=%s max_daily_loss_pct=%.1f%%", timeframe, max_daily_loss_pct)

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

            # S/R Detector — sinkron dengan live trading
            sr_detector = SRDetector()
            SR_WARMUP_CANDLES = 50  # butuh minimal 50 candle M15 untuk inisialisasi S/R levels

            # Daily loss tracking
            daily_pnl: dict[str, float] = {}       # key: "YYYY-MM-DD", value: total PnL hari itu
            daily_trade_count: dict[str, int] = {}  # key: "YYYY-MM-DD:SESSION", value: trade count

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

                # Ambil slice candle — batasi 200 candle terakhir untuk hemat token LLM
                candles_window = all_candles[max(0, i - 199): i + 1]
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

                        # Update daily PnL tracker
                        exit_time = current_candle.get("time")
                        exit_date_key = exit_time.strftime("%Y-%m-%d") if isinstance(exit_time, datetime) else str(exit_time)[:10]
                        daily_pnl[exit_date_key] = daily_pnl.get(exit_date_key, 0.0) + pnl

                        virtual_trades.append(virtual_position)
                        equity_curve.append({"candle_index": i, "equity": current_balance, "event": f"close_{exit_reason}"})
                        # Format exit time untuk log
                        et = virtual_position.get("exit_time")
                        et_str = et.strftime("%Y-%m-%d %H:%M UTC") if isinstance(et, datetime) else str(et) if et else "?"
                        pnl_sign = "+" if pnl >= 0 else ""
                        logger.info(
                            "Backtest: %s CLOSE #%d | %s | Exit=%.4f | PnL=%s%.2f USD | Balance=%.2f | candle %d [%s]",
                            "🟢" if pnl >= 0 else "🔴",
                            len(virtual_trades),
                            "TP HIT" if exit_reason == "tp_hit" else "SL HIT" if exit_reason == "sl_hit" else exit_reason.upper(),
                            virtual_position["exit_price"],
                            pnl_sign, pnl,
                            current_balance, i, et_str,
                        )
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
                    else:
                        unrealized = self._calc_unrealized_pnl(virtual_position, float(current_candle["close"]))
                        equity_curve.append({"candle_index": i, "equity": current_balance + unrealized, "event": "hold"})
                else:
                    # ── SESSION FILTER ──
                    if session not in VALID_SESSIONS:
                        equity_curve.append({"candle_index": i, "equity": current_balance, "event": "skip_session"})
                        continue

                    # ── DAILY LOSS GUARD ──
                    candle_time = current_candle.get("time")
                    date_key = candle_time.strftime("%Y-%m-%d") if isinstance(candle_time, datetime) else str(candle_time)[:10]
                    today_pnl = daily_pnl.get(date_key, 0.0)
                    daily_loss_limit = -(initial_capital * max_daily_loss_pct / 100.0)

                    if today_pnl <= daily_loss_limit:
                        equity_curve.append({"candle_index": i, "equity": current_balance, "event": "skip_daily_loss"})
                        continue

                    # ── MAX TRADE PER SESSION GUARD ──
                    session_day_key = f"{date_key}:{session}"
                    trades_this_session = daily_trade_count.get(session_day_key, 0)
                    if trades_this_session >= 2:
                        equity_curve.append({"candle_index": i, "equity": current_balance, "event": "skip_max_trades"})
                        continue

                    # ── UPDATE S/R DETECTOR (setiap candle, gratis — tidak pakai AI) ──
                    if i >= SR_WARMUP_CANDLES:
                        m15_candles = _downsample_m5_to_m15(candles_window)
                        sr_detector.update(m15_candles)

                    # ── CEK APAKAH HARGA MENYENTUH S/R FRESH ──
                    current_price_close = float(current_candle["close"])
                    current_price_high  = float(current_candle["high"])
                    current_price_low   = float(current_candle["low"])

                    touched_by_high = sr_detector.check_touch(current_price_high, candle_time=candle_time)
                    touched_by_low  = sr_detector.check_touch(current_price_low,  candle_time=candle_time)
                    all_touched = touched_by_high + touched_by_low

                    if not all_touched:
                        equity_curve.append({"candle_index": i, "equity": current_balance, "event": "scan"})
                        continue

                    # ── S/R DISENTUH → CALL AI UNTUK VALIDASI ──
                    sr_level = min(all_touched, key=lambda lv: abs(lv.price - current_price_close))

                    # Format candle time untuk log
                    ct = current_candle.get("time")
                    ct_str = ct.strftime("%Y-%m-%d %H:%M UTC") if isinstance(ct, datetime) else str(ct)

                    logger.info(
                        "Backtest: SR TOUCH candle=%d [%s] price_range=[%.4f,%.4f] level=%.4f (%s) — calling AI...",
                        i, ct_str, current_price_low, current_price_high, sr_level.price, sr_level.kind,
                    )

                    try:
                        atr = calculate_atr(candles_window, period=14)
                        agent_result = await self._agent.analyze(
                            candles=candles_window,
                            position=None,
                            session=session,
                            atr=atr,
                            symbol=symbol,
                            balance=current_balance,
                            risk_percent=1.0,
                            sr_level=sr_level.to_dict(),
                        )

                        decision = agent_result.get("decision", "STANDBY")
                        confidence = agent_result.get("confidence", 0)

                        if decision == "ENTRY" and confidence >= 60:
                            direction = "BUY" if sr_level.kind == "support" else "SELL"
                            agent_result["direction"] = direction
                            agent_result["entry_price"] = current_price_close

                            virtual_position = self._create_virtual_position(
                                agent_result, current_candle, i,
                                trading_params={
                                    "lot_fix": lot_fix, "tp_mode": tp_mode, "tp_pips": tp_pips,
                                    "sl_mode": sl_mode, "sl_pips": sl_pips,
                                },
                            )
                            equity_curve.append({
                                "candle_index": i,
                                "equity": current_balance,
                                "event": f"open_{direction}",
                            })
                            logger.info(
                                "Backtest: 🔵 OPEN %s | Entry=%.4f | SL=%.4f | TP=%.4f | Conf=%d | candle %d [%s]",
                                direction, current_price_close,
                                virtual_position["sl"], virtual_position["tp"],
                                confidence, i, ct_str,
                            )
                            daily_trade_count[session_day_key] = trades_this_session + 1
                        else:
                            logger.info(
                                "Backtest: AI STANDBY at candle %d — %s",
                                i, agent_result.get("reason", ""),
                            )
                            equity_curve.append({"candle_index": i, "equity": current_balance, "event": "standby"})

                    except Exception as e:
                        logger.error("Backtest agent error at candle %d: %s", i, e)
                        equity_curve.append({"candle_index": i, "equity": current_balance, "event": "error"})

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

    def _create_virtual_position(
        self,
        agent_result: dict[str, Any],
        candle: dict[str, Any],
        candle_idx: int,
        trading_params: dict,          # ← parameter baru
    ) -> dict[str, Any]:
        direction   = agent_result.get("direction", "BUY")
        entry_price = float(agent_result.get("entry_price") or candle["close"])
        lot_fix     = trading_params["lot_fix"]
        tp_mode     = trading_params["tp_mode"]
        tp_pips     = trading_params["tp_pips"]
        sl_mode     = trading_params["sl_mode"]
        sl_pips     = trading_params["sl_pips"]
        pip_val     = 0.10  # XAUUSD_PIP_VALUE

        # ── TP ────────────────────────────────────────────────────────────────────
        if tp_mode == "fixed":
            tp_distance = tp_pips * pip_val
            if direction == "BUY":
                tp_price = round(entry_price + tp_distance, 5)
            else:
                tp_price = round(entry_price - tp_distance, 5)
        else:
            # tp_mode == "ai": pakai dari agent_result jika ada
            tp_price = float(agent_result.get("tp1_price") or 0)
            if tp_price == 0:
                # Fallback ke fixed jika AI tidak berikan TP
                tp_distance = tp_pips * pip_val
                tp_price = round(entry_price + tp_distance if direction == "BUY" else entry_price - tp_distance, 5)

        # ── SL ────────────────────────────────────────────────────────────────────
        if sl_mode == "fixed":
            sl_distance = sl_pips * pip_val
            if direction == "BUY":
                sl_price = round(entry_price - sl_distance, 5)
            else:
                sl_price = round(entry_price + sl_distance, 5)
        else:
            # sl_mode == "ai": pakai dari agent_result jika ada
            sl_price = float(agent_result.get("sl_price") or 0)
            if sl_price == 0:
                # Fallback ke ATR jika AI tidak berikan SL
                atr = agent_result.get("atr", 0.5)
                sl_distance = atr * 1.2
                if direction == "BUY":
                    sl_price = round(entry_price - sl_distance, 5)
                else:
                    sl_price = round(entry_price + sl_distance, 5)

        return {
            "opened_at_candle": candle_idx,
            "entry_price": entry_price,
            "direction": direction,
            "sl": sl_price,
            "tp": tp_price,
            "volume": lot_fix,       # ← dari config, bukan hardcode
            "opened_at": candle.get("time"),
            "entry_reason": agent_result.get("reason", ""),
            "confidence": agent_result.get("confidence", 0),
            "rr_ratio_t1": agent_result.get("rr_ratio_t1"),
            "session": agent_result.get("session", ""),
            "sr_level": agent_result.get("sr_level"),
            "bias_htf": agent_result.get("bias_htf"),
        }

    @staticmethod
    def _calc_pnl(position: dict[str, Any]) -> float:
        """Hitung PnL virtual position dalam USD (XAUUSD).

        Formula: PnL = price_diff × volume × 100
        1 lot XAUUSD = 100 oz, setiap $1 move = $100 per lot.
        """
        d = 1 if position["direction"] == "BUY" else -1
        entry = float(position["entry_price"])
        exit_p = float(position.get("exit_price", entry))
        vol = float(position.get("volume", 0.01))  # dari position, bukan hardcode
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
