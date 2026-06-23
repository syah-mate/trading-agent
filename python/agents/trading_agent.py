"""
Trading Agent — SINGLE AI Agent (v2.0)
Menggantikan seluruh multi-agent architecture sebelumnya.

Agent ini membaca trading_agent_system_prompt.md sebagai system prompt,
menganalisis candle data secara langsung via LLM (OpenRouter),
dan memberikan keputusan: ENTRY (BUY/SELL) atau STANDBY.

Tidak ada lagi:
- Volume Profile Agent (terpisah)
- Liquidity Sweep Agent (terpisah)
- Evaluator Agent (terpisah)
- Position Monitor Agent (terpisah)

Semua analisis dilakukan oleh SATU LLM call dengan system prompt lengkap.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from core.openrouter_client import OpenRouterClient
from core.mt5_client import detect_session, calculate_atr

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path ke system prompt markdown
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "trading_agent_system_prompt.md",
)

# ---------------------------------------------------------------------------
# JSON output instruction (appended after system prompt)
# ---------------------------------------------------------------------------
_JSON_INSTRUCTION = """

---
## OUTPUT FORMAT (MANDATORY)

Kamu HARUS merespon HANYA dengan JSON object. Tidak boleh ada teks lain, markdown, atau code fences.

Format JSON:

```json
{
  "decision": "ENTRY" | "STANDBY",
  "direction": "BUY" | "SELL" | "NONE",
  "entry_price": number | null,
  "sl_price": number | null,
  "tp1_price": number | null,
  "tp2_price": number | null,
  "lot_size": number | null,
  "rr_ratio_t1": number | null,
  "rr_ratio_t2": number | null,
  "confidence": number (0-100),
  "bias_htf": "BULLISH" | "BEARISH" | "RANGING",
  "intraday_phase": "TRENDING" | "PULLBACK" | "CONSOLIDATION",
  "reason": "string — alasan singkat (max 300 chars)",
  "invalidation": "string — kondisi yang membatalkan setup ini (max 200 chars)",
  "risk_percent": number
}
```

Jika decision = "STANDBY":
- Isi "reason" dengan alasan jelas (mis. "M15 ranging, tidak ada bias jelas")
- Field lain boleh null/0
- direction boleh "NONE"

