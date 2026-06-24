"""
MT5 Executor — TASK 3.1
Eksekusi order (open, close, modify SL/TP) via MetaTrader 5.

PENTING: MT5 tidak thread-safe. Semua calls harus dari thread yang sama.
"""

import logging
from datetime import datetime, timezone
from typing import Any

import MetaTrader5 as mt5

logger = logging.getLogger(__name__)


class MT5Executor:
    """Eksekusi order trading via MT5.

    Usage:
        executor = MT5Executor(symbol="XAUUSD", lot_size=0.01)
        trade = executor.open_position(signal)
        executor.modify_sl(ticket=12345, new_sl=2000.00)
        executor.close_position(ticket=12345)
    """

    def __init__(self, symbol: str = "XAUUSDc", lot_size: float = 0.01) -> None:
        """
        Args:
            lot_size: lot size dari config (LOT_FIX). Tidak hardcode di sini —
                      nilai ini di-inject dari orchestrator saat startup.
        """
        self._symbol: str = symbol
        self._lot_size: float = lot_size  # di-set dari orchestrator via _get_trading_params()

    # ------------------------------------------------------------------
    # Open Position
    # ------------------------------------------------------------------

    def open_position(self, signal: dict[str, Any]) -> dict[str, Any]:
        """Buka posisi baru berdasarkan sinyal.

        Args:
            signal: dict dengan keys:
                direction ('BUY'/'SELL'), sl_price, tp1_price

        Returns:
            dict: {ticket, entry_price, sl, tp, direction, volume, opened_at}
            Atau dict dengan error field jika gagal.
        """
        direction = signal.get("direction")
        sl = signal.get("sl_price")
        tp = signal.get("tp1_price")

        if direction not in ("BUY", "SELL"):
            return {"error": f"Invalid direction: {direction}"}

        # Dapatkan harga terkini
        tick = mt5.symbol_info_tick(self._symbol)
        if tick is None:
            error = mt5.last_error()
            return {"error": f"Gagal ambil harga {self._symbol}: {error}"}

        if direction == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid

        # Siapkan request
        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self._symbol,
            "volume": self._lot_size,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": 123456,
            "comment": f"AI_AGENT_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        if sl is not None and sl > 0:
            request["sl"] = float(sl)
        if tp is not None and tp > 0:
            request["tp"] = float(tp)

        # Kirim order
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            error_info = mt5.last_error()
            retcode = result.retcode if result else "N/A"
            logger.error("open_position gagal: retcode=%s error=%s", retcode, error_info)
            return {
                "error": f"Order gagal — retcode={retcode} error={error_info}",
                "retcode": retcode,
            }

        now = datetime.now(timezone.utc)
        trade = {
            "ticket": int(result.order),
            "entry_price": float(result.price),
            "sl": float(sl) if sl else 0.0,
            "tp": float(tp) if tp else 0.0,
            "direction": direction,
            "volume": self._lot_size,
            "opened_at": now,
        }

        logger.info(
            "open_position OK: ticket=%d %s %s entry=%.4f sl=%.4f tp=%.4f",
            trade["ticket"], self._symbol, direction,
            trade["entry_price"], trade["sl"], trade["tp"],
        )

        return trade

    # ------------------------------------------------------------------
    # Close Position
    # ------------------------------------------------------------------

    def close_position(self, ticket: int, percentage: int = 100) -> bool:
        """Tutup posisi (atau partial close).

        Args:
            ticket: ticket number posisi yang akan ditutup
            percentage: berapa persen volume ditutup (default 100 = full close)

        Returns:
            True jika berhasil, False jika gagal
        """
        # Cari posisi
        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            logger.error("close_position: posisi ticket=%d tidak ditemukan", ticket)
            return False

        pos = position[0]
        volume = pos.volume

        # Hitung volume yang akan ditutup
        close_volume = volume * (percentage / 100.0)
        close_volume = round(close_volume, 2)
        if close_volume <= 0:
            logger.warning("close_position: volume close = 0 (percentage=%d)", percentage)
            return False

        # Tentukan arah tutup
        if pos.type == mt5.POSITION_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = mt5.symbol_info_tick(self._symbol).bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(self._symbol).ask

        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self._symbol,
            "volume": close_volume,
            "type": order_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": 123456,
            "comment": f"AI_CLOSE_{percentage}pct",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            error_info = mt5.last_error()
            retcode = result.retcode if result else "N/A"
            logger.error("close_position gagal: retcode=%s error=%s", retcode, error_info)
            return False

        logger.info(
            "close_position OK: ticket=%d volume=%.2f (%.0f%%)",
            ticket, close_volume, percentage,
        )
        return True

    # ------------------------------------------------------------------
    # Modify SL / TP
    # ------------------------------------------------------------------

    def modify_sl(self, ticket: int, new_sl: float) -> bool:
        """Update Stop Loss posisi.

        Args:
            ticket: ticket number
            new_sl: harga SL baru

        Returns:
            True jika berhasil
        """
        return self._modify_sltp(ticket, sl=new_sl)

    def modify_tp(self, ticket: int, new_tp: float) -> bool:
        """Update Take Profit posisi.

        Args:
            ticket: ticket number
            new_tp: harga TP baru

        Returns:
            True jika berhasil
        """
        return self._modify_sltp(ticket, tp=new_tp)

    def _modify_sltp(
        self,
        ticket: int,
        sl: float | None = None,
        tp: float | None = None,
    ) -> bool:
        """Internal: modify SL dan/atau TP.

        Gunakan mt5.order_send() dengan TRADE_ACTION_SLTP.
        """
        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            logger.error("modify_sltp: posisi ticket=%d tidak ditemukan", ticket)
            return False

        pos = position[0]

        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": self._symbol,
            "position": ticket,
            "sl": float(sl) if sl is not None else pos.sl,
            "tp": float(tp) if tp is not None else pos.tp,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            error_info = mt5.last_error()
            retcode = result.retcode if result else "N/A"
            logger.error("modify_sltp gagal: retcode=%s error=%s", retcode, error_info)
            return False

        logger.info(
            "modify_sltp OK: ticket=%d sl=%.4f tp=%.4f",
            ticket,
            float(sl) if sl else pos.sl,
            float(tp) if tp else pos.tp,
        )
        return True
