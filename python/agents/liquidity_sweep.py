"""
Liquidity Sweep Agent — TASK 2.2
Mendeteksi liquidity sweep (manipulasi) dari struktur harga.

Logic:
1. Struktur lama (candles[-40:-20]) → swing_high, swing_low
2. Candle recent (candles[-20:]) → deteksi sweep
3. BULLISH SWEEP: low break bawah swing_low + close KEMBALI di atas → sinyal BUY
4. BEARISH SWEEP: high break atas swing_high + close KEMBALI di bawah → sinyal SELL
5. Hitung candles_since_sweep (basi jika > 5)
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Window definitions
STRUCTURE_START = -40
STRUCTURE_END = -20
RECENT_START = -20

# Sweep basi setelah N candle
MAX_SWEEP_AGE = 5


class LiquiditySweepAgent:
    """Agent untuk mendeteksi liquidity sweep pada candle data.

    Usage:
        agent = LiquiditySweepAgent()
        result = agent.analyze(candles)
        print(result["direction"], result["sweep_detected"])
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, candles: list[dict[str, Any]]) -> dict[str, Any]:
        """Analisis liquidity sweep dari candle data.

        Args:
            candles: list[dict] dengan keys 'high','low','close'
                     Minimal 41 candle untuk analisis valid.

        Returns:
            dict dengan keys:
                sweep_detected, direction, sweep_level,
                swing_high, swing_low, current_price,
                candles_since_sweep, sweep_candle_index
        """
        n = len(candles)

        if n < 41:
            logger.warning(
                "LiquiditySweepAgent: hanya %d candle (min 41), tidak bisa analisis",
                n,
            )
            return self._empty_result()

        # Step 1: Struktur lama — candles[-40:-20]
        structure = candles[STRUCTURE_START:STRUCTURE_END]
        swing_high = max(float(c["high"]) for c in structure)
        swing_low = min(float(c["low"]) for c in structure)

        # Step 2: Candle recent — candles[-20:]
        recent = candles[RECENT_START:]

        current_price = float(recent[-1]["close"])

        # Step 3: Deteksi sweep
        result = self._detect_sweep(recent, swing_high, swing_low, n)

        result["swing_high"] = swing_high
        result["swing_low"] = swing_low
        result["current_price"] = current_price

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _empty_result(self) -> dict[str, Any]:
        """Return empty/default result."""
        return {
            "sweep_detected": False,
            "direction": None,
            "sweep_level": None,
            "swing_high": 0.0,
            "swing_low": 0.0,
            "current_price": 0.0,
            "candles_since_sweep": None,
            "sweep_candle_index": None,
        }

    def _detect_sweep(
        self,
        recent: list[dict[str, Any]],
        swing_high: float,
        swing_low: float,
        total_candles: int,
    ) -> dict[str, Any]:
        """Deteksi bullish / bearish sweep di recent candles.

        Bullish sweep: low < swing_low → lalu close > swing_low (BUY signal)
        Bearish sweep: high > swing_high → lalu close < swing_high (SELL signal)

        Prioritas: ambil sweep PALING BARU (candle index terbesar).
        """
        best_bullish: dict[str, Any] | None = None
        best_bearish: dict[str, Any] | None = None

        for i, candle in enumerate(recent):
            high = float(candle["high"])
            low = float(candle["low"])
            close = float(candle["close"])

            # --- Bullish Sweep ---
            # Low break di bawah swing_low, tapi close di atas atau candle berikutnya close di atas
            if low < swing_low:
                # Cek candle ini atau berikutnya close di atas swing_low
                recovery_found = False
                for j in range(i, len(recent)):
                    c_close = float(recent[j]["close"])
                    if c_close > swing_low:
                        recovery_found = True
                        break

                if recovery_found:
                    global_idx = total_candles - len(recent) + i
                    best_bullish = {
                        "sweep_detected": True,
                        "direction": "BUY",
                        "sweep_level": swing_low,
                        "sweep_candle_index": global_idx,
                        "candles_since_sweep": len(recent) - 1 - i,
                    }

            # --- Bearish Sweep ---
            # High break di atas swing_high, tapi close di bawah atau candle berikutnya close di bawah
            if high > swing_high:
                recovery_found = False
                for j in range(i, len(recent)):
                    c_close = float(recent[j]["close"])
                    if c_close < swing_high:
                        recovery_found = True
                        break

                if recovery_found:
                    global_idx = total_candles - len(recent) + i
                    best_bearish = {
                        "sweep_detected": True,
                        "direction": "SELL",
                        "sweep_level": swing_high,
                        "sweep_candle_index": global_idx,
                        "candles_since_sweep": len(recent) - 1 - i,
                    }

        # Pilih sweep yang paling baru (candles_since_sweep terkecil)
        if best_bullish and best_bearish:
            if best_bullish["candles_since_sweep"] <= best_bearish["candles_since_sweep"]:
                logger.info("LiquiditySweep: BULLISH sweep detected at level %.4f", swing_low)
                return best_bullish
            else:
                logger.info("LiquiditySweep: BEARISH sweep detected at level %.4f", swing_high)
                return best_bearish
        elif best_bullish:
            logger.info("LiquiditySweep: BULLISH sweep detected at level %.4f", swing_low)
            return best_bullish
        elif best_bearish:
            logger.info("LiquiditySweep: BEARISH sweep detected at level %.4f", swing_high)
            return best_bearish

        logger.debug("LiquiditySweep: tidak ada sweep terdeteksi")
        return self._empty_result()
