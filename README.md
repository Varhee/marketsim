# MarketSim

A small event-driven market simulator: a real limit order book, a
price-time-priority matching engine, and a handful of trading agents
(noise, momentum, mean-reversion, market makers, an institutional
trader) that trade against each other. There's a FastAPI backend that
streams the simulation over a WebSocket, and a single-page dashboard
that renders it live - order book, price chart, trade tape, scenario
buttons.

Started life as a much bigger idea (research lab, bias detector,
evolutionary agents, the works) and got scoped down deliberately.
Everything here actually runs. The bigger stuff is listed at the
bottom as "what's next," not pretended into existence.

## Running it

```bash
cd marketsim
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Then open `http://localhost:8000`. The market starts trading
immediately - noise traders and market makers keep it ticking over on
their own, no input needed. That's intentional, not a bug: the price
moves in the background all the time; **Run scenario** just injects
one deliberate shock on top of the ambient activity. Use **Pause** if
you want the book to sit still.

The dashboard has six sections, in the sidebar:

- **Market** - the live order book, price chart, trade tape, and a
  running position/P&L strip per agent.
- **Portfolio & Risk** - a fuller P&L table sorted by who's winning,
  aggregate market stats, and a rolling realised-volatility chart.
- **Scenarios** - the three shocks as cards with a real explanation of
  what each one does, plus a log that records price-before and
  price-40-ticks-later for every scenario you run this session.
- **Strategies** - momentum and mean-reversion backtests, run against
  this session's actual simulated price history (not synthetic data).
  Adjustable lookback/threshold/position-size/stop-loss/transaction-cost
  parameters, an equity curve vs buy-and-hold, and a bias-detector
  panel that flags small sample size, zero transaction costs, and the
  lack of out-of-sample testing on every run.
- **Research Lab** - returns distribution, lag-1-through-5
  autocorrelation of returns, a volatility-regime badge (calm /
  elevated / stressed, relative to this run's own recent history),
  and a first-half-vs-second-half consistency check. No pair analysis
  or cointegration testing - this is a single-asset sim, see "known
  limitations."
- **Learn** - a couple of short explainers, including a clickable
  mini order book that mirrors whatever the live book currently looks
  like.

No frontend build step - `frontend/index.html` is plain HTML/CSS/JS,
served straight off disk by the backend.

## Using it without the UI at all

The engine doesn't know the API or the frontend exist. You can run
the whole thing from a script or a REPL:

```python
from sim_factory import build_simulation

sim = build_simulation(seed=42)
for _ in range(200):
    sim.step()

print(sim.price_history[-1], sim.book.spread(), sim.realized_volatility())
```

That's what `experiments/mm_liquidity_experiment.py` does - runs the
sim headless, across multiple seeds, and prints a comparison table.

## What's actually in here

```
marketsim/
├── engine/              order book + matching engine (price-time priority)
├── agents/               noise / momentum / mean-reversion / market maker / institutional
├── simulation.py         ties agents + engine together, steps the market forward
├── sim_factory.py        the "standard" agent population used everywhere
├── backend/main.py       FastAPI: REST control endpoints + WebSocket feed
├── frontend/index.html   live dashboard (order book, chart, trade tape)
├── experiments/          headless research scripts
└── tests/                order book / matching engine tests
```

### The matching engine

Supports market and limit orders, cancellation, partial fills, and
strict price-time priority - two orders at the same price fill in the
order they arrived. It also does self-trade prevention: an agent
can't fill against its own resting order (this came up for real - a
market maker updating its skew mid-run would otherwise occasionally
cross its own quote and "trade with itself", which isn't a thing real
exchanges let happen).

`tests/test_order_book.py` covers price-time priority, partial fills
across multiple price levels, market orders never resting, and the
self-trade case.

### The agents

Each agent only sees the current book and the recent price history,
and returns orders - it never touches the book directly. Market
makers are the interesting one: they quote both sides for the spread,
but skew their quotes as inventory builds up, and pull out of the
market entirely past a configurable inventory limit. That skew
behaviour is what turns "market maker exists" into "market maker
starts amplifying the move once they're overloaded," which is a real
phenomenon and not just flavour text.

