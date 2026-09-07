"""
Thin API layer over the simulation. The engine doesn't know this file
exists - it's perfectly usable from a plain Python script (see
sim_factory.py / tests) - this is just what lets a browser watch it
happen live.

Run with:
    uvicorn backend.main:app --reload --port 8000
from the marketsim/ directory.
"""

from __future__ import annotations
import asyncio
import sys
import os
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from engine import Side
from sim_factory import build_simulation
from strategies import run_backtest
from research import returns_histogram, autocorrelation, volatility_regime, half_split_stability_check

app = FastAPI(title="MarketSim")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

state = {
    "sim": build_simulation(seed=None),
    "running": True,
    "speed": 1.0,  # ticks/sec multiplier
    "scenario_log": [],  # list of {kind, tick_triggered, price_before, resolve_at_tick, price_after, resolved}
}
BASE_INTERVAL = 0.4  # seconds per tick at speed=1
SCENARIO_RESOLVE_AFTER_TICKS = 40


def snapshot() -> dict:
    sim = state["sim"]
    depth = sim.book.depth()
    recent_trades = sim.book.trade_history[-15:][::-1]
    current_price = sim.price_history[-1]

    # resolve any scenario log entries whose window has elapsed
    for entry in state["scenario_log"]:
        if not entry["resolved"] and sim.tick_count >= entry["resolve_at_tick"]:
            entry["price_after"] = current_price
            entry["resolved"] = True
            entry["move_pct"] = round((current_price - entry["price_before"]) / entry["price_before"] * 100, 2)

    return {
        "tick": sim.tick_count,
        "price": current_price,
        "price_history": sim.price_history[-120:],
        "volatility_history": sim.volatility_history[-120:],
        "best_bid": sim.book.best_bid(),
        "best_ask": sim.book.best_ask(),
        "spread": sim.book.spread(),
        "volatility": sim.realized_volatility(),
        "liquidity_score": sim.liquidity_score(),
        "total_volume": sim.total_volume,
        "total_trades": len(sim.book.trade_history),
        "depth": depth,
        "trades": [
            {
                "price": t.price,
                "quantity": t.quantity,
                "buyer": t.buyer_id,
                "seller": t.seller_id,
                "aggressor": t.aggressor.value,
                "timestamp": t.timestamp,
            }
            for t in recent_trades
        ],
        "agents": [
            {
                "id": a.agent_id,
                "type": a.__class__.__name__,
                "position": a.position,
                "cash": round(a.cash, 2),
                "pnl": a.mark_to_market_pnl(current_price),
            }
            for a in sim.agents.values()
        ],
        "scenario_log": list(reversed(state["scenario_log"][-20:])),
        "running": state["running"],
        "speed": state["speed"],
    }


# -- REST control endpoints --------------------------------------------

@app.get("/api/state")
def get_state():
    return snapshot()


@app.post("/api/control/pause")
def pause():
    state["running"] = False
    return {"running": False}


@app.post("/api/control/resume")
def resume():
    state["running"] = True
    return {"running": True}


@app.post("/api/control/speed/{multiplier}")
def set_speed(multiplier: float):
    state["speed"] = max(0.25, min(10.0, multiplier))
    return {"speed": state["speed"]}


@app.post("/api/control/reset")
def reset(seed: Optional[int] = None):
    state["sim"] = build_simulation(seed=seed)
    state["running"] = True
    state["scenario_log"] = []
    return {"status": "reset"}


@app.post("/api/scenario/{kind}")
def run_scenario(kind: str):
    valid = {"flash_crash", "liquidity_crisis", "volatility_spike"}
    if kind not in valid:
        return {"error": f"unknown scenario, expected one of {sorted(valid)}"}
    sim = state["sim"]
    record = sim.inject_shock(kind)
    state["scenario_log"].append({
        "kind": record["kind"],
        "tick_triggered": record["tick"],
        "price_before": record["price_before"],
        "resolve_at_tick": record["tick"] + SCENARIO_RESOLVE_AFTER_TICKS,
        "price_after": None,
        "move_pct": None,
        "resolved": False,
    })
    return {"status": "triggered", "scenario": kind}


# -- research lab ---------------------------------------------------------

@app.get("/api/research/stats")
def research_stats():
    sim = state["sim"]
    prices = sim.price_history
    return {
        "sample_size": len(prices),
        "returns_histogram": returns_histogram(prices),
        "autocorrelation": autocorrelation(prices),
        "volatility_regime": volatility_regime(sim.realized_volatility(), sim.volatility_history),
        "stability_check": half_split_stability_check(prices),
    }


# -- strategies / backtesting ----------------------------------------------

@app.post("/api/strategy/backtest")
def backtest(
    strategy: str,
    lookback: int = 20,
    entry_threshold_pct: float = 0.02,
    window: int = 30,
    z_threshold: float = 1.5,
    position_size_pct: float = 0.10,
    stop_loss_pct: float = 0.05,
    transaction_cost_bps: float = 5.0,
):
    sim = state["sim"]
    prices = sim.price_history
    if len(prices) < 40:
        return {"error": "Not enough price history yet - let the market run a bit longer before backtesting."}

    params = {
        "lookback": lookback,
        "entry_threshold_pct": entry_threshold_pct,
        "window": window,
        "z_threshold": z_threshold,
        "position_size_pct": position_size_pct,
        "stop_loss_pct": stop_loss_pct,
        "transaction_cost_bps": transaction_cost_bps,
    }
    try:
        result = run_backtest(strategy, prices, params)
    except ValueError as e:
        return {"error": str(e)}

    return {
        "strategy": strategy,
        "params": params,
        "total_return_pct": result.total_return_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown_pct": result.max_drawdown_pct,
        "win_rate_pct": result.win_rate_pct,
        "num_trades": result.num_trades,
        "total_transaction_costs": result.total_transaction_costs,
        "equity_curve": result.equity_curve[-300:],
        "buy_hold_curve": result.buy_hold_curve[-300:],
        "warnings": result.warnings,
    }


# -- live feed -----------------------------------------------------------

connected_sockets: list[WebSocket] = []


@app.websocket("/ws")
async def market_feed(websocket: WebSocket):
    await websocket.accept()
    connected_sockets.append(websocket)
    try:
        while True:
            await websocket.send_json(snapshot())
            await asyncio.sleep(1)  # keepalive/ping; real pushes happen in the tick loop below
    except WebSocketDisconnect:
        connected_sockets.remove(websocket)


async def tick_loop():
    while True:
        if state["running"]:
            state["sim"].step()
            payload = snapshot()
            dead = []
            for ws in connected_sockets:
                try:
                    await ws.send_json(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                if ws in connected_sockets:
                    connected_sockets.remove(ws)
        await asyncio.sleep(BASE_INTERVAL / state["speed"])


@app.on_event("startup")
async def startup():
    asyncio.create_task(tick_loop())


# serve the dashboard itself
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")


@app.get("/")
def index():
    return FileResponse(os.path.join(frontend_dir, "index.html"))


app.mount("/static", StaticFiles(directory=frontend_dir), name="static")
