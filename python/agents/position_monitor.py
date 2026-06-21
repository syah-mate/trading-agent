"""
Position Monitor Agent — TASK 3.2
Monitoring posisi aktif via LLM — hold, move_sl, partial_close, atau close_all.

Setiap keputusan disimpan dengan reasoning untuk audit & replay mode.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from core.openrouter_client import OpenRouterClient
from core.mt5_client import calculate_atr, detect_session
from agents.mt5_executor import MT5Executor

logger = logging.getLogger(__name__)

# System prompt untuk position monitor
SYSTEM_PROMPT = """Kamu adalah manajer posisi trading profesional. Evaluasi apakah posisi aktif harus
dihold, SL-nya dipindah, di-partial close, atau ditutup penuh.

Rules manajemen:
1. Jika harga sudah mendekati TP1 (>80% jarak), pertimbangkan move_sl ke entry (breakeven)
2. Jika ada sweep BERLAWANAN arah → pertimbangkan close sebagian atau penuh
3. Jika floating loss > 1R → jangan move_sl menjauh, justru evaluasi close
4. Jika posisi sudah > 20 candle tanpa profit signifikan → pertimbangkan partial_close
5. Jangan terlalu agresif — biarkan trade berjalan jika konteks mendukung

Berikan keputusan berdasarkan Price Action, Volume Profile, dan manajemen risiko.
Respond HANYA dengan JSON, tidak ada teks lain."""


class PositionMonitorAgent:
    """Agent untuk monitoring & manajemen posisi aktif via LLM.

    Usage:
        agent = PositionMonitorAgent(llm_client, executor)
        decision = await agent.monitor(position, candles, vp_result, sweep_result)
    """

    def __init__(self, llm_client: OpenRouterClient, executor: MT5Executor) -> None:
        self._llm = llm_client
        self._executor = executor

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def monitor(
        self,
        position: dict[str, Any],
        candles: list[dict[str, Any]],
        vp_result: dict[str, Any],
        sweep_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Monitor posisi aktif & berikan keputusan manajemen.

        Args:
            position: data posisi aktif (dari MT5Client.get_open_positions)
            candles: list candle OHLCV (minimal 100)
            vp_result: hasil VolumeProfileAgent.analyze()
            sweep_result: hasil LiquiditySweepAgent.analyze()

        Returns:
            dict: {decision, new_sl, new_tp, close_percentage, reasoning,
                   executed, execution_error, monitored_at}
        """
        now = datetime.now(timezone.utc)

        # Step 1: Hitung metrics
        metrics = self._calculate_metrics(position, candles)

        # Step 2: Cek kondisi ekstrem tanpa LLM (fast path)
        fast_decision = self._check_extreme_conditions(position, metrics, sweep_result)
        if fast_decision:
            fast_decision["monitored_at"] = now
            fast_decision["executed"] = False
            fast_decision["execution_error"] = None
            return self._execute_decision(fast_decision, position)

        # Step 3: Kirim ke LLM
        session = detect_session(now)
        user_prompt = self._build_user_prompt(position, metrics, vp_result, sweep_result, candles, session)

        try:
            llm_result = await self._llm.chat_json(SYSTEM_PROMPT, user_prompt)
        except (ValueError, Exception) as e:
            logger.error("PositionMonitor: LLM call gagal — %s", e)
            llm_result = {
                "decision": "hold",
                "new_sl": None,
                "new_tp": None,
                "close_percentage": None,
                "reasoning": f"LLM error — hold by default: {str(e)[:100]}",
            }

        decision: dict[str, Any] = {
            "decision": llm_result.get("decision", "hold"),
            "new_sl": llm_result.get("new_sl"),
            "new_tp": llm_result.get("new_tp"),
            "close_percentage": llm_result.get("close_percentage"),
            "reasoning": llm_result.get("reasoning", ""),
            "monitored_at": now,
            "executed": False,
            "execution_error": None,
            "metrics": metrics,
            "session": session,
        }

        # Validasi
        decision = self._validate_decision(decision, position)

        # Step 4: Eksekusi
        return self._execute_decision(decision, position)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _calculate_metrics(
        self,
        position: dict[str, Any],
        candles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Hitung metrics posisi aktif."""
        direction = 1 if position.get("type") in (0, "BUY") else -1
        entry_price = float(position.get("price_open", 0))
        sl = float(position.get("sl", 0))
        tp = float(position.get("tp", 0))
        volume = float(position.get("volume", 0.01))

        current_price = float(candles[-1]["close"])
        atr = calculate_atr(candles, period=14)

        # Floating PnL (dalam currency — aproksimasi)
        if direction == 1:
            pnl_pips = (current_price - entry_price) * 10000  # asumsi 4-digit forex
        else:
            pnl_pips = (entry_price - current_price) * 10000
        floating_pnl = pnl_pips * volume * 10  # aproksimasi: 1 pip = $10 per 0.1 lot

        # Initial risk
        if sl and sl > 0 and entry_price > 0:
            initial_risk = abs(entry_price - sl)
        else:
            initial_risk = atr * 1.5

        # Current R:R
        if initial_risk > 0:
            current_rr = (current_price - entry_price) * direction / initial_risk
        else:
            current_rr = 0.0

        # Candles elapsed
        opened_at = position.get("time_open")
        if opened_at and isinstance(opened_at, datetime):
            candles_elapsed = 0
            for c in reversed(candles):
                c_time = c.get("time")
                if isinstance(c_time, datetime) and c_time > opened_at:
                    candles_elapsed += 1
        else:
            candles_elapsed = 0

        return {
            "floating_pnl": round(floating_pnl, 2),
            "current_rr": round(current_rr, 4),
            "candles_elapsed": candles_elapsed,
            "current_atr": round(atr, 4),
            "initial_risk": round(initial_risk, 4),
            "current_price": current_price,
        }

    # ------------------------------------------------------------------
    # Extreme conditions (fast path, tanpa LLM)
    # ------------------------------------------------------------------

    def _check_extreme_conditions(
        self,
        position: dict[str, Any],
        metrics: dict[str, Any],
        sweep_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Cek kondisi ekstrem yang bisa diputuskan tanpa LLM.

        Returns:
            decision dict atau None jika perlu LLM.
        """
        # Kondisi: TP sudah sangat dekat → move SL ke entry (breakeven)
        tp = float(position.get("tp", 0))
        entry = float(position.get("price_open", 0))
        current = float(metrics["current_price"])
        direction = 1 if position.get("type") in (0, "BUY") else -1

        if tp > 0 and entry > 0:
            distance_to_tp = abs(tp - current)
            total_distance = abs(tp - entry)
            if total_distance > 0 and distance_to_tp / total_distance < 0.2:
                # Harga sudah >80% menuju TP
                return {
                    "decision": "move_sl",
                    "new_sl": entry,  # breakeven
                    "new_tp": tp,
                    "close_percentage": None,
                    "reasoning": f"Auto: harga sudah dekat TP ({distance_to_tp/total_distance*100:.0f}% tersisa), move SL ke breakeven",
                }

        # Kondisi: floating loss > 2R → close_all
        if metrics["current_rr"] < -2.0:
            return {
                "decision": "close_all",
                "new_sl": None,
                "new_tp": None,
                "close_percentage": 100,
                "reasoning": f"Auto: floating loss > 2R ({metrics['current_rr']:.1f}R), close all",
            }

        # Kondisi: ada sweep berlawanan & floating loss → close_all
        sweep_dir = sweep_result.get("direction")
        pos_dir = "BUY" if direction == 1 else "SELL"
        if sweep_dir and sweep_dir != pos_dir and metrics["current_rr"] < 0:
            candles_since = sweep_result.get("candles_since_sweep", 99)
            if candles_since is not None and candles_since <= 3:
                return {
                    "decision": "close_all",
                    "new_sl": None,
                    "new_tp": None,
                    "close_percentage": 100,
                    "reasoning": f"Auto: sweep berlawanan ({sweep_dir}) saat floating loss, close all",
                }

        return None  # Perlu evaluasi LLM

    # ------------------------------------------------------------------
    # LLM Context Builder
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self,
        position: dict[str, Any],
        metrics: dict[str, Any],
        vp: dict[str, Any],
        sweep: dict[str, Any],
        candles: list[dict[str, Any]],
        session: str,
    ) -> str:
        """Bangun user prompt untuk LLM position monitor."""

        last5 = candles[-5:]
        last5_str = "\n".join([
            f"  [{c['time']}] O={c['open']:.4f} H={c['high']:.4f} L={c['low']:.4f} C={c['close']:.4f}"
            for c in last5
        ])

        pos_type_str = "BUY" if position.get("type") in (0, "BUY") else "SELL"

        return f"""Evaluasi posisi aktif:

=== POSITION ===
Direction: {pos_type_str}
Entry: {position.get('price_open', 0):.4f}
Current SL: {position.get('sl', 0):.4f}
Current TP: {position.get('tp', 0):.4f}
Volume: {position.get('volume', 0.01)}
Ticket: {position.get('ticket')}

=== METRICS ===
Floating PnL: ${metrics.get('floating_pnl', 0):.2f}
Current R:R: {metrics.get('current_rr', 0):.2f}R
Candles Elapsed: {metrics.get('candles_elapsed', 0)}
ATR(14): {metrics.get('current_atr', 0):.4f}

=== VOLUME PROFILE (TERBARU) ===
POC: {vp.get('poc', 0):.4f}
VAH: {vp.get('vah', 0):.4f}
VAL: {vp.get('val', 0):.4f}

=== LIQUIDITY SWEEP (TERBARU) ===
Sweep: {sweep.get('sweep_detected')}
Direction: {sweep.get('direction')}
Level: {sweep.get('sweep_level', 0):.4f}
Candles Since: {sweep.get('candles_since_sweep')}

=== MARKET CONTEXT ===
Session: {session}
Current Price: {metrics.get('current_price', 0):.4f}

=== LAST 5 CANDLES ===
{last5_str}

Putuskan: hold / move_sl / partial_close / close_all?
Output JSON:
{{
  "decision": "hold" | "move_sl" | "partial_close" | "close_all",
  "new_sl": float atau null,
  "new_tp": float atau null,
  "close_percentage": int atau null,
  "reasoning": "ALASAN LENGKAP, minimal 1 kalimat"
}}"""

    # ------------------------------------------------------------------
    # Validation & Execution
    # ------------------------------------------------------------------

    def _validate_decision(
        self,
        decision: dict[str, Any],
        position: dict[str, Any],
    ) -> dict[str, Any]:
        """Validasi decision dari LLM sebelum eksekusi."""
        valid_decisions = {"hold", "move_sl", "partial_close", "close_all"}

        if decision.get("decision") not in valid_decisions:
            logger.warning("PositionMonitor: decision tidak valid '%s', fallback ke hold", decision.get("decision"))
            decision["decision"] = "hold"

        # Pastikan new_sl/new_tp valid
        if decision["decision"] == "move_sl":
            new_sl = decision.get("new_sl")
            if new_sl is None or float(new_sl) <= 0:
                decision["decision"] = "hold"
                decision["reasoning"] = (decision.get("reasoning", "") + " [SL invalid, fallback hold]").strip()

        # Partial close: percentage 10-90
        if decision["decision"] == "partial_close":
            pct = decision.get("close_percentage")
            try:
                pct = int(pct)
                if pct < 10 or pct > 90:
                    pct = 50  # default 50%
            except (ValueError, TypeError):
                pct = 50
            decision["close_percentage"] = pct

        if decision["decision"] == "close_all":
            decision["close_percentage"] = 100

        return decision

    def _execute_decision(
        self,
        decision: dict[str, Any],
        position: dict[str, Any],
    ) -> dict[str, Any]:
        """Eksekusi decision via MT5Executor."""
        ticket = int(position.get("ticket", 0))
        decision["executed"] = False
        decision["execution_error"] = None

        d = decision["decision"]

        if d == "hold":
            decision["executed"] = True
            logger.debug("PositionMonitor: hold — ticket=%d", ticket)

        elif d == "move_sl":
            new_sl = float(decision["new_sl"])
            ok = self._executor.modify_sl(ticket, new_sl)
            decision["executed"] = ok
            if not ok:
                decision["execution_error"] = "Gagal modify SL"
            logger.info("PositionMonitor: move_sl ticket=%d new_sl=%.4f ok=%s", ticket, new_sl, ok)

        elif d == "partial_close":
            pct = int(decision.get("close_percentage", 50))
            ok = self._executor.close_position(ticket, percentage=pct)
            decision["executed"] = ok
            if not ok:
                decision["execution_error"] = "Gagal partial close"
            logger.info("PositionMonitor: partial_close ticket=%d pct=%d ok=%s", ticket, pct, ok)

        elif d == "close_all":
            ok = self._executor.close_position(ticket, percentage=100)
            decision["executed"] = ok
            if not ok:
                decision["execution_error"] = "Gagal close all"
            logger.info("PositionMonitor: close_all ticket=%d ok=%s", ticket, ok)

        return decision
