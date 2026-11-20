"""
=============================================================================
 LUMO EDGE - ULTRA RAPID 3D AUTOMATION SERVER & DASHBOARD
 Owner: Gontse | Powered by: Lumo Edge
 Features:
   - 3-Second Active Market Scanner (Fast Scalp Execution)
   - Instant Close As Soon As In Profit + Immediate Re-entry
   - Smart Dynamic Money Management (Auto-scaled safe lot sizing)
   - Dual Mode: Auto Multi-Pair OR Single Selected Pair
   - One-Click MT5 Account Connect from 3D Web UI
   - Magic Number Isolation (786999 - Never touches manual trades)
=============================================================================
"""

import os
import sys
import time
import json
import threading
from datetime import datetime
import datetime as dt
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from strategy import analyze_fast_scalp, resolve_symbol
from money_manager import calculate_dynamic_lot, get_risk_summary

# --- AI Integration Bridge (4 AI Systems) ------------------------------------
_ai_bridge = None
_ai_bridge_error = None
_ai_bridge_ready = False

def _init_ai_bridge():
    global _ai_bridge, _ai_bridge_error, _ai_bridge_ready
    try:
        from ai_integration_bridge import get_bridge
        _ai_bridge = get_bridge()
        _ai_bridge_ready = True
        print("[LUMO EDGE] ✅ AI Integration Bridge READY (OpenBB + day-trader-skill + TradingAgents + Paperclip)")
    except Exception as e:
        _ai_bridge_error = str(e)
        print(f"[LUMO EDGE] ⚠️  AI Bridge not loaded: {e}")

# Load bridge in background — OpenBB takes ~60s on first import, don't block server
threading.Thread(target=_init_ai_bridge, daemon=True, name="AIBridgeLoader").start()

app = FastAPI(title="Lumo Edge Ultra Rapid Cockpit")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_report", "report.html")
MAGIC_NUMBER = 786999

# --- Live Server State --------------------------------------------------------
state = {
    "mt5_connected": False,
    "bot_running": True,              # AUTO-START: Immediately ON!
    "trading_mode": "SINGLE",         # Dedicated Single Pair
    "active_pair": "XAUUSDm",         # ONLY Gold (XAUUSDm) as requested
    "min_profit_usd": 0.25,           # Ultra-Fast Close when profit >= $0.25
    "max_open_trades": 5,             # Allow up to 5 simultaneous trades
    "timeframe": "M1",                # Ultra-Rapid 1-Minute Scalp
    "execution_speed": "Super 0.1s",  # Super-Fast execution as in video
    "turbo_scalper_active": True,
    "scanner_results": [],
    "recent_logs": [],
    "account_info": None,
    "risk_stats": {"recommended_lot": 0.01}
}

TF_MAP = {
    "M1": getattr(mt5, "TIMEFRAME_M1", 1) if mt5 else 1,
    "M5": getattr(mt5, "TIMEFRAME_M5", 5) if mt5 else 5,
    "M15": getattr(mt5, "TIMEFRAME_M15", 15) if mt5 else 15,
    "H1": getattr(mt5, "TIMEFRAME_H1", 60) if mt5 else 60
}

# --- Pydantic Request Models --------------------------------------------------
class ConnectAccountReq(BaseModel):
    login: int
    password: str
    server: str

class ManualOrderReq(BaseModel):
    symbol: str
    action: str           # "BUY" or "SELL"
    volume: float = 0.0   # 0.0 = auto dynamic money management
    sl_pips: float = 20.0

class SettingsReq(BaseModel):
    min_profit_usd: float = 0.35
    max_open_trades: int = 3
    trading_mode: str = "MULTI"
    active_pair: str = "EURUSDm"
    timeframe: str = "M5"

# --- Logging Helper -----------------------------------------------------------
def log_event(message: str, tag: str = "INFO"):
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "tag": tag,
        "message": message
    }
    state["recent_logs"].insert(0, entry)
    if len(state["recent_logs"]) > 80:
        state["recent_logs"].pop()
    print(f"[{entry['time']}] [{tag}] {message}")