Jika decision = "ENTRY":
- SEMUA field wajib diisi
- SL maksimum 10 pip dari entry
- RR T1 minimum 0.8
"""


class TradingAgent:
    """Single AI trading agent — analisis full via LLM dengan system prompt.

    Usage:
        llm = OpenRouterClient()
        agent = TradingAgent(llm)
        decision = await agent.analyze(candles, position=None)
        if decision["decision"] == "ENTRY":
            executor.open_position(decision)
    """

    def __init__(self, llm_client: OpenRouterClient) -> None:
        self._llm = llm_client
        self._system_prompt: str = ""
        self._load_system_prompt()

    # ------------------------------------------------------------------
    # System Prompt Loading
    # ------------------------------------------------------------------

    def _load_system_prompt(self) -> None:
        """Load system prompt dari file markdown + append JSON instruction."""
        try:
            with open(_SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
                base_prompt = f.read()
            self._system_prompt = base_prompt + _JSON_INSTRUCTION
            logger.info(
                "TradingAgent: system prompt loaded (%d chars) from %s",
                len(self._system_prompt), _SYSTEM_PROMPT_PATH,
            )
        except FileNotFoundError:
            logger.error(
                "TradingAgent: system prompt file NOT FOUND at %s — agent will fail!",
                _SYSTEM_PROMPT_PATH,
            )
            self._system_prompt = "You are a trading agent. Respond with JSON."

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze(
        self,
        candles: list[dict[str, Any]],
        position: dict[str, Any] | None = None,
        session: str | None = None,
        atr: float | None = None,
        symbol: str = "XAUUSDc",
        balance: float = 10000.0,
        risk_percent: float = 1.0,
    ) -> dict[str, Any]:
        """Analisis candle data & posisi (jika ada), return keputusan trading.

        Args:
            candles: list candle OHLCV (minimal 100-200 candle)
            position: posisi aktif (None jika tidak ada)
            session: session trading (auto-detect jika None)
            atr: nilai ATR (auto-calculate jika None)
            symbol: simbol trading (default XAUUSDc)
            balance: balance akun saat ini
            risk_percent: risk per trade dalam persen

        Returns:
            dict dengan keys:
                decision, direction, entry_price, sl_price, tp1_price,
                tp2_price, lot_size, rr_ratio_t1, rr_ratio_t2,
                confidence, bias_htf, intraday_phase, reason,
                invalidation, risk_percent, analyzed_at, session, atr
        """
        now = datetime.now(timezone.utc)

        # Auto-detect
        if session is None:
            session = detect_session(now)
        if atr is None:
            atr = calculate_atr(candles, period=14)

        # Build user prompt with candle data
        user_prompt = self._build_user_prompt(
            candles=candles,
            position=position,
            session=session,
            atr=atr,
            symbol=symbol,
            balance=balance,
            risk_percent=risk_percent,
        )

        logger.info(
            "TradingAgent: sending to LLM — %d candles, session=%s, atr=%.4f, has_position=%s",
            len(candles), session, atr, position is not None,
        )

        # Call LLM
        try:
            llm_result = await self._llm.chat_json(
                system_prompt=self._system_prompt,
                user_prompt=user_prompt,
            )
        except (ValueError, Exception) as e:
            logger.error("TradingAgent: LLM call gagal — %s", e)
            return self._fallback_result(now, session, atr, str(e)[:200])

        # Validate & normalize
        result = self._validate_and_normalize(llm_result, now, session, atr)

        logger.info(
            "TradingAgent: decision=%s direction=%s confidence=%d",
            result["decision"], result.get("direction"), result.get("confidence", 0),
        )

        return result

    # ------------------------------------------------------------------
    # User Prompt Builder
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self,
        candles: list[dict[str, Any]],
        position: dict[str, Any] | None,
        session: str,
        atr: float,
        symbol: str,
        balance: float,
        risk_percent: float,
    ) -> str:
        """Build detailed user prompt with OHLCV data for LLM analysis."""

        # M15 candles — downsample dari M5 untuk HTF bias
        m15_candles = self._downsample_to_m15(candles)

        # Last 30 M5 candles (2.5 jam terakhir) — untuk setup entry
        recent_m5 = candles[-30:]
        m5_str = "\n".join([
            f"  [{self._fmt_time(c['time'])}] "
            f"O={c['open']:.2f} H={c['high']:.2f} L={c['low']:.2f} "
            f"C={c['close']:.2f} V={c.get('tick_volume', 0)}"
            for c in recent_m5
        ])

        # Last 20 M15 candles (~5 jam terakhir) — untuk HTF bias
        recent_m15 = m15_candles[-20:] if len(m15_candles) >= 20 else m15_candles
        m15_str = "\n".join([
            f"  [{self._fmt_time(c['time'])}] "
            f"O={c['open']:.2f} H={c['high']:.2f} L={c['low']:.2f} "
            f"C={c['close']:.2f}"
            for c in recent_m15
        ])

        # Key levels dari 100 candle M5 terakhir (~8 jam)
        all_highs = [float(c["high"]) for c in candles[-100:]]
        all_lows = [float(c["low"]) for c in candles[-100:]]
        recent_high = max(all_highs)
        recent_low = min(all_lows)
        current_price = float(candles[-1]["close"])

        # Posisi aktif
        position_str = "TIDAK ADA POSISI AKTIF"
        if position:
            pos_dir = "BUY" if position.get("type") in (0, "BUY") else "SELL"
            pos_entry = position.get("price_open", position.get("entry_price", 0))
            pos_sl = position.get("sl", 0)
            pos_tp = position.get("tp", 0)
            pos_pnl = self._calc_position_pnl(position, current_price)
            position_str = f"""POSISI AKTIF:
  Arah: {pos_dir}
  Entry: {float(pos_entry):.2f}
  SL: {float(pos_sl):.2f}
  TP: {float(pos_tp):.2f}
  Current PnL: {pos_pnl:+.2f} USD"""

        return f"""=== TRADING CONTEXT ===
Symbol: {symbol}
Timeframe: M5 (entry) / M15 (HTF bias)
Session: {session}
Current Price: {current_price:.2f}
ATR (14): {atr:.4f}
Balance: ${balance:,.2f}
Risk per Trade: {risk_percent}%

=== KEY LEVELS (100 candle terakhir) ===
Recent High: {recent_high:.2f}
Recent Low: {recent_low:.2f}
Mid Range: {((recent_high + recent_low) / 2):.2f}

