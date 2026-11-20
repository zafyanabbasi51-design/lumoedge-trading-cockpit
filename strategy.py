"""
=============================================================================
 LUMO EDGE - STRATEGY ENGINE (EMA 50 / EMA 200)
 Owner: Gontse | Powered by: Lumo Edge
=============================================================================
Pure signal logic and MT5 market data helpers.
Calculates signals on CLOSED candles only to eliminate repainting.

Entries:
  1. Golden / Death Cross: fresh EMA 50 / 200 cross within last CROSS_LOOKBACK bars
  2. Trend Pullback: price tags EMA 50 in a trend and closes back with trend
Filters:
  - EMA 200 5-bar slope confirming direction
  - Minimum EMA gap >= 0.3 * ATR (anti-chop filter)
  - RSI(14) with Wilder smoothing: no BUY > 70, no SELL < 30
"""

import pandas as pd
import numpy as np
import config

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


def resolve_symbol(symbol: str) -> str:
    """
    Detects broker-specific suffix for a forex pair (e.g., EURUSD -> EURUSDm, EURUSD.raw).
    """
    if mt5 is None:
        return symbol
    try:
        if mt5.symbol_info(symbol) is not None:
            return symbol
        base = symbol[:-1] if symbol.endswith("m") or symbol.endswith("c") else symbol
        candidates = (base, base + "m", base + "c", base + ".raw", base + "_i", base + ".s")
        for cand in candidates:
            if mt5.symbol_info(cand) is not None:
                return cand
    except Exception:
        pass
    return symbol


def get_rates(symbol: str, timeframe, num_bars: int = 500) -> pd.DataFrame:
    """
    Fetches OHLCV candle rates from MT5.
    """
    if mt5 is None:
        return pd.DataFrame()
    actual = resolve_symbol(symbol)
    si = mt5.symbol_info(actual)
    if si is not None and not si.visible:
        mt5.symbol_select(actual, True)

    rates = mt5.copy_rates_from_pos(actual, timeframe, 0, num_bars)
    if rates is None or len(rates) == 0:
        return pd.DataFrame()

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Wilder's RSI implementation using exponential moving average with alpha = 1 / period.
    """
    diff = close.diff()
    gain = diff.clip(lower=0).ewm(alpha=1.0 / period, adjust=False).mean()
    loss = (-diff.clip(upper=0)).ewm(alpha=1.0 / period, adjust=False).mean()

    # Guard against division by zero
    rs = gain / loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.fillna(50.0)
    rsi = rsi.where(~((loss == 0) & (gain > 0)), 100.0)
    rsi = rsi.where(~((loss == 0) & (gain == 0)), 50.0)
    return rsi


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range (ATR) with Wilder smoothing.
    """
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average Directional Index (ADX) calculation with Wilder smoothing.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    high_diff = high.diff()
    low_diff = -low.diff()

    plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0.0)
    minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0.0)

    smooth_tr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    smooth_pdm = plus_dm.ewm(alpha=1.0 / period, adjust=False).mean()
    smooth_mdm = minus_dm.ewm(alpha=1.0 / period, adjust=False).mean()

    plus_di = 100.0 * (smooth_pdm / smooth_tr.replace(0, np.nan))
    minus_di = 100.0 * (smooth_mdm / smooth_tr.replace(0, np.nan))

    dx = 100.0 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.ewm(alpha=1.0 / period, adjust=False).mean()
    return adx.fillna(15.0)


