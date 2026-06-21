"""
MT5 Client — Connection wrapper untuk MetaTrader 5 terminal.
Mencakup TASK 1.2 (MT5Client), TASK 4.2 (detect_session), TASK 4.3 (calculate_atr).

Semua method menggunakan type hints.
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

import MetaTrader5 as mt5
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timeframe mapping: string → mt5.TIMEFRAME_* constant
# ---------------------------------------------------------------------------
_TIMEFRAME_MAP: dict[str, int] = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}


def _resolve_timeframe(tf: str | int) -> int:
    """Konversi string timeframe (misal 'M15') ke konstanta mt5.TIMEFRAME_*.

    Jika sudah berupa int, langsung return (asumsi sudah konstanta MT5).
    """
    if isinstance(tf, int):
        return tf
    if tf.upper() in _TIMEFRAME_MAP:
        return _TIMEFRAME_MAP[tf.upper()]
    raise ValueError(f"Unknown timeframe: {tf!r}")


# ===================================================================
# TASK 4.2 — Session Detection
# ===================================================================


def detect_session(dt: datetime | None = None) -> str:
    """Deteksi session trading berdasarkan waktu UTC.

    Returns salah satu dari: 'London', 'New York', 'Overlap', 'Asia', 'Other'.

    Zona waktu (UTC):
    - Asia:    00:00 – 07:00
    - London:  07:00 – 16:00
    - New York: 12:00 – 21:00
    - Overlap: 12:00 – 16:00  (London & NY bersamaan, prioritas tertinggi)
    - Other:   sisanya
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        # Anggap naive datetime sebagai UTC
        dt = dt.replace(tzinfo=timezone.utc)

    hour: int = dt.hour

    if 12 <= hour < 16:
        return "Overlap"
    if 7 <= hour < 16:
        return "London"
    if 12 <= hour < 21:
        return "New York"
    if 0 <= hour < 7:
        return "Asia"
    return "Other"


# ===================================================================
# TASK 4.3 — ATR Calculator
# ===================================================================


def calculate_atr(candles: list[dict], period: int = 14) -> float:
    """Hitung Average True Range (ATR) dari daftar candles.

    True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
    ATR = rata-rata TR dari N candle terakhir.

    Args:
        candles: list[dict] dengan keys 'high', 'low', 'close'
        period: jumlah candle untuk rata-rata (default 14)

    Returns:
        float — nilai ATR, atau 0.0 jika data tidak cukup
    """
    if len(candles) < period + 1:
        logger.warning(
            "calculate_atr: hanya %d candle, butuh minimal %d", len(candles), period + 1
        )
        return 0.0

    # Ambil N candle terakhir + 1 (untuk prev_close)
    window = candles[-(period + 1):]

    true_ranges: list[float] = []
    for i in range(1, len(window)):
        high = float(window[i]["high"])
        low = float(window[i]["low"])
        prev_close = float(window[i - 1]["close"])

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)

    if not true_ranges:
        return 0.0

    return sum(true_ranges) / len(true_ranges)


# ===================================================================
# TASK 1.2 — MT5Client
# ===================================================================