=== M15 CANDLES (HTF Bias - 20 terakhir, hasil downsample M5→M15) ===
{m15_str}

=== M5 CANDLES (Entry TF - 30 terakhir) ===
{m5_str}

=== POSITION STATUS ===
{position_str}

---

Jalankan TOP-DOWN ANALYSIS sesuai system prompt v3.0:
1. FASE 1: Baca struktur M15 → tentukan BIAS (BULLISH/BEARISH) atau RANGING
2. FASE 2: Jika RANGING atau sesi tidak valid → output STANDBY
3. FASE 3: Jika ada bias jelas → cari setup M5 (BoS retest / rejection wick / engulfing)
4. FASE 4: Kalkulasi SL (maks 10 pip) dan TP (min RR 0.8)

INGAT:
- STANDBY diperbolehkan jika kondisi tidak mendukung
- SL TIDAK BOLEH melebihi 10 pip
- Hanya entry di session London (07:00–10:00 UTC) atau NY (12:00–15:00 UTC)
- Modal sangat terbatas ($30) — capital preservation > profit hunting

Respond HANYA dengan JSON, tidak ada teks lain."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_time(dt: Any) -> str:
        """Format datetime ke string pendek."""
        if isinstance(dt, datetime):
            return dt.strftime("%m/%d %H:%M")
        return str(dt)[:16] if dt else "?"

    def _downsample_to_m15(self, candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Downsample M5 candles ke M15 dengan alignment ke boundary 15 menit yang benar.

        Grouping berdasarkan 15-minute boundary dari timestamp tiap candle (UTC):
          - menit 0–14  → slot 0
          - menit 15–29 → slot 15
          - menit 30–44 → slot 30
          - menit 45–59 → slot 45

        Setiap grup 3 candle M5 membentuk 1 candle M15.

        Args:
            candles: list candle M5 dengan field 'time' berupa datetime atau string ISO

        Returns:
            list candle M15, diurutkan ascending by time
        """
        if len(candles) < 3:
            return candles

        from collections import defaultdict
        from datetime import datetime as _dt

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

            # Boundary 15 menit: floor menit ke 0, 15, 30, atau 45
            slot_minute = (dt.minute // 15) * 15
            m15_key = (dt.year, dt.month, dt.day, dt.hour, slot_minute)
            groups[m15_key].append(candle)

        m15: list[dict] = []
        for m15_key in sorted(groups.keys()):
            chunk = groups[m15_key]
            if not chunk:
                continue

            # Sort by time untuk pastikan urutan open → close benar
            chunk_sorted = sorted(
                chunk,
                key=lambda c: (
                    c["time"] if isinstance(c["time"], str)
                    else c["time"].isoformat() if c.get("time")
                    else ""
                ),
            )

            m15.append({
                "time": chunk_sorted[0].get("time"),          # open time = awal slot 15 menit
                "open": float(chunk_sorted[0]["open"]),
                "high": max(float(c["high"]) for c in chunk_sorted),
                "low": min(float(c["low"]) for c in chunk_sorted),
                "close": float(chunk_sorted[-1]["close"]),
                "tick_volume": sum(int(c.get("tick_volume", 0)) for c in chunk_sorted),
            })

        return m15

    @staticmethod
    def _calc_position_pnl(position: dict[str, Any], current_price: float) -> float:
        """Hitung floating PnL posisi dalam USD (XAUUSD).

        Formula: PnL = price_diff × volume × 100
        Karena 1 lot XAUUSD = 100 oz, setiap $1 move = $100 per lot.
        """
        direction = 1 if position.get("type") in (0, "BUY") else -1
        entry = float(position.get("price_open", position.get("entry_price", 0)))
        volume = float(position.get("volume", 0.01))
        price_diff = (current_price - entry) * direction
        return price_diff * volume * 100

    # ------------------------------------------------------------------
    # Response Validation
    # ------------------------------------------------------------------

    def _validate_and_normalize(
        self,
        raw: dict[str, Any],
        now: datetime,
        session: str,
        atr: float,
    ) -> dict[str, Any]:
        """Validate & normalize LLM response ke format standar.

        v3.0: STANDBY diperbolehkan. ENTRY divalidasi seperti biasa.
        """

        decision = str(raw.get("decision", "ENTRY")).upper()

        # v3.0: Handle STANDBY
        if decision == "STANDBY":
            return {
                "decision": "STANDBY",
                "direction": "NONE",
                "entry_price": None,
                "sl_price": None,
                "tp1_price": None,
                "tp2_price": None,
                "lot_size": None,
                "rr_ratio_t1": None,
                "rr_ratio_t2": None,
                "confidence": self._safe_int(raw.get("confidence"), 0),
                "bias_htf": str(raw.get("bias_htf", "RANGING")).upper(),
                "intraday_phase": raw.get("intraday_phase") or "CONSOLIDATION",
                "reason": str(raw.get("reason", "Kondisi tidak mendukung entry"))[:300],
                "invalidation": "N/A",
                "risk_percent": 1.0,
                "analyzed_at": now,
                "session": session,
                "atr": atr,
            }

        # Lanjut ke validasi ENTRY seperti biasa...
        direction = str(raw.get("direction", "")).upper()
        bias_htf = str(raw.get("bias_htf", "")).upper()

        # Force direction dari bias_htf jika invalid
        if direction not in ("BUY", "SELL"):
            if bias_htf == "BEARISH":
                direction = "SELL"
            elif bias_htf == "BULLISH":
                direction = "BUY"
            else:
                # Default: ikuti arah candle terakhir (nanti diisi orchestrator)
                direction = "SELL"  # fallback default
            logger.warning(
                "TradingAgent: direction invalid, forced from bias_htf=%s → %s",
                bias_htf, direction,
            )

        # Force bias_htf valid
        if bias_htf not in ("BULLISH", "BEARISH"):
            bias_htf = "BULLISH" if direction == "BUY" else "BEARISH"

        result: dict[str, Any] = {
            "decision": "ENTRY",
            "direction": direction,
            "entry_price": self._safe_float(raw.get("entry_price")),
            "sl_price": self._safe_float(raw.get("sl_price")),
            "tp1_price": self._safe_float(raw.get("tp1_price")),
            "tp2_price": self._safe_float(raw.get("tp2_price")),
            "lot_size": self._safe_float(raw.get("lot_size")),
            "rr_ratio_t1": self._safe_float(raw.get("rr_ratio_t1")),
            "rr_ratio_t2": self._safe_float(raw.get("rr_ratio_t2")),
            "confidence": self._safe_int(raw.get("confidence"), 40),
            "bias_htf": bias_htf,
            "intraday_phase": raw.get("intraday_phase") or "TRENDING",
            "reason": str(raw.get("reason", ""))[:300],
            "invalidation": str(raw.get("invalidation", ""))[:200],
            "risk_percent": self._safe_float(raw.get("risk_percent")),
            "analyzed_at": now,
            "session": session,
            "atr": atr,
        }

        # Jika entry_price null, tidak bisa eksekusi → flag untuk orchestrator
        if result["entry_price"] is None:
            logger.warning("TradingAgent: entry_price null — orchestrator will use current price")

        if result["sl_price"] is None:
            logger.warning("TradingAgent: sl_price null — orchestrator will calculate from ATR")

        if result["tp1_price"] is None:
            logger.warning("TradingAgent: tp1_price null — orchestrator will calculate from RR")

        return result

    @staticmethod
    def _safe_float(val: Any) -> float | None:
        """Safe float conversion."""
        if val is None:
            return None
        try:
            return round(float(val), 5)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_int(val: Any, default: int = 0) -> int:
        """Safe int conversion."""
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def _fallback_result(
        self,
        now: datetime,
        session: str,
        atr: float,
        error: str,
    ) -> dict[str, Any]:
        """Return fallback ENTRY when LLM fails completely.

        v2.1: Tidak ada STANDBY. Return ENTRY dengan null prices —
        orchestrator akan mengisi dari current price + ATR-based SL/TP.
        """
        return {
            "decision": "ENTRY",
            "direction": "SELL",  # orchestrator akan override berdasarkan price action
            "entry_price": None,
            "sl_price": None,
            "tp1_price": None,
            "tp2_price": None,
            "lot_size": None,
            "rr_ratio_t1": None,
            "rr_ratio_t2": None,
            "confidence": 10,
            "bias_htf": "BEARISH",
            "intraday_phase": "TRENDING",
            "reason": f"LLM error — rule-based fallback: {error}",
            "invalidation": "N/A",
            "risk_percent": 1.0,
            "analyzed_at": now,
            "session": session,
            "atr": atr,
        }