### The "flash crash" scenario, and a real finding from testing it

Injecting a flash crash schedules the institutional agent to sell
3,000 shares over the next several ticks. First version of this
dumped 8,000 shares in 3 ticks and briefly sent the price into
negative numbers, which - for the avoidance of doubt - is not a thing
that happens to equities. Fixed by flooring prices at £0.01 and
tuning the shock size against actual book depth rather than a
round-sounding number. Calibrated version now produces something in
the -5% to -15% range depending on seed, which is in the right
ballpark for what a real flash crash looks like.

Running the comparison experiment (`experiments/mm_liquidity_experiment.py`)
turned up something worth knowing about before you draw conclusions
from a metric: a market *without* market makers looks calmer under
the same shock, but only because most of the institutional order
never fills - there's no resting liquidity to sell into. That's not
resilience, it's an order that can't execute. The honest comparison
is impact-per-share-actually-filled, not impact-per-market. Left the
fill-rate column in the output specifically so that trap is visible
rather than hidden.

A second, separate bug showed up while stress-testing the same
scenario over a longer horizon (400+ ticks instead of the ~100 used
above): with only one mean-reversion agent, the momentum agent could
enter a self-reinforcing spiral - price drops, momentum sells into
the drop, price drops further - that eventually ran the price down to
the floor with no recovery, regardless of shock size. Fixed by adding
a second mean-reversion agent and reducing the momentum agent's
sensitivity slightly. Re-tested across six seeds over 650 ticks after
the fix: no floor hits, and the shock still produces a visible
(-3.5% to -11%) drawdown in the first 40 ticks, which is what the
dashboard's scenario log actually reports.

### The Strategies page

Momentum and mean-reversion are both real signal-based backtests
(`strategies.py`) run against whatever price history this session's
simulation has actually generated - not a canned dataset. Position
changes incur transaction costs (in basis points, configurable), and
a stop-loss forces an exit if an open position moves against you past
a threshold. Metrics (total return, Sharpe, max drawdown, win rate)
are computed the standard way off the resulting equity curve, checked
against a plain buy-and-hold baseline over the same period.

The "bias detector" is genuinely rule-based, not decorative: it flags
small sample sizes, zero transaction costs, and - on every single run,
because it's true on every single run - the fact that this is one
in-sample backtest with no out-of-sample or walk-forward validation.
Testing the mean-reversion strategy turned up a good example of why
that last warning matters: at default settings it can post a 100%+ win
rate on individual trades while still *losing* money overall, because
transaction costs on frequent small trades outweigh the gains. That's
a real result from this codebase, not a hypothetical.

### The Research Lab page

Single-asset statistics only - returns distribution, autocorrelation,
a volatility-regime label relative to the run's own recent history,
and a crude first-half-vs-second-half consistency check (explicitly
*not* a real stationarity test like Augmented Dickey-Fuller - it says
so in the UI). No pair analysis or cointegration testing, because
that needs a second, correlated asset, and this sim only runs one
symbol. Worth noting: this market's return series shows real, visible
negative autocorrelation at lag 1 in testing - a plausible signature
of the mean-reversion and market-maker agents in the population, not
noise.

## Known limitations

- Single asset only - no pairs trading, no correlation structure.
- Agents react to the current tick's book, not to each other's
  intentions - there's no order anticipation or spoofing.
- No latency, no queue-jumping, no regulatory constraints (circuit
  breakers, uptick rules) - real market microstructure has a lot more
  friction than this.
- The market maker's inventory-skew model is a simplification, not a
  calibrated one - the numbers came from testing until behaviour
  looked sensible, not from real market-making literature.
- Self-trade prevention skips the offending order in FIFO order
  rather than fully preserving queue position for every other order
  at that price level - a reasonable simplification for a toy engine,
  not how a real venue implements STP.


