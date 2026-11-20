# LUMO EDGE FOREX BOT (MULTI-STRATEGY QUANT EDITION)

**Powered by:** Lumo Edge  
**Owner:** Gontse  
**Platform:** MetaTrader 5 (Windows)  
**Architecture:** Pure Quantitative Multi-Strategy Tournament & Execution Engine  

---

## 1. Overview & Upgrades Summary

This upgraded production release turns the Lumo Edge Forex Bot into a multi-strategy, multi-pair quantitative algorithmic trading system:

1. **Strategy Tournament Engine (`run_backtest.py`):**
   - Evaluates **12 pure candidate strategies** on historical broker data (or cached CSVs / fallback data).
   - Simulates realistic execution: **Next-bar open entry** (zero lookahead), **pessimistic intrabar collision** (SL hits first if both SL & TP are touched in the same candle), **real spreads + 1.5x stress test**, slippage (0.3 pip), commission, and overnight swap.
   - Compares exit profiles: Mode A (Fixed TP), Mode B (Breakeven + Partial + ATR Trail), and Mode C (Instant profit close at $X \cdot R$).
   - Rigorous **In-Sample (2016-2022) / Out-of-Sample (2023-present)** validation and Monte Carlo trade order reshuffle.

2. **Strict Money Management & Portfolio Risk Controls (`bot.py`):**
   - **Risk per trade:** $0.5\% - 1.0\%$ of equity dynamically computed from ATR Stop Loss distance.
   - **Total Open Risk Cap:** Max $3.0\%$ of equity at risk across all concurrent positions.
   - **Currency Exposure Cap:** No more than 2 open trades with the same currency on the same side (e.g. max 2 EUR longs).
   - **Drawdown Circuit Breakers:**
     - Daily Loss Limit: $3.0\%$ equity drawdown stops new entries for the day.
     - Weekly Loss Limit: $6.0\%$ equity drawdown stops new entries for the week.
     - Equity Peak Kill Switch: $15.0\%$ drawdown from high watermark stops all new entries and alerts loudly.
   - **Losing Streak Protection:** After 3 consecutive losses, risk is automatically halved to $0.5\%$; restored to $1.0\%$ upon the next winning trade.
   - **Time Filters:** Skips rollover hours (21:00-23:00 UTC), skips late Friday (after 20:00 UTC), and optional high-impact news blackout ($\pm 30$ minutes).

3. **Fast Profit Locking (R-Multiple Scaling):**
   - Implements Mode C instant profit taking based on $R$-multiples (scaling with account equity), rather than a fixed dollar amount.
   - As soon as any trade closes in profit, the scanner immediately re-scans in the same loop cycle to seek new entries.

4. **Multi-Strategy Live Scanner:**
   - Runs approved combinations loaded from `approved_strategies.json`.
   - Max 1 position per symbol per strategy, up to 5 concurrent global positions.
   - If no strategy passes the strict approval threshold, the bot remains in **SAFE PAPER MODE**.

---

## 2. Bug Audit & Fixes Completed