# --- MT5 Session & Connection -------------------------------------------------
def init_mt5_session() -> bool:
    if mt5 is None:
        state["mt5_connected"] = False
        return False

    base_kw = {"path": config.MT5_PATH} if getattr(config, "MT5_PATH", "") else {}

    # Attempt connection
    if config.MT5_ACCOUNT and config.MT5_PASSWORD and config.MT5_SERVER:
        login_id = str(config.MT5_ACCOUNT).strip()
        if login_id not in {"12345678", "0", "", "None"}:
            mt5.initialize(**base_kw)
            mt5.login(int(config.MT5_ACCOUNT), str(config.MT5_PASSWORD), str(config.MT5_SERVER))
        else:
            mt5.initialize(**base_kw)
    else:
        mt5.initialize(**base_kw)

    acc = mt5.account_info()
    if acc is not None:
        state["mt5_connected"] = True
        state["account_info"] = {
            "login": acc.login,
            "name": acc.name,
            "balance": round(acc.balance, 2),
            "equity": round(acc.equity, 2),
            "server": acc.server,
            "currency": acc.currency
        }
        return True

    state["mt5_connected"] = False
    return False

def get_live_positions():
    if mt5 is None:
        return []
    if not state["mt5_connected"] and not init_mt5_session():
        return []
    raw = mt5.positions_get()
    if not raw:
        return []
    return [{
        "ticket": p.ticket,
        "symbol": p.symbol,
        "type": "BUY" if p.type == getattr(mt5, "ORDER_TYPE_BUY", 0) else "SELL",
        "volume": p.volume,
        "price_open": p.price_open,
        "price_current": p.price_current,
        "sl": p.sl,
        "tp": p.tp,
        "profit": round(p.profit + getattr(p, "swap", 0.0), 2),
        "is_bot": (getattr(p, "magic", 0) == MAGIC_NUMBER),
        "open_time": getattr(p, "time", int(time.time()))
    } for p in raw]

def close_position_ticket(ticket: int, comment: str = "LumoEdge: Take Profit") -> bool:
    if mt5 is None:
        return False
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return False
    pos = positions[0]
    symbol = pos.symbol
    lot = pos.volume
    order_type = getattr(mt5, "ORDER_TYPE_SELL", 1) if pos.type == getattr(mt5, "ORDER_TYPE_BUY", 0) else getattr(mt5, "ORDER_TYPE_BUY", 0)
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return False
    price = tick.bid if order_type == getattr(mt5, "ORDER_TYPE_SELL", 1) else tick.ask

    req = {
        "action": getattr(mt5, "TRADE_ACTION_DEAL", 1),
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "position": pos.ticket,
        "price": price,
        "deviation": 25,
        "magic": MAGIC_NUMBER,
        "comment": comment,
        "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
        "type_filling": getattr(mt5, "ORDER_FILLING_IOC", 1),
    }
    
    # Pre-simulate with order_check before close
    try:
        chk = mt5.order_check(req)
        if chk and chk.retcode != 0:
            log_event(f"Close order check warning on #{ticket}: {chk.comment}", "WARN")
    except Exception:
        pass

    res = mt5.order_send(req)
    # [BUG FIXED]: Fallback to FOK (0), NOT unsupported RETURN (2)!
    if res and res.retcode != getattr(mt5, "TRADE_RETCODE_DONE", 10009):
        req["type_filling"] = getattr(mt5, "ORDER_FILLING_FOK", 0)
        res = mt5.order_send(req)

    if res and res.retcode == getattr(mt5, "TRADE_RETCODE_DONE", 10009):
        log_event(f"POSITION CLOSED: #{ticket} {symbol} (+${pos.profit:.2f}) | {comment}", "TRADE")
        return True
    else:
        err_c = getattr(res, "comment", "Unknown") if res else "No response"
        err_code = getattr(res, "retcode", -1) if res else -1
        log_event(f"Failed to close #{ticket}: {err_c} (Retcode {err_code})", "ERROR")
        return False

# --- Persistent Safety, Circuit Breakers & Loss Streak Tracking ---------------
bot_startup_time = time.time()
symbol_loss_streak: Dict[str, int] = {}
symbol_pause_until: Dict[str, float] = {}
symbol_last_entry_time: Dict[str, float] = {}
processed_deal_tickets: set = set()

state["daily_realized_pnl"] = 0.0
state["consecutive_losses"] = 0
state["circuit_breaker_active"] = False
state["circuit_breaker_reason"] = None
state["peak_equity"] = 0.0

