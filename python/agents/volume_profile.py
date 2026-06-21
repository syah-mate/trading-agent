"""
Volume Profile Agent — TASK 2.1
Menganalisis distribusi volume per price level dari candle data.

Logic:
1. Akumulasi tick_volume per price level (round 4 desimal)
2. Temukan POC (Point of Control) = level volume tertinggi
3. Value Area = range yang mencakup 70% total volume, expand dari POC
4. HVN = levels volume > 70% max
5. LVN = levels volume < 30% max
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Jumlah candle minimal untuk analisis yang valid
MIN_CANDLES = 100

# Persentase Value Area dari total volume
VA_PCT = 0.70

# Threshold HVN / LVN relatif terhadap volume maksimum
HVN_THRESHOLD = 0.70
LVN_THRESHOLD = 0.30


class VolumeProfileAgent:
    """Agent untuk menghitung Volume Profile dari data candle.

    Usage:
        agent = VolumeProfileAgent()
        result = agent.analyze(candles)
        print(result["poc"], result["vah"], result["val"])
    """

    def __init__(self, price_precision: int = 4) -> None:
        self._precision: int = price_precision

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, candles: list[dict[str, Any]]) -> dict[str, Any]:
        """Analisis volume profile dari list candle.

        Args:
            candles: list[dict] dengan keys 'high','low','close','tick_volume'
                     Minimal 100 candle untuk hasil yang valid.

        Returns:
            dict dengan keys:
                poc, vah, val, hvn_zones, lvn_zones,
                total_volume, candle_count, volume_profile
        """
        candle_count = len(candles)

        if candle_count < MIN_CANDLES:
            logger.warning(
                "VolumeProfileAgent: hanya %d candle (min %d), hasil kurang valid",
                candle_count, MIN_CANDLES,
            )

        # Step 1: Distribusi volume per price level
        vp = self._build_volume_profile(candles)

        if not vp:
            return {
                "poc": 0.0,
                "vah": 0.0,
                "val": 0.0,
                "hvn_zones": [],
                "lvn_zones": [],
                "total_volume": 0.0,
                "candle_count": candle_count,
                "volume_profile": {},
            }

        total_volume = sum(vp.values())
        max_volume = max(vp.values())

        # Step 2: POC
        poc = max(vp, key=vp.get)  # type: ignore[arg-type]

        # Step 3: Value Area (70%)
        # Sort levels by price ascending
        sorted_levels = sorted(vp.keys())
        va_target = total_volume * VA_PCT

        # Mulai dari POC, expand ke atas & bawah sampai cover 70%
        vah, val = self._calculate_value_area(
            vp, sorted_levels, poc, va_target
        )

        # Step 4: HVN & LVN
        hvn_zones = [
            level for level, vol in vp.items()
            if vol > max_volume * HVN_THRESHOLD
        ]
        hvn_zones.sort()

        lvn_zones = [
            level for level, vol in vp.items()
            if vol < max_volume * LVN_THRESHOLD
        ]
        lvn_zones.sort()

        logger.info(
            "VolumeProfile: POC=%.4f VAH=%.4f VAL=%.4f HVN=%d LVN=%d vol=%.0f",
            poc, vah, val, len(hvn_zones), len(lvn_zones), total_volume,
        )

        return {
            "poc": poc,
            "vah": vah,
            "val": val,
            "hvn_zones": hvn_zones,
            "lvn_zones": lvn_zones,
            "total_volume": total_volume,
            "candle_count": candle_count,
            "volume_profile": vp,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _round_price(self, price: float) -> float:
        """Round price ke precision desimal."""
        return round(price, self._precision)

    def _build_volume_profile(self, candles: list[dict[str, Any]]) -> dict[float, float]:
        """Bangun volume profile: {price_level: total_volume}."""
        vp: dict[float, float] = {}

        for c in candles:
            try:
                high = float(c["high"])
                low = float(c["low"])
                close = float(c["close"])
                volume = float(c.get("tick_volume", 0))
            except (KeyError, ValueError, TypeError):
                continue

            if volume <= 0:
                continue

            # Gunakan range high-low untuk distribusi volume per candle
            price_range = high - low
            if price_range <= 0:
                # Single price level (high == low)
                level = self._round_price(close)
                vp[level] = vp.get(level, 0.0) + volume
                continue

            # Distribusikan volume dari low ke high
            # Setiap level dalam candle ini dapat sebagian volume
            num_levels = max(1, int(price_range / (10 ** -self._precision)))
            if num_levels > 200:
                # Terlalu banyak level, gunakan pendekatan sederhana
                # Tambah volume ke POC candle (close)
                level = self._round_price(close)
                vp[level] = vp.get(level, 0.0) + volume
                continue

            step = price_range / num_levels
            vol_per_level = volume / (num_levels + 1)

            current = low
            for _ in range(num_levels + 1):
                level = self._round_price(current)
                vp[level] = vp.get(level, 0.0) + vol_per_level
                current += step

        return vp

    def _calculate_value_area(
        self,
        vp: dict[float, float],
        sorted_levels: list[float],
        poc: float,
        va_target: float,
    ) -> tuple[float, float]:
        """Hitung Value Area High & Low dengan expand dari POC.

        Returns:
            (vah, val) tuple
        """
        if poc not in sorted_levels:
            return poc, poc

        poc_idx = sorted_levels.index(poc)
        accumulated = vp[poc]

        # Pointer untuk ekspansi atas & bawah
        above_idx = poc_idx + 1
        below_idx = poc_idx - 1

        vah = poc
        val = poc

        while accumulated < va_target:
            above_vol = vp.get(sorted_levels[above_idx], 0.0) if above_idx < len(sorted_levels) else 0.0
            below_vol = vp.get(sorted_levels[below_idx], 0.0) if below_idx >= 0 else 0.0

            if above_vol == 0.0 and below_vol == 0.0:
                break

            # Expand ke arah dengan volume lebih besar
            if above_vol >= below_vol and above_idx < len(sorted_levels):
                vah = sorted_levels[above_idx]
                accumulated += above_vol
                above_idx += 1
            elif below_idx >= 0:
                val = sorted_levels[below_idx]
                accumulated += below_vol
                below_idx -= 1
            else:
                break

        return vah, val
