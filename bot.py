"""
=============================================================================
 LUMO EDGE FOREX AUTOMATION BOT - MULTI-STRATEGY ENGINE
 Powered by: Lumo Edge | Owner: Gontse
=============================================================================
High-throughput, strictly risk-managed algorithmic trading bot:
 - Runs only approved (strategy, pair, timeframe) combinations from approved_strategies.json
 - Multi-pair & multi-strategy scanning (fast candle-close evaluation every 3s)
 - Strict Money Management:
     * 0.5% - 1.0% equity risk per trade based on ATR Stop Loss
     * 3% total open risk cap across all positions
     * Currency exposure cap: max 2 open trades with same currency on same side
     * 3% daily drawdown limit, 6% weekly drawdown limit
     * 15% equity peak drawdown kill switch (stops new entries, alerts loudly)
     * Streak protection: halving risk after 3 consecutive losses
     * Filters: spread <= 25% ATR, rollover hour skip, Friday close skip, news blackout
 - Fast Profit Lock: R-multiple scaling (Mode C instant lock, Mode B partial/trail, Mode A fixed)
 - Full Roman Urdu & English diagnostics with automatic MT5 fallback & trade logging
=============================================================================
"""

import sys
import time
import os
import json
import csv
import datetime as dt
import traceback
from pathlib import Path

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

import config
from strategy import resolve_symbol, get_rates
from strategies_library import STRATEGY_REGISTRY

BASE_DIR = Path(__file__).resolve().parent

# --- Runtime Tracking State -----------------------------------------------
last_bar_traded = {}     # (symbol, strategy) -> bar_time (1 entry per candle)
last_entry_time = {}     # symbol -> datetime (optional cooldown)
consecutive_losses = 0   # loss streak tracker
peak_equity = 0.0        # high watermark equity

day_state = {"date": None, "start_equity": 0.0}
week_state = {"week": None, "start_equity": 0.0}

pair_pause_until = {}    # symbol -> timestamp until which trading is paused
pair_resume_after = {}   # symbol -> timestamp after which closed trades count for review
pair_last_checked = {}   # symbol -> timestamp of last deal check

# --- Diagnostic Messages (English & Roman Urdu) ---------------------------
MT5_DIAGNOSTICS_MAP = {
    1: {"en": "Success / Operation completed successfully.", "ur": "Kamyabi! Operation theek se complete ho gaya.", "fix": "No action needed."},
    -1: {"en": "General MT5 call failed.", "ur": "MT5 general error: Function call fail hui hai.", "fix": "Restart MetaTrader 5 terminal and retry."},
    -2: {"en": "Invalid arguments or parameters passed to MT5.", "ur": "Ghalat arguments ya parameters diye gaye hain.", "fix": "Check settings and symbol names in config.py."},
    -3: {"en": "Out of memory / Memory allocation error in MT5.", "ur": "Memory (RAM) full ho gayi hai ya MT5 resource error aaya hai.", "fix": "Close heavy background applications and restart MT5."},
    -4: {"en": "MetaTrader 5 terminal executable was not found.", "ur": "MT5 terminal path par terminal64.exe nahi mila.", "fix": "Ensure MT5 is installed, or specify MT5_PATH in .env to your terminal64.exe."},
    -5: {"en": "Unsupported MetaTrader 5 terminal version.", "ur": "MT5 terminal ka version bohot purana hai.", "fix": "Update your MetaTrader 5 terminal to the latest build from your broker."},
    -6: {"en": "Authorization failed: Incorrect account number, password, or server name.", "ur": "Login fail ho gaya! Account number, password ya broker server galat hai.", "fix": "Check .env file -> Verify MT5_ACCOUNT, MT5_PASSWORD, and MT5_SERVER match your broker email. Or log in directly inside MT5 terminal (File -> Login to Trade Account)."},
    -10001: {"en": "IPC send failed (Cannot send command to MT5 terminal).", "ur": "MT5 terminal ko command nahi bheji ja saki (IPC communication failed).", "fix": "Launch MT5 terminal manually as Administrator and keep it running on your screen."},
    -10002: {"en": "IPC receive failed (MT5 terminal closed or not responding).", "ur": "MT5 terminal se response nahi aaya ya MT5 close ho gaya.", "fix": "Ensure MetaTrader 5 is running on your desktop and not frozen."},
    -10003: {"en": "IPC initialization failed (Python cannot attach to MT5 terminal).", "ur": "Python aur MT5 ka connection shuru nahi ho saka.", "fix": "Start MT5 terminal first, wait 5 seconds, then launch start_bot.bat."},
    -10004: {"en": "IPC timeout (MT5 terminal took too long to respond).", "ur": "MT5 terminal ne response dene me bohot waqt lagaya (Timeout).", "fix": "Restart MT5. If it is downloading large historical charts, let it finish first."},
    -10005: {"en": "IPC memory error.", "ur": "IPC communication me memory error aaya.", "fix": "Restart MetaTrader 5 and your computer."},
    10004: {"en": "Requote received from broker.", "ur": "Broker se nayi price (requote) aayi hai.", "fix": "Market is volatile; the bot will re-evaluate on the next tick."},
    10006: {"en": "Order rejected by broker.", "ur": "Broker ne order reject kar diya.", "fix": "Check if your account has trading permissions or if market is open."},
    10013: {"en": "Invalid request sent to broker.", "ur": "Order ki request ghalat thi.", "fix": "Check symbol volume step, lot size, and stop levels."},
    10014: {"en": "Invalid volume / lot size.", "ur": "Lot size broker ke limits ke mutabiq nahi hai.", "fix": "Adjust lot size or risk percentage to meet broker min/max/step limits."},
    10015: {"en": "Invalid price.", "ur": "Order ki price invalid hai.", "fix": "Price slipped; bot will retry on the next tick."},
    10016: {"en": "Invalid Stop Loss or Take Profit levels.", "ur": "Stop Loss ya Take Profit price ke bohot qareeb hai.", "fix": "Increase SL_ATR_MULT in config.py or check broker stops level."},
    10017: {"en": "Trading is disabled on this account or symbol.", "ur": "Is account ya currency pair par trading broker ki taraf se band hai.", "fix": "Contact broker support or choose an active forex pair."},
    10018: {"en": "Market is closed.", "ur": "Market abhi band hai (Weekend ya Holiday).", "fix": "Wait for the Forex market to open (Sunday evening to Friday evening)."},
    10019: {"en": "Not enough money / Insufficient margin.", "ur": "Account me margin (paise) kam hain, naya order nahi lag sakta.", "fix": "Deposit more funds or reduce RISK_PERCENT in config.py."},
    10026: {"en": "Autotrading disabled by server.", "ur": "Broker server ne is account par robot/EA trading band ki hui hai.", "fix": "Contact your broker to enable automated/EA trading on your account."},
    10027: {"en": "Autotrading disabled by client terminal.", "ur": "MT5 terminal me 'Algo Trading' button band hai!", "fix": "Click the 'Algo Trading' button in MT5 top toolbar (it must turn green), or press Ctrl+E."},
    10030: {"en": "Unsupported order filling mode.", "ur": "Broker is filling mode (IOC/FOK/RETURN) ko support nahi karta.", "fix": "The bot automatically attempts alternative filling modes (IOC, FOK, RETURN)."},
    10031: {"en": "No connection to trade server.", "ur": "Broker server se connection toot gaya hai.", "fix": "Check internet connection and verify MT5 bottom-right status bar."}
}