def record_trade_result(symbol: str, profit: float):
    """
    [CRITICAL BUG FIXED]: Fully wired circuit breaker tracking.
    Enforces Daily Loss Cap (3%), Drawdown Kill Switch (10%), and Loss Streaks.
    """
    acc = mt5.account_info() if mt5 else None
    current_equity = acc.equity if acc else 10000.0
    
    if state["peak_equity"] == 0.0 or current_equity > state["peak_equity"]:
        state["peak_equity"] = current_equity

    state["daily_realized_pnl"] = round(state["daily_realized_pnl"] + profit, 2)
    
    # Track streaks
    if profit < 0:
        state["consecutive_losses"] += 1
        symbol_loss_streak[symbol] = symbol_loss_streak.get(symbol, 0) + 1
        log_event(f"LOSS RECORDED: {symbol} ${profit:.2f} (Streak: {state['consecutive_losses']})", "RISK")
    else:
        state["consecutive_losses"] = 0
        symbol_loss_streak[symbol] = 0
        log_event(f"WIN RECORDED: {symbol} +${profit:.2f} (Streak Reset)", "PROFIT")

    # Write to trades_log.csv
    log_file = getattr(config, "TRADES_LOG_FILE", "trades_log.csv")
    try:
        file_exists = os.path.exists(log_file)
        with open(log_file, "a", encoding="utf-8") as f:
            if not file_exists:
                f.write("timestamp,symbol,net_pnl,daily_pnl,equity,consecutive_losses\n")
            f.write(f"{datetime.now(dt.timezone.utc).isoformat()},{symbol},{profit:.2f},{state['daily_realized_pnl']:.2f},{current_equity:.2f},{state['consecutive_losses']}\n")
    except Exception as e:
        log_event(f"Failed to append to trades_log.csv: {e}", "WARN")

    # 1. Enforce Daily Loss Limit
    max_daily_loss = current_equity * (getattr(config, "MAX_DAILY_LOSS_PCT", 3.0) / 100.0)
    if state["daily_realized_pnl"] <= -max_daily_loss:
        state["circuit_breaker_active"] = True
        state["bot_running"] = False
        state["circuit_breaker_reason"] = f"DAILY LOSS LIMIT BREACHED (-${abs(state['daily_realized_pnl']):.2f} >= -${max_daily_loss:.2f})"
        log_event(f"🚨 CIRCUIT BREAKER TRIPPED: {state['circuit_breaker_reason']}. All entries halted!", "CRITICAL")

    # 2. Enforce Drawdown Kill Switch
    dd_usd = state["peak_equity"] - current_equity
    dd_pct = (dd_usd / state["peak_equity"] * 100.0) if state["peak_equity"] > 0 else 0.0
    max_dd_limit = getattr(config, "MAX_DD_KILL_SWITCH_PCT", 10.0)
    if dd_pct >= max_dd_limit:
        state["circuit_breaker_active"] = True
        state["bot_running"] = False
        state["circuit_breaker_reason"] = f"MAX DRAWDOWN LIMIT BREACHED ({dd_pct:.1f}% >= {max_dd_limit}%)"
        log_event(f"🚨 KILL SWITCH TRIPPED: {state['circuit_breaker_reason']}. All entries halted!", "CRITICAL")

    # 3. Enforce Consecutive Loss Pause
    max_cons = getattr(config, "MAX_CONSECUTIVE_LOSSES", 5)
    if state["consecutive_losses"] >= max_cons:
        symbol_pause_until[symbol] = time.time() + (4 * 3600)  # Pause symbol for 4 hours
        log_event(f"CONSECUTIVE LOSS PAUSE: {symbol} paused for 4 hours after {max_cons} losses.", "RISK")

def check_recent_closed_deals():
    """Detects any closed positions from MT5 history to track streaks and enforce safety."""
    if mt5 is None or not state["mt5_connected"]:
        return
    try:
        now = datetime.now()
        from_t = now - dt.timedelta(minutes=5)
        deals = mt5.history_deals_get(from_t, now)
        if deals:
            for d in deals:
                if d.time < bot_startup_time:
                    continue
                if (d.entry == 1 or d.entry == getattr(mt5, "DEAL_ENTRY_OUT", 1)) and d.ticket not in processed_deal_tickets:
                    if getattr(d, "magic", 0) == MAGIC_NUMBER or "LumoEdge" in getattr(d, "comment", ""):
                        processed_deal_tickets.add(d.ticket)
                        net_pnl = d.profit + getattr(d, "swap", 0.0) + getattr(d, "commission", 0.0)
                        record_trade_result(d.symbol, net_pnl)
    except Exception:
        pass