class MT5Client:
    """Wrapper koneksi MetaTrader 5.

    Membaca kredensial dari environment variables (via python-dotenv).

    Usage:
        client = MT5Client()
        if client.connect():
            candles = client.get_candles("XAUUSD", "M15", 200)
            price  = client.get_current_price("XAUUSD")
            ...
            client.disconnect()
    """

    def __init__(self) -> None:
        load_dotenv()
        self._login: int = int(os.getenv("MT5_LOGIN", "0"))
        self._password: str = os.getenv("MT5_PASSWORD", "")
        self._server: str = os.getenv("MT5_SERVER", "")
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Konek ke MT5 terminal dengan credentials dari .env.

        Returns:
            True jika berhasil connect + login, False jika gagal.
        """
        if self._connected:
            logger.info("MT5Client: sudah terkoneksi, skip connect()")
            return True

        if not mt5.initialize(
    login=self._login,
    password=self._password,
    server=self._server,
):
    error = mt5.last_error()
    logger.error("MT5 initialize() gagal: %s", error)
    return False

        if not authorized:
            error = mt5.last_error()
            logger.error("MT5 login() gagal — %s", error)
            mt5.shutdown()
            return False

        self._connected = True
        account = mt5.account_info()
        if account is not None:
            logger.info(
                "MT5Client: terkoneksi ke akun #%s, server=%s, balance=%.2f",
                account.login,
                account.server,
                account.balance,
            )
        return True

    def disconnect(self) -> None:
        """Shutdown koneksi MT5."""
        if self._connected:
            mt5.shutdown()
            self._connected = False
            logger.info("MT5Client: disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Market Data
    # ------------------------------------------------------------------

    def get_candles(
        self,
        symbol: str,
        timeframe: str | int = "M15",
        count: int = 200,
    ) -> list[dict]:
        """Ambil N candle terbaru dari MT5.

        Menggunakan mt5.copy_rates_from_pos().

        Args:
            symbol: nama simbol (misal 'XAUUSD', 'EURUSD')
            timeframe: 'M1','M5','M15','M30','H1','H4','D1','W1','MN1'
                       atau konstanta mt5.TIMEFRAME_*
            count: jumlah candle yang diminta (default 200)

        Returns:
            list[dict] dengan keys: time, open, high, low, close, tick_volume, spread.
            Return list kosong jika gagal.
        """
        tf = _resolve_timeframe(timeframe)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            error = mt5.last_error()
            logger.error("get_candles(%s, %s, %d) gagal: %s", symbol, timeframe, count, error)
            return []

        result: list[dict] = []
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

    def get_current_price(self, symbol: str) -> dict:
        """Ambil harga bid/ask/last terkini.

        Args:
            symbol: nama simbol

        Returns:
            dict: {"bid": float, "ask": float, "last": float, "time": datetime}
            Jika gagal, return dictionary dengan semua nilai 0.0.
        """
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            error = mt5.last_error()
            logger.error("get_current_price(%s) gagal: %s", symbol, error)
            return {"bid": 0.0, "ask": 0.0, "last": 0.0, "time": datetime.now(timezone.utc)}

        return {
            "bid": float(tick.bid),
            "ask": float(tick.ask),
            "last": float(tick.last) if tick.last else 0.0,
            "time": datetime.fromtimestamp(tick.time, tz=timezone.utc) if tick.time else datetime.now(timezone.utc),
        }

    # ------------------------------------------------------------------
    # Account & Positions
    # ------------------------------------------------------------------

    def get_open_positions(self) -> list[dict]:
        """Ambil semua posisi aktif dari MT5.

        Returns:
            list[dict] — setiap dict berisi:
                ticket, symbol, type (0=BUY,1=SELL), volume, price_open,
                sl, tp, profit, comment, time_open
        """
        positions = mt5.positions_get()
        if positions is None or len(positions) == 0:
            return []

        result: list[dict] = []
        for p in positions:
            result.append({
                "ticket": int(p.ticket),
                "symbol": str(p.symbol),
                "type": int(p.type),  # 0 = BUY, 1 = SELL
                "volume": float(p.volume),
                "price_open": float(p.price_open),
                "sl": float(p.sl),
                "tp": float(p.tp),
                "profit": float(p.profit),
                "comment": str(p.comment),
                "time_open": datetime.fromtimestamp(p.time, tz=timezone.utc),
            })
        return result

    def get_account_info(self) -> dict:
        """Ambil informasi akun trading.

        Returns:
            dict: {balance, equity, margin, free_margin, currency, leverage}
            Jika gagal, return dictionary dengan nilai default.
        """
        account = mt5.account_info()
        if account is None:
            error = mt5.last_error()
            logger.error("get_account_info() gagal: %s", error)
            return {
                "balance": 0.0,
                "equity": 0.0,
                "margin": 0.0,
                "free_margin": 0.0,
                "currency": "",
                "leverage": 0,
            }

        return {
            "balance": float(account.balance),
            "equity": float(account.equity),
            "margin": float(account.margin),
            "free_margin": float(account.margin_free),
            "currency": str(account.currency),
            "leverage": int(account.leverage),
        }
