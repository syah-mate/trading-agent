"""
Evaluator Agent — TASK 2.3
Mengevaluasi confluence antara Volume Profile dan Liquidity Sweep via LLM.

Pre-filter sebelum LLM:
- sweep_detected = False → langsung reject
- candles_since_sweep > 5 → langsung reject (sinyal basi)
- Session Asia + bukan pair Asia → warning, tapi tetap lanjut
"""

import logging
from datetime import datetime, timezone
from typing import Any

from core.openrouter_client import OpenRouterClient
from core.mt5_client import calculate_atr

logger = logging.getLogger(__name__)

# System prompt untuk evaluator
SYSTEM_PROMPT = """Kamu adalah evaluator trading profesional yang ahli dalam Volume Profile dan Liquidity Sweep.
Tugasmu mengevaluasi apakah ada confluence yang valid untuk entry.

Rules evaluasi:
1. Sweep harus FRESH — candles_since_sweep <= 5
2. Entry valid jika harga saat ini dekat dengan POC atau Value Area boundary
3. Konfirmasi dari HVN/LVN zones memperkuat sinyal
4. SL dan TP harus LOGIS — jangan terlalu sempit atau terlalu lebar
5. Jika ragu atau tidak jelas, SET is_valid=false

SL logic:
- BUY: SL di bawah sweep_low - ATR*0.5
- SELL: SL di atas sweep_high + ATR*0.5

TP logic:
- TP1: POC (target pertama)
- TP2: VAH (untuk BUY) atau VAL (untuk SELL)

Respond HANYA dengan JSON, tidak ada teks lain, tidak ada markdown."""