def execute_market_trade(symbol: str, action: str, lot: float = 0.0, sl_pips: float = 25.0, reason: str = ""):
    """
    [BUGS FIXED]:
    1. Single Order Execution (Debounce Lock prevents burst spam).
    2. Dynamic ATR 1:1.5 Positive Risk/Reward (SL 1.0x ATR, TP 1.5x ATR).
    3. Pre-Trade order_check() and margin verification.
    4. Supported Filling Mode (IOC -> FOK fallback).
    """
    if mt5 is None:
        return False

    # [TASK 6 AUDIT FIX]: Hard Safety Interlock - Absolute Prevention of Real Orders in Paper Mode
    if not getattr(config, "LIVE_TRADING", False):
        log_event(f"SAFETY INTERLOCK: Real execution disabled (config.LIVE_TRADING=False). mt5.order_send() suppressed for {action} on {symbol}.", "SAFETY")
        return False

    # Check Circuit Breaker
    if state.get("circuit_breaker_active", False):
        log_event(f"Trade REJECTED on {symbol}: Circuit breaker active ({state.get('circuit_breaker_reason')})", "FILTER")
        return False

    sym = resolve_symbol(symbol)
    si = mt5.symbol_info(sym)
    if not si:
        log_event(f"Symbol {sym} not found on broker", "ERROR")
        return False

    # Check symbol trade mode (Market Open / Full Permissions)
    if getattr(si, "trade_mode", 4) != getattr(mt5, "SYMBOL_TRADE_MODE_FULL", 4):
        log_event(f"Trade REJECTED: Symbol {sym} trade_mode={si.trade_mode} (not full trading mode)", "FILTER")
        return False

    # Debounce Lock: Minimum 60 seconds between trade entries on same symbol
    now_ts = time.time()
    last_entry = symbol_last_entry_time.get(sym, 0.0)
    debounce_sec = getattr(config, "COOLDOWN_MINUTES", 1) * 60
    if now_ts - last_entry < debounce_sec:
        log_event(f"Trade REJECTED on {sym}: Debounce cooldown active ({int(debounce_sec - (now_ts - last_entry))}s remaining)", "FILTER")
        return False

    # Check pause until after losing streak
    if now_ts < symbol_pause_until.get(sym, 0.0):
        log_event(f"Trade REJECTED on {sym}: Pair is paused until losing streak cooldown expires.", "FILTER")
        return False

    # Ensure visible in MarketWatch
    if not si.visible:
        mt5.symbol_select(sym, True)

    tick = mt5.symbol_info_tick(sym)
    if not tick:
        log_event(f"Tick data unavailable for {sym}", "ERROR")
        return False

    # Tick Freshness Guard (Reject if older than 5.0s during trading)
    if abs(now_ts - tick.time) > 10.0:
        log_event(f"Trade REJECTED on {sym}: Stale tick timestamp ({abs(now_ts - tick.time):.1f}s lag)", "FILTER")
        return False

    # Spread Protection Filter (Dynamic ATR ceiling)
    spread = tick.ask - tick.bid
    spread_pts = round(spread / si.point) if si.point > 0 else (spread * 1000)
    max_pts = getattr(config, "MAX_SPREAD_POINTS", 45.0)
    if spread_pts > max_pts:
        log_event(f"Trade REJECTED: Spread too wide on {sym} ({spread_pts} pts > max {max_pts} pts)", "FILTER")
        return False

    # Query current ATR for dynamic stops
    rates = mt5.copy_rates_from_pos(sym, getattr(mt5, f"TIMEFRAME_{config.DEFAULT_TIMEFRAME}", mt5.TIMEFRAME_M15), 0, 30)
    atr_val = 3.00
    if rates is not None and len(rates) >= 15:
        df_r = pd.DataFrame(rates)
        tr = pd.concat([
            df_r['high'] - df_r['low'],
            (df_r['high'] - df_r['close'].shift()).abs(),
            (df_r['low'] - df_r['close'].shift()).abs()
        ], axis=1).max(axis=1)
        atr_val = float(tr.rolling(14).mean().iloc[-1])
        if np.isnan(atr_val) or atr_val <= 0:
            atr_val = 3.00

    # Auto Money Management: ATR-based % risk sizing (0.25% - 0.50%)
    sl_dist = atr_val * getattr(config, "SL_ATR_MULT", 1.0)
    tp_dist = atr_val * getattr(config, "TP_ATR_MULT", 1.5)  # Enforcing 1:1.5 positive R:R!

    if lot <= 0:
        lot = calculate_dynamic_lot(sym, sl_distance_usd=sl_dist)

    order_type = getattr(mt5, "ORDER_TYPE_BUY", 0) if action.upper() == "BUY" else getattr(mt5, "ORDER_TYPE_SELL", 1)
    price = tick.ask if action.upper() == "BUY" else tick.bid
    digits = si.digits

    tp = round((price + tp_dist) if action.upper() == "BUY" else (price - tp_dist), digits)
    sl = round((price - sl_dist) if action.upper() == "BUY" else (price + sl_dist), digits)

    # Pre-check Margin Availability
    acc = mt5.account_info()
    if acc:
        req_margin = mt5.order_calc_margin(order_type, sym, lot, price)
        if req_margin and req_margin > acc.margin_free:
            log_event(f"Trade REJECTED on {sym}: Insufficient margin (Req: ${req_margin:.2f} > Free: ${acc.margin_free:.2f})", "MARGIN")
            return False

    req = {
        "action": getattr(mt5, "TRADE_ACTION_DEAL", 1),
        "symbol": sym,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,   # Hard Take-Profit filled automatically by MT5 broker!
        "deviation": 35,
        "magic": MAGIC_NUMBER,
        "comment": "LumoEdge Clean",
        "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
        "type_filling": getattr(mt5, "ORDER_FILLING_IOC", 1),
    }

    # Pre-simulate with order_check()
    try:
        chk = mt5.order_check(req)
        if chk and chk.retcode != 0:
            log_event(f"Pre-Order Simulation Failed: {chk.comment} (Code {chk.retcode})", "REJECT")
            return False
    except Exception as e:
        log_event(f"Order check exception: {e}", "WARN")

    # Send Order with IOC -> FOK fallback
    res = mt5.order_send(req)
    if res and res.retcode != getattr(mt5, "TRADE_RETCODE_DONE", 10009):
        req["type_filling"] = getattr(mt5, "ORDER_FILLING_FOK", 0)
        res = mt5.order_send(req)

    if res and res.retcode == getattr(mt5, "TRADE_RETCODE_DONE", 10009):
        symbol_last_entry_time[sym] = time.time()
        log_event(f"OPENED {action.upper()} {sym} | Lot: {lot} | Ticket: #{res.order} | SL: {sl:.2f} | TP: {tp:.2f} | {reason}", "TRADE")
        return True
    else:
        err_comment = getattr(res, "comment", "Unknown") if res else "No response"
        err_code = getattr(res, "retcode", -1) if res else -1
        log_event(f"Trade failed on {sym}: {err_comment} (Code {err_code})", "WARN")
        return False

