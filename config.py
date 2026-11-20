"""
=============================================================================
 LUMO EDGE FOREX BOT - CONFIGURATION
 Owner: Gontse | Powered by: Lumo Edge
=============================================================================
All settings and credentials. Credentials loaded exclusively from .env.
Never hardcode passwords or sensitive credentials in source code.
"""

import os
from pathlib import Path

# Base project path (never hardcode drive letters)
BASE_DIR = Path(__file__).resolve().parent

# --- .env loader (built-in parser, no external dependency required) -------
def _load_dotenv(filename=".env"):
    env_path = BASE_DIR / filename
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        os.environ.setdefault(k, v)
        except Exception:
            pass

_load_dotenv()

# --- Branding -------------------------------------------------------------
OWNER = "Gontse"
POWERED_BY = "Lumo Edge"

# --- MT5 Account Credentials (from .env only) -----------------------------
MT5_ACCOUNT_RAW = os.getenv("MT5_ACCOUNT", "").strip()
MT5_ACCOUNT = int(MT5_ACCOUNT_RAW) if MT5_ACCOUNT_RAW.isdigit() else None
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "").strip() or None
MT5_SERVER = os.getenv("MT5_SERVER", "").strip() or None
MT5_PATH = os.getenv("MT5_PATH", "").strip()

# --- Safety Switch: 0 = Paper Mode (Log only), 1 = Real Orders ------------
LIVE_TRADING = os.getenv("LIVE_TRADING", "0").strip() == "1"

# --- Placeholder values detection set -------------------------------------
PLACEHOLDER_ACCOUNTS = {"12345678", "0", 12345678, 0, None, ""}
PLACEHOLDER_PASSWORDS = {
    "your_trading_password", "your_password_here", "password",
    "123456", "admin", None, ""
}
PLACEHOLDER_SERVERS = {"YourBroker-Server", "broker_server_here", None, ""}

# --- Scanner Watchlist Symbols -------------------------------------------
# Dedicated to XAUUSDm (Gold) Only
SCANNER_SYMBOLS = [
    "XAUUSDm"
]
DEFAULT_TIMEFRAME = "M15"      # High-Expectancy M15 Timeframe (Eliminating M1 friction trap)
SCAN_INTERVAL_SECONDS = 2      # Stable 2-second Scan Loop

# --- Multi-Strategy Tournament & Approved Config -------------------------
APPROVED_STRATEGIES_FILE = str(BASE_DIR / "approved_strategies.json")
TRADES_LOG_FILE = str(BASE_DIR / "trades_log.csv")
DATA_DIR = str(BASE_DIR / "data")
BACKTEST_REPORT_DIR = str(BASE_DIR / "backtest_report")
NEWS_CALENDAR_FILE = str(BASE_DIR / "news_calendar.json")

# --- Strategy Baseline Parameters ----------------------------------------
EMA_FAST = 13                  # Optimized Fast EMA (was 50)
EMA_SLOW = 34                  # Optimized Slow EMA (was 200)
TREND_EMA = 200                # Macro Baseline Trend EMA
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70            # Filter: No BUY above 70
RSI_OVERSOLD = 30              # Filter: No SELL below 30
ADX_PERIOD = 14
ADX_MIN_THRESHOLD = 20.0       # Anti-chop filter: skip if ADX < 20.0
ATR_PERIOD = 14
CROSS_LOOKBACK = 3             # Lookback bars for fresh cross
MIN_EMA_GAP_ATR = 0.2          # Filter: skip if |EMA13 - EMA34| < 0.2 * ATR (ranging)

# --- Money Management & Strict Risk Controls -----------------------------
RISK_PERCENT = 0.30            # Conservative initial risk: 0.30% equity per trade (User target: 0.25%-0.5%)
MIN_RISK_PERCENT = 0.20        # Halved risk after consecutive losses
TOTAL_OPEN_RISK_CAP_PCT = 1.5  # Max total simultaneous open risk
MAX_OPEN_TRADES = 1            # Strictly 1 position per symbol to eliminate duplicate order spam
MAX_PER_SYMBOL_STRATEGY = 1    # Max 1 position per symbol per strategy
MAX_SAME_CURRENCY_EXPOSURE = 1 # Max 1 open trade per currency

SL_ATR_MULT = 1.0              # Stop Loss distance = 1.0 x ATR
TP_ATR_MULT = 1.5              # Take Profit distance = 1.5 x ATR (enforcing positive 1:1.5 R:R)
TP_RR = 1.5                    # Backup Take Profit R:R ratio
MAX_SPREAD_ATR_FRAC = 0.25     # Skip trade if spread > 25% of ATR
MAX_SPREAD_POINTS = 45.0       # Absolute spread ceiling: 45 points ($0.45 on Gold)
MAX_RISK_OVERSHOOT = 2.0       # Skip if min lot risks > 2x the target risk
COOLDOWN_MINUTES = 5           # Minutes before re-entering same pair (debounce)

# --- Circuit Breakers & Drawdown Limits -----------------------------------
MAX_DAILY_LOSS_PCT = 3.0       # Max daily loss (3% of start equity) stops new entries
MAX_WEEKLY_LOSS_PCT = 6.0      # Max weekly loss (% of start-of-week equity)
MAX_DD_KILL_SWITCH_PCT = 10.0  # Max drawdown from equity peak: stop opening, alert loudly (User target: < 10%)
CONSECUTIVE_LOSS_HALVE_COUNT = 3  # After 3 consecutive losses, halve risk; restore on win
MAX_CONSECUTIVE_LOSSES = 5     # After 5 consecutive losses, halt trading for the session

# --- Time & Session Filters -----------------------------------------------
SKIP_ROLLOVER_HOURS = [21, 22, 23]   # Rollover hours (widest spreads)
SKIP_FRIDAY_AFTER_HOUR = 20          # Skip opening trades after 20:00 UTC on Friday
NEWS_BLACKOUT_MINUTES = 30           # Minutes before/after high-impact news

# --- Instant Profit Taker -------------------------------------------------
MIN_PROFIT_USD = 0.50          # Minimum fallback profit in USD
PROFIT_LOCK_R_MULTIPLE = 0.75  # Close immediately when profit >= X * Initial Risk (R)
MAGIC_NUMBER = 786999          # Bot unique magic number

# --- Per-Pair Auto-Pause (Losing Streak Protection) -----------------------
PAIR_REVIEW_TRADES = 8         # Look at last 8 closed bot trades of each pair
PAIR_PAUSE_HOURS = 24          # Pause pair for 24h if net PnL is negative
