"""
A deliberately simple backtester: it runs a signal-based strategy
against a plain price series (not the live order book - that would
mean re-simulating history, which we don't have) and turns the signal
into an equity curve, with transaction costs charged on every position
change. This is the "quant research" side of the project - simple
enough to read in five minutes, but the metrics it produces (Sharpe,
max drawdown, win rate) are computed the normal way, not faked.

Both strategies here are long/flat/short signal generators - they
don't place real orders, they just decide "long", "short" or "flat"
each tick, and get marked to market against actual price moves.
"""

from __future__ import annotations
import statistics
from typing import List, Optional
from dataclasses import dataclass, field


@dataclass
class Trade:
    entry_tick: int
    exit_tick: int
    direction: str  # "long" or "short"
    entry_price: float
    exit_price: float
    pnl: float


@dataclass
class BacktestResult:
    equity_curve: List[float]
    buy_hold_curve: List[float]
    trades: List[Trade]
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate_pct: float
    num_trades: int
    total_transaction_costs: float
    warnings: List[str] = field(default_factory=list)


def _max_drawdown(curve: List[float]) -> float:
    peak = curve[0]
    worst = 0.0
    for v in curve:
        peak = max(peak, v)
        dd = (v - peak) / peak if peak else 0.0
        worst = min(worst, dd)
    return round(worst * 100, 2)