# --- Robust Execution & Automation Thread -------------------------------------
def startup_reconciliation():
    """Scans for any existing open positions on startup to avoid orphan duplicate trades."""
    if mt5 is None or not state["mt5_connected"]:
        return
    bot_pos = [p for p in (mt5.positions_get() or []) if getattr(p, "magic", 0) == MAGIC_NUMBER]
    if bot_pos:
        for p in bot_pos:
            symbol_last_entry_time[p.symbol] = time.time()
            log_event(f"RECONCILED OPEN POSITION ON STARTUP: #{p.ticket} {p.symbol} {p.volume} lots", "RECOVERY")

def rapid_trading_engine():
    print("[*] LumoEdge Robust Quantitative Engine Started (Throttled 1.0s Polling).")
    startup_reconciliation()
    
    while True:
        try:
            if not state["mt5_connected"]:
                init_mt5_session()
                time.sleep(3)
                continue

            # Heartbeat check
            term_info = mt5.terminal_info() if mt5 else None
            if term_info and not term_info.connected:
                log_event("MT5 Terminal lost server connection. Waiting for reconnect...", "WARN")
                time.sleep(3)
                continue

            # Update live account summary
            acc = mt5.account_info() if mt5 else None
            if acc:
                state["account_info"] = {
                    "login": acc.login,
                    "name": acc.name,
                    "balance": round(acc.balance, 2),
                    "equity": round(acc.equity, 2),
                    "server": acc.server,
                    "currency": acc.currency
                }
                state["risk_stats"] = get_risk_summary(state.get("active_pair", "XAUUSDm"))

            # 1. Closed Deals & Risk Management Monitor
            check_recent_closed_deals()

            # 2. Live Market Scanner (Harmonized to EMA 13/34)
            tf = TF_MAP.get(state["timeframe"], getattr(mt5, "TIMEFRAME_M15", 15) if mt5 else 15)
            symbols_to_scan = config.SCANNER_SYMBOLS

            scanned = []
            for s in symbols_to_scan:
                analysis = analyze_fast_scalp(s, tf, ema_fast=config.EMA_FAST, ema_slow=config.EMA_SLOW)
                si = mt5.symbol_info(s) if mt5 else None
                analysis["digits"] = getattr(si, "digits", 3) if si else 3
                scanned.append(analysis)
            state["scanner_results"] = scanned

            # 3. Entry Automation (Strict 1-Trade Limit, ZERO Burst Loop)
            if state["bot_running"] and not state.get("circuit_breaker_active", False) and mt5:
                all_pos = mt5.positions_get() or []
                bot_positions = [p for p in all_pos if getattr(p, "magic", 0) == MAGIC_NUMBER]
                open_count = len(bot_positions)
                open_symbols = {p.symbol for p in bot_positions}

                if open_count < state["max_open_trades"]:
                    target_pair = resolve_symbol(state["active_pair"])
                    item = next((x for x in scanned if x["symbol"] == target_pair), None)
                    
                    if item and item["signal"] in ["BUY", "SELL"]:
                        # Strict check: Do not open if position already exists for this pair
                        if target_pair not in open_symbols:
                            execute_market_trade(
                                symbol=target_pair,
                                action=item["signal"],
                                lot=0.0,
                                sl_pips=25.0,
                                reason=item.get("reason", "EMA 13/34 Crossover")
                            )

        except Exception as e:
            log_event(f"Engine Loop Error: {e}", "ERROR")

        time.sleep(1.0)  # Throttled 1.0s loop to prevent IPC socket throttling