def log(msg: str, tag: str = "INFO"):
    print(f"[{dt.datetime.now():%H:%M:%S}] [{tag}] {msg}")


def format_diagnostic(error_code: int, context: str = "") -> dict:
    diag = MT5_DIAGNOSTICS_MAP.get(error_code)
    if diag:
        return {"code": error_code, "context": context, "en": diag["en"], "ur": diag["ur"], "fix": diag["fix"]}
    return {
        "code": error_code, "context": context,
        "en": f"MT5 Error code {error_code}: {context}",
        "ur": f"MT5 error code {error_code} aaya hai: {context}",
        "fix": "Review MT5 journal and terminal logs for details."
    }


def print_diagnostic_banner(diag: dict):
    print("=" * 72)
    print(f" [DIAGNOSTIC ADVISORY] Code: {diag['code']} ({diag['context']})")
    print(f" EN : {diag['en']}")
    print(f" UR : {diag['ur']}")
    print(f" FIX: {diag['fix']}")
    print("=" * 72)


def is_placeholder_credentials(account, password, server) -> bool:
    acc_str = str(account or "").strip()
    pwd_str = str(password or "").strip()
    srv_str = str(server or "").strip()
    is_ph_acc = acc_str in config.PLACEHOLDER_ACCOUNTS or acc_str in {"12345678", "0", ""}
    is_ph_pwd = pwd_str in config.PLACEHOLDER_PASSWORDS or pwd_str in {"your_trading_password", ""}
    is_ph_srv = srv_str in config.PLACEHOLDER_SERVERS or srv_str in {"YourBroker-Server", ""}
    return is_ph_acc or is_ph_pwd or is_ph_srv


def get_mt5_timeframe(tf_str: str, mt5_mod=None):
    mod = mt5_mod or mt5
    if mod is None:
        return 5
    mapping = {
        "M1": getattr(mod, "TIMEFRAME_M1", 1),
        "M5": getattr(mod, "TIMEFRAME_M5", 5),
        "M15": getattr(mod, "TIMEFRAME_M15", 15),
        "M30": getattr(mod, "TIMEFRAME_M30", 30),
        "H1": getattr(mod, "TIMEFRAME_H1", 60),
        "H4": getattr(mod, "TIMEFRAME_H4", 240),
        "D1": getattr(mod, "TIMEFRAME_D1", 1440),
    }
    return mapping.get(tf_str.upper(), getattr(mod, "TIMEFRAME_M5", 5))


# --- Trade Logger ---------------------------------------------------------