class EvaluatorAgent:
    """Agent untuk evaluasi confluence sinyal trading via LLM (OpenRouter).

    Usage:
        agent = EvaluatorAgent(llm_client)
        result = await agent.evaluate(vp_result, sweep_result, candles, session)
    """

    def __init__(self, llm_client: OpenRouterClient) -> None:
        self._llm = llm_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        vp_result: dict[str, Any],
        sweep_result: dict[str, Any],
        candles: list[dict[str, Any]],
        session: str,
    ) -> dict[str, Any]:
        """Evaluasi sinyal, kirim ke LLM jika pre-filter lolos.

        Args:
            vp_result: hasil dari VolumeProfileAgent.analyze()
            sweep_result: hasil dari LiquiditySweepAgent.analyze()
            candles: list candle OHLCV (minimal 100)
            session: 'London' / 'New York' / 'Overlap' / 'Asia' / 'Other'

        Returns:
            dict dengan keys:
                is_valid, confidence, direction, entry_reason,
                sl_price, tp1_price, tp2_price, rejection_reason,
                evaluated_at, session, atr
        """
        now = datetime.now(timezone.utc)
        atr = calculate_atr(candles, period=14)

        # --- Pre-filter sebelum LLM ---
        base_result = {
            "evaluated_at": now,
            "session": session,
            "atr": atr,
        }

        # Filter 1: Tidak ada sweep
        if not sweep_result.get("sweep_detected"):
            logger.info("Evaluator: skip — tidak ada sweep terdeteksi")
            return {
                **base_result,
                "is_valid": False,
                "confidence": 0,
                "direction": None,
                "entry_reason": "",
                "sl_price": None,
                "tp1_price": None,
                "tp2_price": None,
                "rejection_reason": "Tidak ada liquidity sweep terdeteksi",
            }

        # Filter 2: Sweep terlalu lama
        candles_since = sweep_result.get("candles_since_sweep")
        if candles_since is not None and candles_since > 5:
            logger.info("Evaluator: skip — sweep sudah %d candle lalu (basi)", candles_since)
            return {
                **base_result,
                "is_valid": False,
                "confidence": 0,
                "direction": None,
                "entry_reason": "",
                "sl_price": None,
                "tp1_price": None,
                "tp2_price": None,
                "rejection_reason": f"Sweep sudah basi ({candles_since} candle lalu)",
            }

        # Filter 3: Session Asia → tetap evaluasi tapi confidence mungkin rendah
        if session == "Asia":
            logger.info("Evaluator: session Asia — tetap evaluasi dengan catatan")

        # --- Kirim ke LLM ---
        user_prompt = self._build_user_prompt(vp_result, sweep_result, candles, session, atr)

        try:
            llm_result = await self._llm.chat_json(SYSTEM_PROMPT, user_prompt)
        except (ValueError, Exception) as e:
            logger.error("Evaluator: LLM call gagal — %s", e)
            return {
                **base_result,
                "is_valid": False,
                "confidence": 0,
                "direction": None,
                "entry_reason": "",
                "sl_price": None,
                "tp1_price": None,
                "tp2_price": None,
                "rejection_reason": f"LLM error: {str(e)[:200]}",
            }

        # Merge dengan base_result
        result = {**base_result, **llm_result}

        # Validasi output LLM
        result = self._validate_llm_output(result)

        logger.info(
            "Evaluator: direction=%s confidence=%d valid=%s",
            result.get("direction"), result.get("confidence"), result.get("is_valid"),
        )

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self,
        vp: dict[str, Any],
        sweep: dict[str, Any],
        candles: list[dict[str, Any]],
        session: str,
        atr: float,
    ) -> str:
        """Bangun user prompt dengan semua context untuk LLM."""

        # Last 5 candles context
        last5 = candles[-5:]
        last5_str = "\n".join([
            f"  [{c['time']}] O={c['open']:.4f} H={c['high']:.4f} L={c['low']:.4f} C={c['close']:.4f} V={c['tick_volume']}"
            for c in last5
        ])

        # HVN / LVN zones
        hvn = ", ".join([f"{z:.4f}" for z in vp.get("hvn_zones", [])[:5]]) or "none"
        lvn = ", ".join([f"{z:.4f}" for z in vp.get("lvn_zones", [])[:5]]) or "none"

        # SL context
        sweep_level = sweep.get("sweep_level", 0.0)
        if sweep.get("direction") == "BUY":
            suggested_sl = round(sweep_level - atr * 0.5, 4)
            tp1 = round(vp.get("poc", 0.0), 4)
            tp2 = round(vp.get("vah", 0.0), 4)
        else:
            suggested_sl = round(sweep_level + atr * 0.5, 4)
            tp1 = round(vp.get("poc", 0.0), 4)
            tp2 = round(vp.get("val", 0.0), 4)

        return f"""Evaluasi trading signal berikut:

=== VOLUME PROFILE ===
POC: {vp.get('poc', 0):.4f}
VAH (Value Area High): {vp.get('vah', 0):.4f}
VAL (Value Area Low): {vp.get('val', 0):.4f}
HVN Zones: [{hvn}]
LVN Zones: [{lvn}]
Total Volume: {vp.get('total_volume', 0):.0f}
Candle Count: {vp.get('candle_count', 0)}

=== LIQUIDITY SWEEP ===
Sweep Detected: {sweep.get('sweep_detected')}
Direction: {sweep.get('direction')}
Sweep Level: {sweep.get('sweep_level', 0):.4f}
Swing High: {sweep.get('swing_high', 0):.4f}
Swing Low: {sweep.get('swing_low', 0):.4f}
Current Price: {sweep.get('current_price', 0):.4f}
Candles Since Sweep: {sweep.get('candles_since_sweep')}

=== MARKET CONTEXT ===
Session: {session}
ATR(14): {atr:.4f}

=== LAST 5 CANDLES ===
{last5_str}

=== SUGGESTED SL/TP (gunakan sebagai referensi) ===
Suggested SL: {suggested_sl:.4f}
TP1 (POC): {tp1:.4f}
TP2: {tp2:.4f}

Evaluasi apakah ini valid entry. Output JSON:
{{
  "is_valid": true/false,
  "confidence": 0-100,
  "direction": "BUY" atau "SELL" atau null,
  "entry_reason": "alasan singkat",
  "sl_price": float atau null,
  "tp1_price": float atau null,
  "tp2_price": float atau null,
  "rejection_reason": "alasan reject" atau null
}}"""

    def _validate_llm_output(self, result: dict[str, Any]) -> dict[str, Any]:
        """Validasi & sanitasi output dari LLM.

        Rules:
        - confidence harus integer 0-100
        - is_valid harus bool
        - direction harus BUY/SELL/null
        - SL/TP harus float yang masuk akal
        """
        # confidence
        try:
            result["confidence"] = int(result.get("confidence", 0))
            result["confidence"] = max(0, min(100, result["confidence"]))
        except (ValueError, TypeError):
            result["confidence"] = 0

        # is_valid
        result["is_valid"] = bool(result.get("is_valid", False))

        # direction
        direction = result.get("direction")
        if direction not in ("BUY", "SELL", None):
            result["direction"] = None

        # SL / TP validation — pastikan float
        for field in ("sl_price", "tp1_price", "tp2_price"):
            val = result.get(field)
            if val is not None:
                try:
                    result[field] = float(val)
                except (ValueError, TypeError):
                    result[field] = None

        # Jika tidak valid, hapus SL/TP untuk keamanan
        if not result["is_valid"]:
            result["sl_price"] = None
            result["tp1_price"] = None
            result["tp2_price"] = None
            result["direction"] = None
            if not result.get("rejection_reason"):
                result["rejection_reason"] = "LLM menilai sinyal tidak valid"

        return result