def _sharpe(returns: List[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = statistics.mean(returns)
    stdev = statistics.pstdev(returns)
    if stdev == 0:
        return 0.0
    # tick-scale Sharpe, annualised with the same toy scaling used elsewhere in the project
    return round((mean / stdev) * (252 ** 0.5), 3)


def bias_warnings(prices: List[float], transaction_cost_bps: float, min_sample: int = 300) -> List[str]:
    """
    The 'bias detector' from the design brief - lightweight, rule-based
    checks run before/alongside a backtest. These are heuristics, not
    a rigorous statistical test suite, and they say so.
    """
    warnings = []
    if len(prices) < min_sample:
        warnings.append(
            f"Only {len(prices)} price points available - under {min_sample}, results here are indicative at best."
        )
    if transaction_cost_bps == 0:
        warnings.append("Transaction costs are set to zero - real execution costs would eat into this return.")
    warnings.append(
        "This is a single in-sample run against one simulated price path - no out-of-sample "
        "or walk-forward validation has been performed. Treat any positive result with suspicion "
        "until it survives a fresh, unseen path."
    )
    return warnings


def _run_signal_backtest(
    prices: List[float],
    signals: List[int],  # -1, 0, 1 per tick (short/flat/long), same length as prices
    position_size_pct: float,
    stop_loss_pct: float,
    transaction_cost_bps: float,
    starting_capital: float = 100_000.0,
) -> BacktestResult:
    equity = starting_capital
    equity_curve = [equity]
    buy_hold_curve = [starting_capital]
    trades: List[Trade] = []

    current_direction = 0  # -1, 0, 1
    entry_price = None
    entry_tick = None
    total_costs = 0.0
    per_tick_returns: List[float] = []

    bh_units = starting_capital / prices[0]

    for i in range(1, len(prices)):
        price = prices[i]
        prev_price = prices[i - 1]
        buy_hold_curve.append(bh_units * price)

        desired = signals[i]

        # stop-loss check on an open position, evaluated before acting on new signals
        if current_direction != 0 and entry_price:
            move = (price - entry_price) / entry_price * current_direction
            if move <= -stop_loss_pct:
                desired = 0  # forced flat

        # position change -> realize the trade, pay transaction costs
        if desired != current_direction:
            notional = equity * position_size_pct
            cost = notional * (transaction_cost_bps / 10_000)
            total_costs += cost
            equity -= cost

            if current_direction != 0 and entry_price is not None:
                pnl = (price - entry_price) / entry_price * current_direction * notional
                equity += pnl
                trades.append(Trade(
                    entry_tick=entry_tick, exit_tick=i, direction="long" if current_direction > 0 else "short",
                    entry_price=entry_price, exit_price=price, pnl=round(pnl, 2),
                ))

            current_direction = desired
            entry_price = price if desired != 0 else None
            entry_tick = i if desired != 0 else None
        elif current_direction != 0:
            # mark-to-market the open position each tick without closing it
            notional = equity * position_size_pct
            tick_pnl = (price - prev_price) / prev_price * current_direction * notional
            equity += tick_pnl

        equity_curve.append(equity)
        per_tick_returns.append((equity_curve[-1] - equity_curve[-2]) / equity_curve[-2] if equity_curve[-2] else 0.0)

    # force-close any position still open at the end of the series, purely
    # for reporting purposes - the equity curve already reflects its
    # mark-to-market value each tick, this just gives it a recorded trade
    # so num_trades/win_rate aren't misleadingly zero for an open winner
    if current_direction != 0 and entry_price is not None:
        final_price = prices[-1]
        notional = equity * position_size_pct
        pnl = (final_price - entry_price) / entry_price * current_direction * notional
        trades.append(Trade(
            entry_tick=entry_tick, exit_tick=len(prices) - 1, direction="long" if current_direction > 0 else "short",
            entry_price=entry_price, exit_price=final_price, pnl=round(pnl, 2),
        ))
        # note: no additional pnl or cost applied to equity here - it's already
        # been marked to market tick by tick in the loop above

    total_return_pct = round((equity - starting_capital) / starting_capital * 100, 2)
    winning = [t for t in trades if t.pnl > 0]
    win_rate = round(len(winning) / len(trades) * 100, 1) if trades else 0.0

    return BacktestResult(
        equity_curve=[round(v, 2) for v in equity_curve],
        buy_hold_curve=[round(v, 2) for v in buy_hold_curve],
        trades=trades,
        total_return_pct=total_return_pct,
        sharpe_ratio=_sharpe(per_tick_returns),
        max_drawdown_pct=_max_drawdown(equity_curve),
        win_rate_pct=win_rate,
        num_trades=len(trades),
        total_transaction_costs=round(total_costs, 2),
    )


def momentum_signals(prices: List[float], lookback: int, entry_threshold_pct: float) -> List[int]:
    signals = [0] * len(prices)
    for i in range(lookback, len(prices)):
        past = prices[i - lookback]
        if past == 0:
            continue
        move = (prices[i] - past) / past
        if move > entry_threshold_pct:
            signals[i] = 1
        elif move < -entry_threshold_pct:
            signals[i] = -1
        else:
            signals[i] = signals[i - 1]  # hold previous stance until a fresh signal fires
    return signals


def mean_reversion_signals(prices: List[float], window: int, z_threshold: float) -> List[int]:
    signals = [0] * len(prices)
    for i in range(window, len(prices)):
        recent = prices[i - window:i]
        mean = statistics.mean(recent)
        stdev = statistics.pstdev(recent) or 0.0001
        z = (prices[i] - mean) / stdev
        if z > z_threshold:
            signals[i] = -1  # too far above mean -> bet on a pullback
        elif z < -z_threshold:
            signals[i] = 1
        elif abs(z) < 0.3:
            signals[i] = 0  # close to fair value -> flatten
        else:
            signals[i] = signals[i - 1]
    return signals


def run_backtest(
    strategy: str,
    prices: List[float],
    params: dict,
) -> BacktestResult:
    position_size_pct = params.get("position_size_pct", 0.10)
    stop_loss_pct = params.get("stop_loss_pct", 0.05)
    transaction_cost_bps = params.get("transaction_cost_bps", 5)

    if strategy == "momentum":
        lookback = int(params.get("lookback", 20))
        entry_threshold_pct = params.get("entry_threshold_pct", 0.02)
        signals = momentum_signals(prices, lookback, entry_threshold_pct)
    elif strategy == "mean_reversion":
        window = int(params.get("window", 30))
        z_threshold = params.get("z_threshold", 1.5)
        signals = mean_reversion_signals(prices, window, z_threshold)
    else:
        raise ValueError(f"unknown strategy: {strategy}")

    result = _run_signal_backtest(prices, signals, position_size_pct, stop_loss_pct, transaction_cost_bps)
    result.warnings = bias_warnings(prices, transaction_cost_bps)
    return result
