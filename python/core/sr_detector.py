"""
SRDetector — Deteksi Support & Resistance Fresh dari candle M15.

Level "fresh" didefinisikan sebagai swing high/low yang:
1. Terbentuk minimal 2 candle lalu (bukan candle terkini)
2. Belum ditest ulang lebih dari MAX_TESTS kali sejak terbentuk
3. Ada wick rejection jelas saat level terbentuk (wick >= WICK_RATIO × body)

Digunakan oleh orchestrator tick loop untuk trigger AI konfirmasi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SWING_LOOKBACK = 3       # candle kiri & kanan untuk konfirmasi swing
MAX_TESTS = 2            # max berapa kali level boleh ditest sebelum dianggap "stale"
WICK_RATIO = 0.5         # wick minimal 50% dari body untuk konfirmasi rejection
TOUCH_THRESHOLD = 0.15   # harga dianggap "menyentuh" level jika jarak <= $0.15


@dataclass
class SRLevel:
    """Satu level Support atau Resistance."""
    price: float
    kind: str                   # "support" atau "resistance"
    formed_at: datetime
    test_count: int = 0
    last_tested_at: datetime | None = None
    is_fresh: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": round(self.price, 4),
            "kind": self.kind,
            "formed_at": self.formed_at.isoformat() if self.formed_at else None,
            "test_count": self.test_count,
            "last_tested_at": self.last_tested_at.isoformat() if self.last_tested_at else None,
            "is_fresh": self.is_fresh,
        }


class SRDetector:
    """Identifikasi dan track level S/R fresh dari candle historis.

    Usage:
        detector = SRDetector()
        detector.update(m15_candles)          # update setiap candle baru
        levels = detector.get_fresh_levels()  # ambil level yang masih fresh
        touched = detector.check_touch(current_price)  # cek apakah harga menyentuh level
    """

    def __init__(
        self,
        swing_lookback: int = SWING_LOOKBACK,
        max_tests: int = MAX_TESTS,
        touch_threshold: float = TOUCH_THRESHOLD,
    ) -> None:
        self._lookback = swing_lookback
        self._max_tests = max_tests
        self._touch_threshold = touch_threshold
        self._levels: list[SRLevel] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, candles: list[dict[str, Any]]) -> None:
        """Identifikasi ulang S/R dari candles M15 terbaru.

        Dipanggil setiap kali candle baru close.

        Args:
            candles: list candle M15, ascending by time
        """
        if len(candles) < self._lookback * 2 + 3:
            return

        new_levels: list[SRLevel] = []

        # Scan semua candle kecuali yang paling ujung (butuh candle kanan untuk konfirmasi)
        scan_range = range(self._lookback, len(candles) - self._lookback - 1)

        for i in scan_range:
            candle = candles[i]
            left = candles[i - self._lookback: i]
            right = candles[i + 1: i + self._lookback + 1]

            high_i = float(candle["high"])
            low_i = float(candle["low"])
            open_i = float(candle["open"])
            close_i = float(candle["close"])
            formed_at = candle.get("time")

            # --- SWING HIGH (Resistance) ---
            is_swing_high = (
                all(float(c["high"]) < high_i for c in left) and
                all(float(c["high"]) < high_i for c in right)
            )
            if is_swing_high:
                # Konfirmasi wick rejection: upper wick >= WICK_RATIO × body
                body = abs(close_i - open_i)
                upper_wick = high_i - max(open_i, close_i)
                has_rejection = body > 0 and upper_wick >= WICK_RATIO * body
                if has_rejection or body < 0.10:  # doji juga valid
                    level = self._find_existing(high_i, "resistance")
                    if level is None:
                        new_levels.append(SRLevel(
                            price=high_i,
                            kind="resistance",
                            formed_at=formed_at,
                        ))
                        ft = formed_at.strftime("%Y-%m-%d %H:%M UTC") if isinstance(formed_at, datetime) else str(formed_at)
                        logger.info("SRDetector: NEW RESISTANCE %.4f formed at %s", high_i, ft)

            # --- SWING LOW (Support) ---
            is_swing_low = (
                all(float(c["low"]) > low_i for c in left) and
                all(float(c["low"]) > low_i for c in right)
            )
            if is_swing_low:
                body = abs(close_i - open_i)
                lower_wick = min(open_i, close_i) - low_i
                has_rejection = body > 0 and lower_wick >= WICK_RATIO * body
                if has_rejection or body < 0.10:
                    level = self._find_existing(low_i, "support")
                    if level is None:
                        new_levels.append(SRLevel(
                            price=low_i,
                            kind="support",
                            formed_at=formed_at,
                        ))
                        ft = formed_at.strftime("%Y-%m-%d %H:%M UTC") if isinstance(formed_at, datetime) else str(formed_at)
                        logger.info("SRDetector: NEW SUPPORT %.4f formed at %s", low_i, ft)

        # Merge: pertahankan existing levels yang masih fresh, tambah yang baru
        existing_prices = {(round(lv.price, 2), lv.kind) for lv in self._levels}
        for lv in new_levels:
            key = (round(lv.price, 2), lv.kind)
            if key not in existing_prices:
                self._levels.append(lv)

        # Hapus level yang sudah stale (test_count melebihi batas)
        self._levels = [lv for lv in self._levels if lv.test_count <= self._max_tests]

        logger.debug(
            "SRDetector.update: %d levels aktif (%d support, %d resistance)",
            len(self._levels),
            sum(1 for lv in self._levels if lv.kind == "support"),
            sum(1 for lv in self._levels if lv.kind == "resistance"),
        )

    def check_touch(
        self,
        current_price: float,
        candle_time: datetime | None = None,
    ) -> list[SRLevel]:
        """Cek apakah harga menyentuh level S/R mana pun.

        Level dianggap "disentuh" jika:
            |current_price - level.price| <= touch_threshold

        Saat level disentuh, test_count-nya bertambah 1.
        Jika test_count > max_tests, level ditandai not fresh.

        Args:
            current_price: harga bid/ask mid saat ini
            candle_time: waktu candle terkini (untuk logging)

        Returns:
            list SRLevel yang tersentuh (bisa lebih dari 1 jika level berdekatan)
        """
        touched: list[SRLevel] = []

        for level in self._levels:
            if not level.is_fresh:
                continue
            distance = abs(current_price - level.price)
            if distance <= self._touch_threshold:
                level.test_count += 1
                level.last_tested_at = candle_time or datetime.utcnow()
                if level.test_count > self._max_tests:
                    level.is_fresh = False
                    logger.info(
                        "SRDetector: level %.4f (%s) dinyatakan STALE setelah %d tests",
                        level.price, level.kind, level.test_count,
                    )
                else:
                    touched.append(level)
                    # Format candle time untuk log
                    time_str = ""
                    if candle_time:
                        if isinstance(candle_time, datetime):
                            time_str = candle_time.strftime("%Y-%m-%d %H:%M UTC")
                        else:
                            time_str = str(candle_time)
                    logger.info(
                        "SRDetector: TOUCH! candle=%s price=%.4f level=%.4f (%s) test=%d/%d",
                        time_str or "N/A", current_price, level.price, level.kind,
                        level.test_count, self._max_tests,
                    )

        return touched

    def get_fresh_levels(self) -> list[SRLevel]:
        """Return semua level yang masih fresh, sorted by price."""
        return sorted(
            [lv for lv in self._levels if lv.is_fresh],
            key=lambda x: x.price,
        )

    def get_nearest_level(self, current_price: float) -> SRLevel | None:
        """Return level fresh terdekat dari current_price."""
        fresh = self.get_fresh_levels()
        if not fresh:
            return None
        return min(fresh, key=lambda lv: abs(lv.price - current_price))

    def reset(self) -> None:
        """Reset semua levels (gunakan saat reconnect atau simbol berganti)."""
        self._levels = []
        logger.info("SRDetector: levels direset")

    def summary(self) -> dict[str, Any]:
        """Return ringkasan level untuk logging/dashboard."""
        fresh = self.get_fresh_levels()
        return {
            "total_levels": len(self._levels),
            "fresh_levels": len(fresh),
            "supports": [lv.to_dict() for lv in fresh if lv.kind == "support"],
            "resistances": [lv.to_dict() for lv in fresh if lv.kind == "resistance"],
        }

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _find_existing(self, price: float, kind: str, tolerance: float = 0.20) -> SRLevel | None:
        """Cari level yang sudah ada dalam radius tolerance."""
        for lv in self._levels:
            if lv.kind == kind and abs(lv.price - price) <= tolerance:
                return lv
        return None
