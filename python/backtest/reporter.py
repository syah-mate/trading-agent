"""
Backtest Reporter — TASK 6.2
Generate statistik dari list virtual trades.

Output:
- total_trades, winning_trades, losing_trades, win_rate
- avg_win_rr, avg_loss_rr, profit_factor
- max_drawdown, max_drawdown_duration
- equity_curve (untuk chart SvelteKit)
- best_trade, worst_trade
- trades_by_session, trades_by_direction
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def generate_stats(
    trades: list[dict[str, Any]],
    initial_balance: float = 10000.0,
    equity_curve: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate comprehensive statistics dari backtest trades.

    Args:
        trades: list virtual trades dengan fields:
                direction, entry_price, exit_price, pnl, sl, tp,
                session, exit_reason, monitoring_log
        initial_balance: balance awal
        equity_curve: optional — [{candle_index, equity, event}]

    Returns:
        dict statistik lengkap
    """
    total_trades = len(trades)

    if total_trades == 0:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "avg_win_rr": 0.0,
            "avg_loss_rr": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "max_drawdown_duration": 0,
            "equity_curve": equity_curve or [],
            "best_trade": {},
            "worst_trade": {},
            "trades_by_session": {},
            "trades_by_direction": {},
            "total_pnl": 0.0,
            "final_balance": initial_balance,
        }

    # Basic counts
    winning = [t for t in trades if t.get("pnl", 0) > 0]
    losing = [t for t in trades if t.get("pnl", 0) <= 0]
    winning_trades = len(winning)
    losing_trades = len(losing)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    # PnL
    gross_profit = sum(t.get("pnl", 0) for t in winning)
    gross_loss = abs(sum(t.get("pnl", 0) for t in losing))

    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (
        999.0 if gross_profit > 0 else 0.0
    )

    total_pnl = sum(t.get("pnl", 0) for t in trades)
    final_balance = initial_balance + total_pnl

    # Average R:R
    avg_win_rr = _avg_rr(winning)
    avg_loss_rr = _avg_rr(losing)

    # Best / Worst trade
    sorted_by_pnl = sorted(trades, key=lambda t: t.get("pnl", 0), reverse=True)
    best_trade = _summarize_trade(sorted_by_pnl[0]) if sorted_by_pnl else {}
    worst_trade = _summarize_trade(sorted_by_pnl[-1]) if sorted_by_pnl else {}

    # Max drawdown from equity curve
    max_dd, max_dd_duration = _calculate_drawdown(
        equity_curve, initial_balance
    )

    # Trades by session
    trades_by_session: dict[str, int] = {}
    for t in trades:
        session = t.get("session", "Other")
        trades_by_session[session] = trades_by_session.get(session, 0) + 1

    # Trades by direction
    trades_by_direction: dict[str, int] = {}
    for t in trades:
        direction = t.get("direction", "UNKNOWN")
        trades_by_direction[direction] = trades_by_direction.get(direction, 0) + 1

    return {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": round(win_rate, 2),
        "avg_win_rr": round(avg_win_rr, 4),
        "avg_loss_rr": round(avg_loss_rr, 4),
        "profit_factor": round(profit_factor, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "total_pnl": round(total_pnl, 2),
        "initial_balance": initial_balance,
        "final_balance": round(final_balance, 2),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_duration": max_dd_duration,
        "equity_curve": equity_curve or [],
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "trades_by_session": trades_by_session,
        "trades_by_direction": trades_by_direction,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _avg_rr(trades: list[dict[str, Any]]) -> float:
    """Hitung rata-rata R:R dari list trades."""
    rrs: list[float] = []
    for t in trades:
        entry = t.get("entry_price", 0)
        sl = t.get("sl", 0)
        pnl = t.get("pnl", 0)
        lot_size = t.get("lot_size", 0.01)

        if sl and sl > 0 and entry > 0:
            risk = abs(entry - sl) * 10000 * lot_size * 10
            if risk > 0:
                rrs.append(pnl / risk)
    return sum(rrs) / len(rrs) if rrs else 0.0


def _calculate_drawdown(
    equity_curve: list[dict[str, Any]] | None,
    initial_balance: float,
) -> tuple[float, int]:
    """Hitung max drawdown (%) dan durasi dari equity curve."""
    if not equity_curve:
        return 0.0, 0

    peak = initial_balance
    max_dd = 0.0
    max_dd_duration = 0
    current_dd_duration = 0

    for point in equity_curve:
        equity = point.get("equity", initial_balance)

        if equity > peak:
            peak = equity
            current_dd_duration = 0
        else:
            current_dd_duration += 1
            dd_pct = (peak - equity) / peak * 100
            if dd_pct > max_dd:
                max_dd = dd_pct
            if current_dd_duration > max_dd_duration:
                max_dd_duration = current_dd_duration

    return max_dd, max_dd_duration


def _summarize_trade(trade: dict[str, Any]) -> dict[str, Any]:
    """Ringkasan 1 trade untuk best/worst."""
    return {
        "direction": trade.get("direction", ""),
        "entry_price": trade.get("entry_price", 0),
        "exit_price": trade.get("exit_price", 0),
        "pnl": round(trade.get("pnl", 0), 2),
        "exit_reason": trade.get("exit_reason", ""),
        "candles_held": (
            trade.get("closed_at_candle", 0) - trade.get("opened_at_candle", 0)
        ),
        "session": trade.get("session", ""),
    }