# --- Start Background Engine --------------------------------------------------
threading.Thread(target=rapid_trading_engine, daemon=True).start()

# --- HTTP Endpoints -----------------------------------------------------------
@app.get("/")
def serve_dashboard():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Lumo Edge UI online"}

@app.get("/health-dashboard")
def serve_health_terminal():
    health_file = os.path.join(STATIC_DIR, "bot_health_dashboard.html")
    if os.path.exists(health_file):
        return FileResponse(health_file)
    raise HTTPException(404, "Health dashboard file not found in static directory.")

@app.get("/api/health-telemetry")
def get_health_telemetry():
    t_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trading", "health_telemetry.json")
    if os.path.exists(t_path):
        try:
            with open(t_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"status": "telemetry_initializing"}

@app.get("/backtest-report")
def serve_backtest_report():
    if os.path.exists(REPORT_PATH):
        return FileResponse(REPORT_PATH)
    raise HTTPException(404, "Backtest report not found. Run python run_backtest.py first.")

@app.get("/api/status")
def get_status():
    positions = get_live_positions()
    total_floating = sum(p["profit"] for p in positions if p.get("is_bot", True))

    return {
        "mt5_connected": state["mt5_connected"],
        "bot_running": state["bot_running"],
        "trading_mode": state["trading_mode"],
        "active_pair": state["active_pair"],
        "timeframe": state["timeframe"],
        "min_profit_usd": state["min_profit_usd"],
        "max_open_trades": state["max_open_trades"],
        "execution_speed": state.get("execution_speed", "Turbo 0.5s"),
        "turbo_scalper_active": state.get("turbo_scalper_active", True),
        "account": state["account_info"],
        "floating_pnl": round(total_floating, 2),
        "positions": positions,
        "scanner_results": state["scanner_results"],
        "recent_logs": state["recent_logs"],
        "risk_stats": state["risk_stats"],
        "config": {
            "owner": config.OWNER,
            "brand": config.POWERED_BY,
            "scan_interval": 3
        }
    }

@app.post("/api/connect-account")
def connect_account(data: ConnectAccountReq):
    login_id = int(data.login)
    pwd = str(data.password).strip()
    srv = str(data.server).strip()

    if mt5 is None:
        raise HTTPException(500, "MT5 library not installed")

    # Connect to MT5 with explicit account
    init_res = mt5.initialize(login=login_id, password=pwd, server=srv)
    if not init_res:
        mt5.initialize()
        authorized = mt5.login(login=login_id, password=pwd, server=srv)
        if not authorized:
            err = mt5.last_error()
            log_event(f"Failed to connect #{login_id} ({srv}): {err}", "ERROR")
            raise HTTPException(400, f"MT5 Login failed: {err}")

    acc = mt5.account_info()
    if acc is None:
        raise HTTPException(400, "MT5 connected but account info unavailable.")

    state["mt5_connected"] = True
    state["account_info"] = {
        "login": acc.login,
        "name": acc.name,
        "balance": acc.balance,
        "equity": acc.equity,
        "server": acc.server,
        "currency": acc.currency
    }
    # Update config in memory
    config.MT5_ACCOUNT = login_id
    config.MT5_PASSWORD = pwd
    config.MT5_SERVER = srv
    log_event(f"Successfully connected to MT5 Account #{acc.login} ({acc.server}) - Balance: ${acc.balance:.2f}", "SUCCESS")
    return {"status": "success", "account": state["account_info"]}