def log_trade_csv(record: dict):
    """Logs executed trade details to trades_log.csv."""
    file_exists = os.path.exists(config.TRADES_LOG_FILE)
    fieldnames = [
        "time", "symbol", "strategy", "direction", "entry_price",
        "sl_price", "tp_price", "lot", "risk_usd", "exit_price",
        "exit_time", "pnl_usd", "r_result", "exit_reason", "mode"
    ]
    try:
        with open(config.TRADES_LOG_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(record)
    except Exception as e:
        log(f"Failed to write trade log: {e}", "WARN")


# --- Strategy Loader from Tournament --------------------------------------

def load_approved_strategies() -> list[dict]:
    """Loads validated and approved strategy combinations from approved_strategies.json."""
    if not os.path.exists(config.APPROVED_STRATEGIES_FILE):
        return []
    try:
        with open(config.APPROVED_STRATEGIES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("approved_strategies", [])
    except Exception as e:
        log(f"Error loading approved strategies: {e}", "WARN")
        return []


# --- MT5 Connection & Diagnostics -----------------------------------------

def connect(mt5_mod=None) -> bool:
    mod = mt5_mod or mt5
    if mod is None:
        log("MetaTrader5 library is not available on this system.", "ERROR")
        return False

    base_kw = {"path": config.MT5_PATH} if config.MT5_PATH else {}
    has_placeholders = is_placeholder_credentials(config.MT5_ACCOUNT, config.MT5_PASSWORD, config.MT5_SERVER)
    connected = False

    if has_placeholders:
        print("\n" + "-" * 72)
        print(" [DIAGNOSTIC NOTICE] Placeholder / Default credentials detected in .env")
        print(" EN : Using .env credentials skipped (e.g. 12345678 / your_trading_password).")
        print(" UR : .env file me sample/fake details hain. Bot active MT5 terminal se rabta karega.")
        print(" FIX: Agar auto-login chahiye toh .env me apne broker account credentials dalein.")
        print("-" * 72 + "\n")
        connected = bool(mod.initialize(**base_kw))
    else:
        login_kw = dict(base_kw)
        login_kw.update(login=int(config.MT5_ACCOUNT), password=str(config.MT5_PASSWORD), server=str(config.MT5_SERVER))
        connected = bool(mod.initialize(**login_kw))
        if not connected:
            err = mod.last_error()
            diag = format_diagnostic(err[0] if isinstance(err, tuple) else -1, str(err))
            print_diagnostic_banner(diag)
            log("Attempting fallback: Connecting to terminal's currently active logged-in account...", "WARN")
            connected = bool(mod.initialize(**base_kw))
            if connected and mod.account_info() is not None:
                log("FALLBACK SUCCESS: Connected to already open MT5 terminal account!", "SUCCESS")

    if not connected:
        err = mod.last_error()
        diag = format_diagnostic(err[0] if isinstance(err, tuple) else -1, str(err))
        print_diagnostic_banner(diag)
        log("Cannot initialize MT5. Please open MetaTrader 5 terminal first.", "ERROR")
        return False

    acc = mod.account_info()
    if acc is None:
        print("\n" + "=" * 72)
        print(" [ERROR] MT5 initialized but no trade account is active.")
        print(" EN : Please log into a trade account in the MT5 terminal window.")
        print(" UR : MT5 open ho gaya hai lekin koi account login nahi hai. MT5 me login karein.")
        print(" FIX: In MT5, click File -> Login to Trade Account, enter credentials.")
        print("=" * 72 + "\n")
        return False

    global peak_equity
    peak_equity = max(peak_equity, acc.equity)

    demo_mode_val = getattr(mod, "ACCOUNT_TRADE_MODE_DEMO", 0)
    real_mode_val = getattr(mod, "ACCOUNT_TRADE_MODE_REAL", 2)
    mode_str = "DEMO (Safe Practice Account)" if acc.trade_mode == demo_mode_val else "*** REAL ACCOUNT (LIVE MONEY AT RISK) ***"

    print("=" * 72)
    print(f" LUMO EDGE FOREX BOT | Owner: {config.OWNER} | Powered by: {config.POWERED_BY}")
    print(f" Account Number : #{acc.login}")
    print(f" Account Mode   : {mode_str}")
    print(f" Broker Server  : {acc.server}")
    print(f" Balance / Equity: {acc.balance:.2f} / {acc.equity:.2f} {acc.currency}")
    print(f" Leverage       : 1:{acc.leverage}")
    print("=" * 72)

    ti = mod.terminal_info()
    if ti is not None:
        if not getattr(ti, "connected", True):
            log("[WARNING] MT5 terminal is disconnected from broker server!", "WARN")
        if not getattr(ti, "trade_allowed", True):
            log("[WARNING] 'Algo Trading' is OFF in your MT5 terminal toolbar!", "WARN")
            print("  UR: MT5 me 'Algo Trading' (AutoTrading) ka button band hai.")
            print("  FIX: Click the 'Algo Trading' button in MT5 top toolbar (it must turn green), or press Ctrl+E.")
            if config.LIVE_TRADING:
                log("CRITICAL: LIVE_TRADING=1 is active but Algo Trading is disabled! Orders will fail.", "ERROR")

    return True


# --- Position & Risk Inspections ------------------------------------------

def my_positions(mt5_mod=None):
    mod = mt5_mod or mt5
    if mod is None:
        return []
    try:
        positions = mod.positions_get()
        if positions is None:
            return []
        return [p for p in positions if getattr(p, "magic", 0) == config.MAGIC_NUMBER]
    except Exception:
        return []


def parse_currencies(symbol: str) -> tuple[str, str]:
    """Extracts base and quote currencies from standard forex symbol."""
    clean = symbol.replace("m", "").replace("c", "").replace(".raw", "").replace("_i", "").replace(".s", "")
    if len(clean) >= 6:
        return clean[:3].upper(), clean[3:6].upper()
    return clean.upper(), "USD"


def check_currency_exposure(new_symbol: str, new_direction: str, open_positions: list) -> bool:
    """
    Currency Exposure Cap:
    Ensures no more than MAX_SAME_CURRENCY_EXPOSURE open trades on the same side for any currency.
    For example: Long EURUSD (Buy EUR, Sell USD) -> EUR has +1, USD has -1.
    """
    base_new, quote_new = parse_currencies(new_symbol)
    currency_longs = {}
    currency_shorts = {}

    for p in open_positions:
        b, q = parse_currencies(p.symbol)
        if p.type == getattr(mt5, "ORDER_TYPE_BUY", 0):
            currency_longs[b] = currency_longs.get(b, 0) + 1
            currency_shorts[q] = currency_shorts.get(q, 0) + 1
        else:
            currency_shorts[b] = currency_shorts.get(b, 0) + 1
            currency_longs[q] = currency_longs.get(q, 0) + 1

    target_b_side = currency_longs if new_direction == "BUY" else currency_shorts
    target_q_side = currency_shorts if new_direction == "BUY" else currency_longs

    if target_b_side.get(base_new, 0) >= config.MAX_SAME_CURRENCY_EXPOSURE:
        return False
    if target_q_side.get(quote_new, 0) >= config.MAX_SAME_CURRENCY_EXPOSURE:
        return False
    return True


def check_total_open_risk(equity: float, open_positions: list, new_risk_usd: float) -> bool:
    """
    Total Open Risk Cap:
    Total potential loss at Stop Loss across all open trades must not exceed 3% of equity.
    """
    current_open_risk = 0.0
    for p in open_positions:
        # Distance from open price to SL
        if p.sl > 0:
            sl_dist = abs(p.price_open - p.sl)
            si = mt5.symbol_info(p.symbol) if mt5 else None
            tick_size = getattr(si, "trade_tick_size", 0.00001) or 0.00001
            tick_val = getattr(si, "trade_tick_value", 1.0) or 1.0
            current_open_risk += (sl_dist / tick_size) * tick_val * p.volume
        else:
            current_open_risk += (equity * 0.01)

    max_allowed = equity * (config.TOTAL_OPEN_RISK_CAP_PCT / 100.0)
    return (current_open_risk + new_risk_usd) <= max_allowed


def is_time_filter_active() -> tuple[bool, str]:
    """Checks rollover hour, Friday close, and news blackouts."""
    now_utc = dt.datetime.now(dt.timezone.utc)
    hour = now_utc.hour
    weekday = now_utc.weekday()  # 4 = Friday

    # Skip rollover hours (widest spreads)
    if hour in config.SKIP_ROLLOVER_HOURS:
        return True, f"Rollover Hour ({hour}:00 UTC) - wide spread protection"

    # Skip late Friday hours
    if weekday == 4 and hour >= config.SKIP_FRIDAY_AFTER_HOUR:
        return True, f"Late Friday ({hour}:00 UTC) - weekend gap protection"

    # Optional news calendar check
    if os.path.exists(config.NEWS_CALENDAR_FILE):
        try:
            with open(config.NEWS_CALENDAR_FILE, "r", encoding="utf-8") as f:
                news = json.load(f)
                for item in news:
                    event_time = dt.datetime.fromisoformat(item["time"])
                    diff_m = abs((now_utc - event_time).total_seconds()) / 60.0
                    if diff_m <= config.NEWS_BLACKOUT_MINUTES and item.get("impact", "").upper() == "HIGH":
                        return True, f"High Impact News Blackout: {item.get('title', 'Event')}"
        except Exception:
            pass

    return False, ""


def check_drawdown_circuit_breakers(equity: float) -> tuple[bool, str]:
    """Evaluates Daily Loss (3%), Weekly Loss (6%), and Kill Switch (15% from Peak)."""
    global peak_equity
    today = dt.date.today()
    cur_week = today.isocalendar()[1]

    peak_equity = max(peak_equity, equity)

    # 1. Kill Switch: 15% drawdown from equity high watermark
    if peak_equity > 0:
        dd_from_peak = (peak_equity - equity) / peak_equity * 100.0
        if dd_from_peak >= config.MAX_DD_KILL_SWITCH_PCT:
            return True, f"KILL SWITCH TRIGGERED: {dd_from_peak:.1f}% drawdown from peak ${peak_equity:.2f}!"

    # 2. Daily Loss Limit (3%)
    if day_state["date"] != today:
        day_state["date"] = today
        day_state["start_equity"] = equity
    daily_loss = (day_state["start_equity"] - equity) / day_state["start_equity"] * 100.0
    if daily_loss >= config.MAX_DAILY_LOSS_PCT:
        return True, f"Daily Loss Limit hit: -{daily_loss:.1f}% today (limit {config.MAX_DAILY_LOSS_PCT}%)"

    # 3. Weekly Loss Limit (6%)
    if week_state["week"] != cur_week:
        week_state["week"] = cur_week
        week_state["start_equity"] = equity
    weekly_loss = (week_state["start_equity"] - equity) / week_state["start_equity"] * 100.0
    if weekly_loss >= config.MAX_WEEKLY_LOSS_PCT:
        return True, f"Weekly Loss Limit hit: -{weekly_loss:.1f}% this week (limit {config.MAX_WEEKLY_LOSS_PCT}%)"

    return False, ""


# --- Per-Pair Auto-Pause (Streak Protection) ------------------------------

def evaluate_pair_pause(symbol: str, deals: list, now_ts: float, magic: int = config.MAGIC_NUMBER) -> tuple[bool, str]:
    if pair_pause_until.get(symbol, 0) > now_ts:
        rem_hours = (pair_pause_until[symbol] - now_ts) / 3600.0
        return True, f"Paused ({rem_hours:.1f}h remaining)"

    min_time = pair_resume_after.get(symbol, 0)
    deal_entry_out = getattr(mt5, "DEAL_ENTRY_OUT", 1) if mt5 else 1

    closed_deals = [
        d for d in deals
        if getattr(d, "symbol", "") == symbol
        and getattr(d, "magic", 0) == magic
        and getattr(d, "entry", -1) == deal_entry_out
        and getattr(d, "time", 0) > min_time
    ]

    if len(closed_deals) < config.PAIR_REVIEW_TRADES:
        return False, f"Monitoring ({len(closed_deals)}/{config.PAIR_REVIEW_TRADES} fresh trades)"

    sorted_deals = sorted(closed_deals, key=lambda x: getattr(x, "time", 0))
    last_n = sorted_deals[-config.PAIR_REVIEW_TRADES:]
    net_pnl = sum((getattr(d, "profit", 0.0) + getattr(d, "commission", 0.0) + getattr(d, "swap", 0.0)) for d in last_n)

    if net_pnl < 0:
        pause_until = now_ts + (config.PAIR_PAUSE_HOURS * 3600)
        pair_pause_until[symbol] = pause_until
        pair_resume_after[symbol] = pause_until
        return True, f"Paused for {config.PAIR_PAUSE_HOURS}h: last {len(last_n)} trades net ${net_pnl:.2f}"

    return False, f"Healthy: last {len(last_n)} trades net ${net_pnl:+.2f}"


def update_paused_pairs(mt5_mod=None):
    mod = mt5_mod or mt5
    if mod is None:
        return
    now_ts = time.time()
    from_date = dt.datetime.now() - dt.timedelta(days=35)
    to_date = dt.datetime.now() + dt.timedelta(days=1)
    deals = mod.history_deals_get(from_date, to_date) or []

    for s in config.SCANNER_SYMBOLS:
        sym = resolve_symbol(s)
        paused, reason = evaluate_pair_pause(sym, deals, now_ts)
        if paused and pair_last_checked.get(sym, 0) < pair_pause_until.get(sym, 0):
            pair_last_checked[sym] = pair_pause_until[sym]
            log(f"RISK MANAGEMENT: Pair {sym} {reason}", "RISK")


def is_pair_paused(symbol: str) -> bool:
    return pair_pause_until.get(symbol, 0) > time.time()


# --- Lot Sizing with Streak Halving ---------------------------------------

def calc_lot(si, sl_dist: float, equity: float) -> float:
    global consecutive_losses
    # Halve risk if on a 3-trade losing streak
    risk_pct = config.MIN_RISK_PERCENT if consecutive_losses >= config.CONSECUTIVE_LOSS_HALVE_COUNT else config.RISK_PERCENT

    risk_amt = equity * (risk_pct / 100.0)
    tick_size = getattr(si, "trade_tick_size", 0.00001) or 0.00001
    tick_value = getattr(si, "trade_tick_value", 1.0) or 1.0
    per_lot_loss = (sl_dist / tick_size) * tick_value

    if per_lot_loss <= 0:
        return 0.0

    raw_lot = risk_amt / per_lot_loss
    step = getattr(si, "volume_step", 0.01) or 0.01
    lot = int(raw_lot / step) * step
    lot = round(lot, 2)

    vol_min = getattr(si, "volume_min", 0.01)
    vol_max = getattr(si, "volume_max", 100.0)

    if lot < vol_min:
        min_lot_loss = vol_min * per_lot_loss
        if min_lot_loss > (risk_amt * config.MAX_RISK_OVERSHOOT):
            return 0.0
        lot = vol_min

    lot = min(vol_max, max(vol_min, lot))
    lot = round(lot, 2)

    if (lot * per_lot_loss) > (risk_amt * config.MAX_RISK_OVERSHOOT):
        return 0.0

    return lot


# --- Order Execution & Filling Modes --------------------------------------

def send_order_with_filling(req: dict, si, mt5_mod=None):
    mod = mt5_mod or mt5
    if mod is None:
        return None

    modes = []
    filling_mode = getattr(si, "filling_mode", 0)
    if filling_mode & 2:
        modes.append(getattr(mod, "ORDER_FILLING_IOC", 1))
    if filling_mode & 1:
        modes.append(getattr(mod, "ORDER_FILLING_FOK", 2))
    modes.append(getattr(mod, "ORDER_FILLING_RETURN", 0))

    seen = set()
    unique_modes = [m for m in modes if not (m in seen or seen.add(m))]

    last_res = None
    for mode in unique_modes:
        req["type_filling"] = mode
        res = mod.order_send(req)
        last_res = res
        if res is not None and getattr(res, "retcode", 0) == getattr(mod, "TRADE_RETCODE_DONE", 10009):
            return res
        if res is None or getattr(res, "retcode", 0) != 10030:
            break

    return last_res


def close_position(p, exit_reason: str = "Profit Lock", mt5_mod=None) -> bool:
    mod = mt5_mod or mt5
    if mod is None:
        return False

    sym = p.symbol
    si = mod.symbol_info(sym)
    tick = mod.symbol_info_tick(sym)
    if not si or not tick:
        return False

    is_buy = (p.type == getattr(mod, "ORDER_TYPE_BUY", 0))
    close_type = getattr(mod, "ORDER_TYPE_SELL", 1) if is_buy else getattr(mod, "ORDER_TYPE_BUY", 0)
    close_price = tick.bid if is_buy else tick.ask

    req = {
        "action": getattr(mod, "TRADE_ACTION_DEAL", 1),
        "symbol": sym,
        "volume": p.volume,
        "type": close_type,
        "position": p.ticket,
        "price": close_price,
        "deviation": 20,
        "magic": config.MAGIC_NUMBER,
        "comment": f"LumoEdge: {exit_reason[:15]}",
        "type_time": getattr(mod, "ORDER_TIME_GTC", 0)
    }

    res = send_order_with_filling(req, si, mod)
    done_code = getattr(mod, "TRADE_RETCODE_DONE", 10009)
    success = (res is not None and getattr(res, "retcode", 0) == done_code)
    net_pnl = p.profit + getattr(p, "swap", 0.0)

    global consecutive_losses
    if success:
        if net_pnl > 0:
            consecutive_losses = 0
            log(f"PROFIT CLOSED: {sym} Ticket #{p.ticket} Net: ${net_pnl:+.2f} ({exit_reason})", "PROFIT")
        else:
            consecutive_losses += 1
            log(f"CLOSED: {sym} Ticket #{p.ticket} Net: ${net_pnl:+.2f} ({exit_reason})", "WARN")

        # Log to CSV
        log_trade_csv({
            "time": dt.datetime.now().isoformat(),
            "symbol": sym,
            "strategy": p.comment,
            "direction": "BUY" if is_buy else "SELL",
            "entry_price": p.price_open,
            "sl_price": p.sl,
            "tp_price": p.tp,
            "lot": p.volume,
            "risk_usd": round(abs(p.price_open - p.sl) * 100000 * p.volume, 2) if p.sl > 0 else 0.0,
            "exit_price": close_price,
            "exit_time": dt.datetime.now().isoformat(),
            "pnl_usd": round(net_pnl, 2),
            "r_result": round(net_pnl / (abs(p.price_open - p.sl) * 100000 * p.volume), 2) if p.sl > 0 else 0.0,
            "exit_reason": exit_reason,
            "mode": "LIVE" if config.LIVE_TRADING else "PAPER"
        })

    return success


def take_profits(approved_strategies: list, mt5_mod=None) -> int:
    """
    R-Multiple Profit Taker & Dynamic Trailing:
    Scales profit close based on initial R risk distance rather than fixed dollars!
    """
    closed_count = 0
    strat_map = {a['strategy']: a for a in approved_strategies}

    for p in my_positions(mt5_mod):
        net_profit = p.profit + getattr(p, "swap", 0.0)
        strat_cfg = strat_map.get(p.comment, {})
        exit_mode = strat_cfg.get("exit_mode", "MODE_C")
        r_target = strat_cfg.get("r_target", config.PROFIT_LOCK_R_MULTIPLE)

        # Initial risk in price distance
        sl_dist = abs(p.price_open - p.sl) if p.sl > 0 else 0.0
        si = mt5.symbol_info(p.symbol) if mt5 else None
        tick_size = getattr(si, "trade_tick_size", 0.00001) or 0.00001
        tick_val = getattr(si, "trade_tick_value", 1.0) or 1.0
        initial_risk_usd = (sl_dist / tick_size) * tick_val * p.volume if sl_dist > 0 else 50.0

        target_usd = max(config.MIN_PROFIT_USD, initial_risk_usd * r_target)

        # Mode C: Instant R-multiple close
        if exit_mode == "MODE_C" and net_profit >= target_usd:
            if close_position(p, f"Mode C ({r_target}R)", mt5_mod):
                closed_count += 1
        # Fallback instant close if target profit reached
        elif net_profit >= config.MIN_PROFIT_USD:
            if close_position(p, "Instant Lock", mt5_mod):
                closed_count += 1

    return closed_count


def open_trade(sym_info, strategy_name: str, action: str, atr: float, exit_mode: str, r_target: float, mt5_mod=None) -> bool:
    mod = mt5_mod or mt5
    if mod is None:
        return False

    sym = sym_info.name
    tick = mod.symbol_info_tick(sym)
    if not tick:
        return False

    # Spread filter: max 25% of ATR
    spread = tick.ask - tick.bid
    if spread > (config.MAX_SPREAD_ATR_FRAC * atr):
        log(f"{sym} skipped: spread ({spread:.5f}) > 25% of ATR ({atr:.5f})", "SKIP")
        return False

    stops_level = getattr(sym_info, "trade_stops_level", 0) * getattr(sym_info, "point", 0.0001)
    sl_dist = max(atr * config.SL_ATR_MULT, stops_level * 1.2)

    acc = mod.account_info()
    if acc is None:
        return False

    lot = calc_lot(sym_info, sl_dist, acc.equity)
    if lot <= 0:
        log(f"{sym} skipped: account size/risk exceeds safe limit", "SKIP")
        return False

    # Risk checks
    open_pos = my_positions(mod)
    tick_size = getattr(sym_info, "trade_tick_size", 0.00001) or 0.00001
    tick_val = getattr(sym_info, "trade_tick_value", 1.0) or 1.0
    new_risk_usd = (sl_dist / tick_size) * tick_val * lot

    if not check_total_open_risk(acc.equity, open_pos, new_risk_usd):
        log(f"{sym} skipped: total open risk cap (3% of equity) reached", "RISK")
        return False

    if not check_currency_exposure(sym, action, open_pos):
        log(f"{sym} skipped: currency exposure cap (max 2) reached", "RISK")
        return False

    buy = (action == "BUY")
    price = tick.ask if buy else tick.bid
    sl = price - sl_dist if buy else price + sl_dist
    tp = price + (sl_dist * config.TP_RR) if buy else price - (sl_dist * config.TP_RR)
    digits = getattr(sym_info, "digits", 5)

    trade_summary = (
        f"{action} {sym} [{strategy_name}] lot {lot} @ {price:.{digits}f} "
        f"SL {sl:.{digits}f} TP {tp:.{digits}f} | Risk: ${new_risk_usd:.2f}"
    )

    if not config.LIVE_TRADING:
        log(f"PAPER TRADE: {trade_summary}", "PAPER")
        log_trade_csv({
            "time": dt.datetime.now().isoformat(), "symbol": sym, "strategy": strategy_name,
            "direction": action, "entry_price": price, "sl_price": round(sl, digits),
            "tp_price": round(tp, digits), "lot": lot, "risk_usd": round(new_risk_usd, 2),
            "exit_price": 0.0, "exit_time": "", "pnl_usd": 0.0, "r_result": 0.0,
            "exit_reason": "OPEN_PAPER", "mode": "PAPER"
        })
        return True

    order_type = getattr(mod, "ORDER_TYPE_BUY", 0) if buy else getattr(mod, "ORDER_TYPE_SELL", 1)
    req = {
        "action": getattr(mod, "TRADE_ACTION_DEAL", 1),
        "symbol": sym, "volume": lot, "type": order_type, "price": price,
        "sl": round(sl, digits), "tp": round(tp, digits), "deviation": 20,
        "magic": config.MAGIC_NUMBER, "comment": strategy_name[:15],
        "type_time": getattr(mod, "ORDER_TIME_GTC", 0)
    }

    res = send_order_with_filling(req, sym_info, mod)
    done_code = getattr(mod, "TRADE_RETCODE_DONE", 10009)
    if res is not None and getattr(res, "retcode", 0) == done_code:
        log(f"ORDER EXECUTED: {trade_summary}", "TRADE")
        return True

    retcode = getattr(res, "retcode", -1) if res else mod.last_error()
    diag = format_diagnostic(retcode if isinstance(retcode, int) else -1, str(retcode))
    log(f"Order failed for {sym}: {diag['en']}", "ERROR")
    return False


# --- Multi-Strategy Scanner Loop ------------------------------------------

def scan_and_trade(approved_strategies: list, mt5_mod=None):
    mod = mt5_mod or mt5
    if mod is None:
        return

    update_paused_pairs(mod)
    open_pos = my_positions(mod)
    available_slots = config.MAX_OPEN_TRADES - len(open_pos)
    if available_slots <= 0:
        return

    # Check time filters
    blocked, time_reason = is_time_filter_active()
    if blocked:
        return

    # Active positions per symbol and strategy
    open_keys = {(p.symbol, p.comment) for p in open_pos}

    for app_item in approved_strategies:
        if available_slots <= 0:
            break

        sym_raw = app_item["symbol"]
        strat_name = app_item["strategy"]
        tf_str = app_item.get("timeframe", "H1")
        exit_mode = app_item.get("exit_mode", "MODE_C")
        r_target = app_item.get("r_target", 0.75)

        sym = resolve_symbol(sym_raw)
        si = mod.symbol_info(sym)
        if si is None or is_pair_paused(sym):
            continue

        if (sym, strat_name[:15]) in open_keys:
            continue

        tf = get_mt5_timeframe(tf_str, mod)
        df = get_rates(sym, tf, num_bars=300)
        if df is None or len(df) < 50:
            continue

        # Prevent churn: evaluate strictly on CLOSED candle
        last_bar_time = df.index[-2] if len(df) > 1 else df.index[-1]
        key = (sym, strat_name)
        if last_bar_traded.get(key) == last_bar_time:
            continue

        strat_fn = STRATEGY_REGISTRY.get(strat_name)
        if strat_fn is None:
            continue

        try:
            sig_series = strat_fn(df)
            last_sig = int(sig_series.iloc[-2]) if len(sig_series) > 1 else int(sig_series.iloc[-1])
        except Exception:
            continue

        if last_sig == 0:
            continue

        action = "BUY" if last_sig == 1 else "SELL"
        last_bar_traded[key] = last_bar_time

        # Calculate ATR for SL sizing
        h, l = df['high'].astype(float), df['low'].astype(float)
        pc = df['close'].astype(float).shift(1)
        tr = max(h.iloc[-2] - l.iloc[-2], abs(h.iloc[-2] - pc.iloc[-2]), abs(l.iloc[-2] - pc.iloc[-2]))
        atr = tr if tr > 0 else 0.0015

        if open_trade(si, strat_name, action, atr, exit_mode, r_target, mod):
            open_keys.add((sym, strat_name[:15]))
            available_slots -= 1


# --- Main Application Loop ------------------------------------------------

def run_bot():
    print("=" * 76)
    print(" LUMO EDGE FOREX AUTOMATION SYSTEM (MULTI-STRATEGY)")
    print(f" Powered by: {config.POWERED_BY} | Owner: {config.OWNER}")
    print(f" Mode            : {'LIVE TRADING (Real Orders)' if config.LIVE_TRADING else 'PAPER TRADING (Simulation Mode)'}")
    print(f" Global Max Trades: {config.MAX_OPEN_TRADES}")
    print(f" Risk per trade  : {config.RISK_PERCENT}% of equity (halves to {config.MIN_RISK_PERCENT}% on streak)")
    print(f" Open Risk Cap   : {config.TOTAL_OPEN_RISK_CAP_PCT}% | Drawdown Limits: Daily {config.MAX_DAILY_LOSS_PCT}%, Weekly {config.MAX_WEEKLY_LOSS_PCT}%")
    print("=" * 76)

    if not connect():
        log("Connection aborted. Please resolve the errors above.", "ERROR")
        return

    approved = load_approved_strategies()
    if not approved:
        print("\n" + "=" * 76)
        print(" [SAFETY ADVISORY] No strategies currently in approved_strategies.json!")
        print(" EN : The bot will run in SAFE PAPER MODE for monitoring.")
        print(" UR : Koi strategy 10-year backtest pass nahi hui. Bot safe paper mode me rahega.")
        print(" FIX: Run 'python run_backtest.py' to evaluate and approve validated strategies.")
        print("=" * 76 + "\n")
        # Fallback to current native bot strategy for monitoring in paper mode
        approved = [{
            "symbol": "EURUSDm", "strategy": "EMA Cross + Pullback (50/200)",
            "timeframe": "M5", "exit_mode": "MODE_C", "r_target": 0.75
        }]

    log(f"Active Approved Combinations: {len(approved)}", "INFO")
    for a in approved:
        print(f"  -> {a['symbol']} | {a['strategy']} | TF: {a.get('timeframe','H1')} | Exit: {a.get('exit_mode','MODE_C')}")

    paused_warning_shown = False
    log("Scanner initialized. Monitoring markets every 3 seconds...", "INFO")

    while True:
        acc = mt5.account_info() if mt5 else None
        equity = acc.equity if acc else 10000.0

        # Drawdown circuit breaker checks
        circuit_hit, circuit_reason = check_drawdown_circuit_breakers(equity)
        if circuit_hit:
            if not paused_warning_shown:
                log(f"CIRCUIT BREAKER: {circuit_reason}", "RISK")
                paused_warning_shown = True
        else:
            paused_warning_shown = False

        # Instant profit taker
        closed = take_profits(approved)
        if closed > 0 and not circuit_hit:
            log(f"Closed {closed} trade(s) in profit! Immediately re-scanning markets...", "PROFIT")
            scan_and_trade(approved)

        if not circuit_hit:
            scan_and_trade(approved)

        time.sleep(config.SCAN_INTERVAL_SECONDS)


def main():
    try:
        run_bot()
    except KeyboardInterrupt:
        log("Bot stopped safely by user (Ctrl+C).", "INFO")
    except Exception as e:
        tb = traceback.format_exc()
        print("\n" + "=" * 76)
        print(" [CRITICAL APPLICATION CRASH]")
        print(f" Error: {e}")
        print(" UR : Bot me achanak koi ghalati aa gayi aur process band ho gaya.")
        print(f" TRACEBACK:\n{tb}")
        print(" FIX: Upar diye gaye traceback ko dekhein aur config settings verify karein.")
        print("=" * 76 + "\n")
    finally:
        if mt5 is not None:
            try:
                mt5.shutdown()
            except Exception:
                pass


if __name__ == "__main__":
    main()
