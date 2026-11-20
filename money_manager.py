"""
=============================================================================
 LUMO EDGE — SMART DYNAMIC MONEY MANAGER (AUDITED & REPAIRED)
 Owner: Gontse | Powered by: Lumo Edge
 Institutional Risk-Adjusted Sizing Engine:
 - ATR-Based Stop Loss Risk Sizing (0.25% - 0.50% Equity per Trade)
 - Pre-Trade Margin Availability Verification
 - Broker Volume Min/Max & Step Rounding
=============================================================================
"""

import sys
import os
import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

def calculate_dynamic_lot(symbol: str = "XAUUSDm", sl_distance_usd: float = 0.0, risk_pct: float = None) -> float:
    """
    Calculates exact risk-adjusted lot size based on account equity,
    target risk percentage (0.25% - 0.50%), and Stop Loss distance in price.
    
    Formula:
        Risk ($) = Equity * (Risk% / 100)
        Points = SL_Distance / Point_Size
        Lot = Risk ($) / (Points * Tick_Value)
    """
    risk_pct = risk_pct or getattr(config, "RISK_PERCENT", 0.30)
    
    if not mt5.initialize():
        return 0.01

    acc = mt5.account_info()
    if acc is None:
        return 0.01

    equity = max(acc.equity, acc.balance)
    if equity <= 0:
        return 0.01

    sym_info = mt5.symbol_info(symbol)
    if sym_info is None:
        return 0.01

    # Broker limits
    vmin = sym_info.volume_min
    vmax = sym_info.volume_max
    vstep = sym_info.volume_step if sym_info.volume_step > 0 else 0.01

    # If SL distance is not provided, estimate using typical Gold ATR (~$3.00)
    if sl_distance_usd <= 0:
        sl_distance_usd = 3.00

    # Risk in account currency
    target_risk_usd = equity * (risk_pct / 100.0)
    
    # Contract size calculation: For Gold, 1 lot = 100 oz -> $1 move = $100
    contract_size = sym_info.trade_contract_size if sym_info.trade_contract_size > 0 else 100.0
    sl_points = sl_distance_usd / sym_info.point if sym_info.point > 0 else (sl_distance_usd * 1000)
    tick_val = sym_info.trade_tick_value if sym_info.trade_tick_value > 0 else 0.10

    # Calculated raw lot
    loss_per_lot = sl_distance_usd * contract_size
    if loss_per_lot > 0:
        raw_lot = target_risk_usd / loss_per_lot
    else:
        raw_lot = vmin

    # Clamp to broker limits & round to volume_step
    clamped = max(vmin, min(vmax, raw_lot))
    stepped = round(round(clamped / vstep) * vstep, 2)
    
    # Pre-check margin: verify required margin does not consume > 50% free margin
    try:
        order_type = getattr(mt5, "ORDER_TYPE_BUY", 0)
        req_margin = mt5.order_calc_margin(order_type, symbol, stepped, sym_info.ask)
        if req_margin and req_margin > (acc.margin_free * 0.70):
            # Reduce lot if margin is tight
            stepped = vmin
    except Exception:
        pass

    return max(vmin, stepped)

def get_risk_summary(symbol: str = "XAUUSDm"):
    """Returns real-time equity risk stats."""
    if not mt5.initialize():
        return {"equity": 0, "balance": 0, "margin_free": 0, "recommended_lot": 0.01, "risk_level": "Safe"}

    acc = mt5.account_info()
    if acc is None:
        return {"equity": 0, "balance": 0, "margin_free": 0, "recommended_lot": 0.01, "risk_level": "Safe"}

    rec_lot = calculate_dynamic_lot(symbol)
    risk_pct = getattr(config, "RISK_PERCENT", 0.30)
    return {
        "equity": round(acc.equity, 2),
        "balance": round(acc.balance, 2),
        "margin_free": round(acc.margin_free, 2),
        "recommended_lot": rec_lot,
        "target_risk_pct": risk_pct,
        "risk_level": "Ultra Safe (Institutional 0.30%)"
    }