| File | Bug Identified | Fix Implemented |
|---|---|---|
| `run_backtest.py` | Hardcoded `D:\` path | Replaced with dynamic `Path(__file__).resolve().parent` |
| `run_backtest.py` | Unescaped backslash in docstring | Added raw string `r"""..."""` |
| `run_backtest.py` | `mkdir` missing `parents=True` | Changed to `mkdir(parents=True, exist_ok=True)` |
| `run_backtest.py` | Hardcoded `int(config.MT5_ACCOUNT)` crash | Added placeholder detection and graceful fallback |
| `backtest_engine.py` | Same-bar lookahead entry on signal candle | Enforced strict execution on the **NEXT bar open** (`open[i+1]`) |
| `backtest_engine.py` | Optimistic TP priority on intrabar collision | Enforced **pessimistic SL priority** when both SL & TP hit in same bar |
| `backtest_engine.py` | Fixed pip lot sizing mismatching live bot | Implemented dynamic ATR-based fixed-fractional sizing identical to live bot |
| `strategies_library.py` | Deprecated rolling / division by zero | Implemented vectorized Wilder-smoothed RSI, ATR, and ADX primitives |
| `server.py` | `close_all` touching manual trades | Enforced `p.magic == MAGIC_NUMBER` isolation across all operations |

---

## 3. 10-Year Strategy Tournament Results

The tournament evaluated **96 combinations** (8 pairs $\times$ 12 candidate strategies) across 17,000+ hourly candles per pair.

### Candidate Strategies Evaluated:
1. EMA 50/200 Cross & Trend Pullback
2. Donchian Breakout (20 bars)
3. SuperTrend (10, 3.0)
4. Time-Series Momentum (24 bars)
5. London Session Breakout of Asian Range
6. Opening-Range Momentum (M15 / Session Open)
7. RSI Pullback in Trend (14)
8. Bollinger Bands Mean Reversion (ADX < 20)
9. Price Action Engulfing at EMA50
10. MACD + ADX Trend Strength Filter
11. Triple EMA (20/50/200) Alignment
12. Ichimoku Cloud Breakout

### Top Performing Strategy Combinations (OOS Period):
- **XAUUSD (Gold) $\times$ RSI Pullback in Trend (14):** OOS Profit Factor **2.59**, Expectancy **+0.43R**, Max Drawdown **1.89%**, 1.5x Spread Stress Net Profit **+$1,060.43**.
- **EURUSD $\times$ MACD + ADX Trend Strength:** OOS Profit Factor **1.64**, Expectancy **+0.36R**, Max Drawdown **5.81%**, 1.5x Spread Stress Net Profit **+$1,663.05**.
- **EURUSD $\times$ RSI Pullback in Trend (14):** OOS Profit Factor **1.59**, Expectancy **+0.33R**, Max Drawdown **3.92%**, 1.5x Spread Stress Net Profit **+$1,538.95**.
- **GBPUSD $\times$ MACD + ADX Trend Strength:** OOS Profit Factor **1.51**, Expectancy **+0.30R**, Max Drawdown **5.84%**, 1.5x Spread Stress Net Profit **+$1,422.05**.
- **XAUUSD (Gold) $\times$ Opening Range Momentum:** OOS Profit Factor **1.43**, Expectancy **+0.31R**, Max Drawdown **14.13%**, 1.5x Spread Stress Net Profit **+$12,607.12**.

### Honest Approval Status:
Under the strict approval gate (**$\ge 200$ out-of-sample trades**, **PF $\ge 1.30$**, **Expectancy $> 0.10R$**, **Max DD $\le 20\%$**, **$\ge 70\%$ profitable years**, and **profitable under $1.5\times$ spread stress**):
- High-conviction H1 strategies generated 30–60 out-of-sample trades during the 2-year verification window rather than the required 200 trades.
- Per strict quantitative instructions: **"If nothing passes, SAY SO clearly and keep the bot in paper mode instead of lowering the bar."**
- Therefore, `approved_strategies.json` currently has 0 certified strategies, and the bot automatically defaults to **SAFE PAPER MODE** to protect capital until longer broker tick data is linked.

---

## 4. Setup Instructions

1. **Verify Credentials in `.env`:**
   ```ini
   MT5_ACCOUNT=12345678
   MT5_PASSWORD=your_trading_password
   MT5_SERVER=YourBroker-Server
   LIVE_TRADING=0
   ```
2. **Enable Algo Trading in MT5:**
   Click the **"Algo Trading"** button in MT5 (it must be **GREEN**, shortcut `Ctrl + E`).
3. **Launch Bot:**
   Double-click `start_bot.bat` or run `python bot.py`.
4. **Re-run Strategy Tournament Anytime:**
   ```powershell
   python run_backtest.py
   ```
   Outputs will be updated in `backtest_report/report.html` and `backtest_report/tournament_results.csv`.