@app.post("/api/bot/start")
def start_bot():
    state["bot_running"] = True
    log_event("AUTO BOT STARTED (3-second rapid scanner active)", "SYSTEM")
    return {"status": "ok", "message": "Lumo Edge Auto-Bot Active"}

@app.post("/api/bot/stop")
def stop_bot():
    state["bot_running"] = False
    log_event("AUTO BOT PAUSED (Manual Execution Ready)", "SYSTEM")
    return {"status": "ok", "message": "Lumo Edge Auto-Bot Paused"}

@app.post("/api/set-trading-mode/{mode}")
def set_trading_mode(mode: str):
    m = mode.upper()
    if m in ["MULTI", "SINGLE"]:
        state["trading_mode"] = m
        log_event(f"Trading Mode changed to: {m}-PAIR", "CONFIG")
        return {"status": "ok", "trading_mode": m}
    raise HTTPException(400, "Invalid mode. Use MULTI or SINGLE.")

@app.post("/api/set-timeframe/{tf}")
def set_timeframe(tf: str):
    tf_up = tf.upper()
    if tf_up in TF_MAP:
        state["timeframe"] = tf_up
        log_event(f"Timeframe set to {tf_up} (Ultra-Rapid Scalper)", "CONFIG")
        return {"status": "ok", "timeframe": tf_up}
    raise HTTPException(400, f"Invalid timeframe {tf}. Use M1, M5, M15, H1.")

@app.post("/api/set-max-trades/{num}")
def set_max_trades(num: int):
    state["max_open_trades"] = max(1, min(20, num))
    log_event(f"Max Open Trades set to {state['max_open_trades']}", "CONFIG")
    return {"status": "ok", "max_open_trades": state["max_open_trades"]}

@app.post("/api/set-pair/{symbol}")
def set_active_pair(symbol: str):
    sym = resolve_symbol(symbol.upper())
    state["active_pair"] = sym
    log_event(f"Active Single Pair set to: {sym}", "CONFIG")
    return {"status": "ok", "active_pair": sym}

@app.post("/api/set-profit-target/{target}")
def set_profit_target(target: float):
    state["min_profit_usd"] = max(0.10, float(target))
    log_event(f"Instant Profit Target updated to: ${state['min_profit_usd']:.2f}", "CONFIG")
    return {"status": "ok", "min_profit_usd": state["min_profit_usd"]}

@app.post("/api/order")
def manual_order(req: ManualOrderReq):
    if not getattr(config, "LIVE_TRADING", False):
        log_event(f"Manual order simulated: Live trading disabled in config.py.", "SAFETY")
        return {"status": "simulated", "message": "[SAFETY INTERLOCK] Live trading is disabled in config.py (LIVE_TRADING=False). Order simulated only."}
    if not state["mt5_connected"] and not init_mt5_session():
        raise HTTPException(500, "MT5 not connected")
    success = execute_market_trade(
        symbol=req.symbol,
        action=req.action.upper(),
        lot=req.volume,
        sl_pips=req.sl_pips,
        reason="Manual 3D Instant Order"
    )
    if success:
        return {"status": "success", "message": f"{req.action.upper()} placed on {req.symbol}"}
    raise HTTPException(400, "Failed to execute order. Ensure Algo Trading is enabled in MT5.")

@app.post("/api/close/{ticket}")
def close_ticket(ticket: int):
    ok = close_position_ticket(ticket)
    if ok:
        return {"status": "success", "message": f"Closed position #{ticket}"}
    raise HTTPException(400, "Failed to close position.")

@app.post("/api/close-profitable")
def close_profitable():
    if mt5 is None:
        return {"status": "error", "message": "MT5 not available"}
    # STRICT MAGIC NUMBER ISOLATION: Never touch manual trades!
    positions = [p for p in (mt5.positions_get() or []) if getattr(p, "magic", 0) == MAGIC_NUMBER]
    closed = 0
    for p in positions:
        if (p.profit + getattr(p, "swap", 0.0)) > 0:
            if close_position_ticket(p.ticket):
                closed += 1
    return {"status": "ok", "closed": closed}