def compute_signal(df: pd.DataFrame, ema_fast: int = None, ema_slow: int = None) -> dict:
    """
    Pure signal function: DataFrame (time, open, high, low, close) -> signal dict.
    Strictly uses CLOSED candles only (drops the current forming candle at index -1).
    Enforces:
      1. Fresh EMA crossover within CROSS_LOOKBACK bars
      2. ADX >= ADX_MIN_THRESHOLD (Anti-chop / trending regime)
      3. RSI Overbought/Oversold boundary filter
    """
    ema_fast = ema_fast or config.EMA_FAST
    ema_slow = ema_slow or config.EMA_SLOW

    out = {
        "signal": "HOLD",
        "reason": "",
        "price": 0.0,
        "ema50": 0.0,
        "ema200": 0.0,
        "atr": 0.0,
        "adx": 0.0,
        "rsi": 50.0,
        "bar_time": None
    }

    min_required_bars = max((2 * ema_slow) + 5, 50)
    if df is None or len(df) < min_required_bars:
        out["reason"] = f"Not enough history ({len(df) if df is not None else 0}/{min_required_bars} bars)"
        return out

    # Closed candles only: live forming candle is at index -1
    live_price = float(df["close"].iloc[-1])
    d = df.iloc[:-1].copy()

    # Compute technical indicators
    d["fast"] = d["close"].ewm(span=ema_fast, adjust=False).mean()
    d["slow"] = d["close"].ewm(span=ema_slow, adjust=False).mean()
    d["rsi"] = _rsi(d["close"], getattr(config, "RSI_PERIOD", 14))
    d["atr"] = _atr(d, getattr(config, "ATR_PERIOD", 14))
    d["adx"] = _adx(d, getattr(config, "ADX_PERIOD", 14))

    last = d.iloc[-1]
    prev = d.iloc[-2]
    
    fast = float(last["fast"])
    slow = float(last["slow"])
    atr = float(last["atr"])
    rsi = float(last["rsi"])
    adx = float(last["adx"])
    bar_time = last["time"] if "time" in d else d.index[-1]

    out.update(
        price=live_price,
        ema50=fast,
        ema200=slow,
        atr=atr,
        adx=adx,
        rsi=rsi,
        bar_time=bar_time
    )

    if atr <= 0 or np.isnan(atr):
        out["reason"] = "ATR unavailable or zero"
        return out

    # 1. Fresh Crossover Check on Completed Candles
    fast_prev = float(prev["fast"])
    slow_prev = float(prev["slow"])
    
    cross_up = (fast_prev <= slow_prev) and (fast > slow)
    cross_down = (fast_prev >= slow_prev) and (fast < slow)

    # Check lookback window for recent cross
    lookback = getattr(config, "CROSS_LOOKBACK", 3)
    recent_cross_up = False
    recent_cross_down = False
    
    for k in range(1, min(lookback + 1, len(d))):
        f_k = float(d["fast"].iloc[-k])
        s_k = float(d["slow"].iloc[-k])
        f_k_prev = float(d["fast"].iloc[-k-1])
        s_k_prev = float(d["slow"].iloc[-k-1])
        if (f_k_prev <= s_k_prev) and (f_k > s_k):
            recent_cross_up = True
            break
        if (f_k_prev >= s_k_prev) and (f_k < s_k):
            recent_cross_down = True
            break

    if not (recent_cross_up or recent_cross_down):
        out["reason"] = f"No fresh EMA {ema_fast}/{ema_slow} cross in last {lookback} bars (Gap: {fast-slow:.2f})"
        return out

    # 2. ADX Trend Strength Filter
    adx_threshold = getattr(config, "ADX_MIN_THRESHOLD", 20.0)
    if adx < adx_threshold:
        out["reason"] = f"Rejected: ADX {adx:.1f} < {adx_threshold} (Ranging/Chop regime)"
        return out

    # 3. Minimum EMA Gap Filter
    min_gap = getattr(config, "MIN_EMA_GAP_ATR", 0.2) * atr
    if abs(fast - slow) < min_gap:
        out["reason"] = f"Rejected: EMA gap {abs(fast-slow):.2f} < {min_gap:.2f} (0.2x ATR)"
        return out

    # 4. RSI Overbought/Oversold Filter
    if recent_cross_up:
        if rsi >= getattr(config, "RSI_OVERBOUGHT", 70):
            out["reason"] = f"Rejected BUY: RSI {rsi:.1f} >= 70 (Overbought)"
            return out
        out.update(signal="BUY", reason=f"Valid Bullish Crossover EMA{ema_fast}>{ema_slow} | ADX: {adx:.1f} | RSI: {rsi:.0f}")

    elif recent_cross_down:
        if rsi <= getattr(config, "RSI_OVERSOLD", 30):
            out["reason"] = f"Rejected SELL: RSI {rsi:.1f} <= 30 (Oversold)"
            return out
        out.update(signal="SELL", reason=f"Valid Bearish Crossover EMA{ema_fast}<{ema_slow} | ADX: {adx:.1f} | RSI: {rsi:.0f}")

    return out


def analyze_symbol(symbol: str, timeframe, ema_fast: int = None, ema_slow: int = None) -> dict:
    """Helper to fetch rates and compute signal for a symbol."""
    rates = get_rates(symbol, timeframe)
    res = compute_signal(rates, ema_fast, ema_slow)
    res["symbol"] = symbol
    return res


def analyze_fast_scalp(symbol: str, timeframe=None, ema_fast: int = 50, ema_slow: int = 200) -> dict:
    """Backward-compatible function used by web UI server."""
    if timeframe is None and mt5 is not None:
        timeframe = mt5.TIMEFRAME_M5
    return analyze_symbol(symbol, timeframe, ema_fast, ema_slow)
