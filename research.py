"""
The lightweight half of "Research Lab" - single-asset statistics
computed directly off the running simulation's price history. No pair
analysis here (that needs a second correlated asset, which this
single-symbol sim doesn't have - see the README's known limitations),
but returns distribution, autocorrelation and a volatility-regime
label are all real, if simple, statistics.
"""

from __future__ import annotations
import statistics
from typing import List


def returns_series(prices: List[float]) -> List[float]:
    return [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(1, len(prices))
        if prices[i - 1] != 0
    ]


def returns_histogram(prices: List[float], bins: int = 20) -> dict:
    rets = returns_series(prices)
    if len(rets) < 2:
        return {"bin_edges": [], "counts": []}

    lo, hi = min(rets), max(rets)
    if lo == hi:
        lo -= 0.0001
        hi += 0.0001
    width = (hi - lo) / bins
    counts = [0] * bins
    for r in rets:
        idx = min(bins - 1, int((r - lo) / width))
        counts[idx] += 1

    edges = [round(lo + i * width, 5) for i in range(bins + 1)]
    return {
        "bin_edges": edges,
        "counts": counts,
        "mean": round(statistics.mean(rets), 6),
        "stdev": round(statistics.pstdev(rets), 6),
        "skew_hint": "right-skewed" if statistics.mean(rets) > statistics.median(rets) else "left-skewed",
    }


def autocorrelation(prices: List[float], max_lag: int = 5) -> List[dict]:
    """
    Lag-k autocorrelation of returns. Near zero at every lag is what an
    efficient, hard-to-predict-from-its-own-past market looks like -
    which, given several of our agents are literally trading on past
    price moves, is a genuinely interesting thing to check rather than
    assume.
    """
    rets = returns_series(prices)
    n = len(rets)
    if n < max_lag + 5:
        return []

    mean = statistics.mean(rets)
    var = sum((r - mean) ** 2 for r in rets) or 1e-9

    out = []
    for lag in range(1, max_lag + 1):
        cov = sum((rets[i] - mean) * (rets[i - lag] - mean) for i in range(lag, n))
        out.append({"lag": lag, "autocorrelation": round(cov / var, 4)})
    return out


def volatility_regime(current_volatility: float, history: List[float]) -> dict:
    """
    Labels the current realised-vol reading against its own recent
    history - a percentile-based regime label, not calibrated against
    any real market. "Calm" / "Elevated" / "Stressed" relative to this
    run's own recent past, nothing more.
    """
    sample = [v for v in history[-200:] if v > 0]
    if len(sample) < 10:
        return {"label": "insufficient data", "percentile": None}

    sorted_sample = sorted(sample)
    rank = sum(1 for v in sorted_sample if v <= current_volatility)
    percentile = round(rank / len(sorted_sample) * 100, 1)

    if percentile < 50:
        label = "calm"
    elif percentile < 85:
        label = "elevated"
    else:
        label = "stressed"

    return {"label": label, "percentile": percentile}


def half_split_stability_check(prices: List[float]) -> dict:
    """
    A crude, honestly-labelled stand-in for a real stationarity test
    (like an Augmented Dickey-Fuller test): splits returns into two
    halves and compares mean/variance. Big divergence between halves
    suggests the price process isn't behaving consistently over the
    sample - useful as a first pass, not a substitute for a proper
    statistical test.
    """
    rets = returns_series(prices)
    if len(rets) < 40:
        return {"verdict": "insufficient data", "detail": None}

    mid = len(rets) // 2
    first, second = rets[:mid], rets[mid:]
    mean1, mean2 = statistics.mean(first), statistics.mean(second)
    std1, std2 = statistics.pstdev(first) or 1e-9, statistics.pstdev(second) or 1e-9

    variance_ratio = max(std1, std2) / min(std1, std2)
    verdict = "looks roughly consistent" if variance_ratio < 1.8 else "variance shifted noticeably between halves"

    return {
        "verdict": verdict,
        "first_half_mean": round(mean1, 6),
        "second_half_mean": round(mean2, 6),
        "first_half_stdev": round(std1, 6),
        "second_half_stdev": round(std2, 6),
        "variance_ratio": round(variance_ratio, 2),
    }