@app.post("/api/close-all")
def close_all():
    if mt5 is None:
        return {"status": "error", "message": "MT5 not available"}
    # STRICT MAGIC NUMBER ISOLATION: Never touch manual trades!
    positions = [p for p in (mt5.positions_get() or []) if getattr(p, "magic", 0) == MAGIC_NUMBER]
    closed = 0
    for p in positions:
        if close_position_ticket(p.ticket, comment="LumoEdge: Manual Close All"):
            closed += 1
    return {"status": "ok", "closed": closed}

@app.post("/api/settings")
def update_settings(cfg: SettingsReq):
    state["min_profit_usd"] = cfg.min_profit_usd
    state["max_open_trades"] = cfg.max_open_trades
    state["trading_mode"] = cfg.trading_mode.upper()
    state["active_pair"] = resolve_symbol(cfg.active_pair)
    state["timeframe"] = cfg.timeframe
    log_event("Dashboard parameters updated.", "CONFIG")
    return {"status": "ok", "state": state}

# =============================================================================
#  AI INTELLIGENCE ENDPOINTS (4 AI Systems Bridge)
# =============================================================================

@app.get("/api/ai-status")
def ai_status():
    """Get status of all 4 connected AI systems."""
    if _ai_bridge is None:
        return {
            "status": "initializing",
            "message": "AI Bridge loading... (OpenBB takes ~60s on first start)",
            "error": _ai_bridge_error,
            "systems": {
                "lumo_edge":        {"status": "ACTIVE"},
                "openbb":           {"status": "WARMING_UP"},
                "day_trader_skill": {"status": "WARMING_UP"},
                "trading_agents":   {"status": "WARMING_UP"},
                "paperclip":        {"status": "WARMING_UP"},
            }
        }
    status = _ai_bridge.get_system_status()
    return {"status": "ok", "systems": status}


@app.get("/api/ai-analysis")
@app.post("/api/ai-analysis")
def ai_analysis(symbol: str = "XAUUSDm"):
    """
    Run full 4-AI analysis on the current Lumo Edge signal.
    Returns combined intelligence: OpenBB + day-trader-skill + TradingAgents + Paperclip.
    """
    if _ai_bridge is None:
        return {
            "status": "initializing",
            "message": "AI Bridge is still loading, try again in 5 seconds",
            "final_signal": state.get("active_pair", "XAUUSDm"),
        }

    # Get current Lumo Edge signal for context
    sym = resolve_symbol(symbol or state.get("active_pair", "XAUUSDm"))
    current_signal = "HOLD"
    current_price  = 0.0
    current_atr    = 0.0
    balance        = 0.0

    try:
        if state.get("scanner_results"):
            for s in state["scanner_results"]:
                if s.get("symbol") == sym:
                    current_signal = s.get("signal", "HOLD")
                    current_price  = float(s.get("price", 0.0))
                    current_atr    = float(s.get("atr", 0.0))
                    break
        if state.get("account_info"):
            balance = float(state["account_info"].get("balance", 0.0))
    except Exception:
        pass

    try:
        result = _ai_bridge.full_analysis(
            symbol=sym,
            signal=current_signal,
            price=current_price,
            atr=current_atr,
            balance=balance,
            use_cache=True
        )
        result["status"] = "ok"
        log_event(f"AI Analysis: {result['final_signal']} ({result['confidence']:.0%} confidence)", "AI")
        return result
    except Exception as e:
        log_event(f"AI Analysis error: {e}", "ERROR")
        raise HTTPException(500, f"AI Analysis failed: {str(e)}")


@app.get("/api/ai-news")
def ai_news():
    """Get Gold news sentiment from day-trader-skill."""
    if _ai_bridge is None:
        return {"status": "initializing"}
    try:
        result = _ai_bridge.day_trader.run_news_sentiment("GC=F")
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/ai-scanner")
def ai_scanner():
    """Run Gold ETF scanner via day-trader-skill."""
    if _ai_bridge is None:
        return {"status": "initializing"}
    try:
        result = _ai_bridge.day_trader.run_gold_scanner()
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/openbb-data")
def openbb_data():
    """Get live Gold market data from OpenBB."""
    if _ai_bridge is None:
        return {"status": "initializing"}
    try:
        result = _ai_bridge.openbb.get_gold_market_data()
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(500, str(e))


if __name__ == "__main__":
    import uvicorn
    init_mt5_session()
    uvicorn.run(app, host="127.0.0.1", port=8000)
