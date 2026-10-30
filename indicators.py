"""Indikator teknikal (murni pandas/numpy, tanpa dependensi TA eksternal)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def rma(s: pd.Series, n: int) -> pd.Series:
    """Wilder smoothing."""
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = rma(d.clip(lower=0), n)
    dn = rma(-d.clip(upper=0), n)
    out = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    return out.where(dn != 0, 100.0).where(up.notna())


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["Close"].shift()
    return pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()],
                     axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return rma(true_range(df), n)


def adx(df: pd.DataFrame, n: int = 14):
    up = df["High"].diff()
    dn = -df["Low"].diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = rma(true_range(df), n)
    pdi = 100 * rma(plus_dm, n) / tr
    mdi = 100 * rma(minus_dm, n) / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return rma(dx, n), pdi, mdi


def add_indicators(df: pd.DataFrame, bench: pd.Series | None = None) -> pd.DataFrame:
    """Tambahkan semua kolom indikator yang dipakai mesin sinyal."""
    out = df.copy()
    c = out["Close"]

    out["EMA9"] = ema(c, 9)
    out["EMA20"] = ema(c, 20)
    out["EMA50"] = ema(c, 50)
    out["SMA50"] = sma(c, 50)
    out["SMA100"] = sma(c, 100)
    out["SMA200"] = sma(c, 200)
    out["SMA50_slope"] = out["SMA50"].pct_change(10)
    out["SMA200_slope"] = out["SMA200"].pct_change(20)

    out["RSI14"] = rsi(c, 14)
    macd = ema(c, 12) - ema(c, 26)
    out["MACD"] = macd
    out["MACD_signal"] = ema(macd, 9)
    out["MACD_hist"] = macd - out["MACD_signal"]

    out["ATR14"] = atr(out, 14)
    out["ATR_pct"] = out["ATR14"] / c
    out["ADX14"], out["PDI"], out["MDI"] = adx(out, 14)

    out["VOL_MA20"] = sma(out["Volume"], 20)
    out["VOL_RATIO"] = out["Volume"] / out["VOL_MA20"].replace(0, np.nan)
    out["VALUE"] = c * out["Volume"]
    out["VALUE_MA20"] = sma(out["VALUE"], 20)

    out["HH20"] = out["High"].rolling(20, min_periods=20).max().shift(1)   # resistance 20 hari sebelumnya
    out["LL20"] = out["Low"].rolling(20, min_periods=20).min().shift(1)
    out["LL10"] = out["Low"].rolling(10, min_periods=10).min().shift(1)
    out["HH250"] = out["High"].rolling(250, min_periods=120).max()

    out["CHG_1D"] = c.pct_change(1)
    out["RET_20"] = c.pct_change(20)
    out["RET_60"] = c.pct_change(60)
    out["MOM_12_1"] = c.shift(21) / c.shift(252) - 1                      # momentum 12 bulan minus 1 bulan
    out["DIST_HH250"] = c / out["HH250"] - 1

    if bench is not None and len(bench) > 0:
        b_full = bench.sort_index()
        b_ema20 = ema(b_full, 20)
        b = b_full.reindex(out.index).ffill()
        out["BENCH"] = b
        above = (b_full > b_ema20).astype(float).where(b_ema20.notna())
        out["BENCH_UP"] = above.reindex(out.index).ffill()
        for name, ma in (("ema20", b_ema20), ("sma50", sma(b_full, 50)), ("sma200", sma(b_full, 200))):
            ok = (b_full > ma).astype(float).where(ma.notna())
            out[f"MKT_{name}"] = ok.reindex(out.index).ffill()
        out["RS_60"] = out["RET_60"] - b.pct_change(60)
    else:
        out["BENCH"] = np.nan
        out["BENCH_UP"] = np.nan
        out["RS_60"] = np.nan
        for name in ("ema20", "sma50", "sma200"):
            out[f"MKT_{name}"] = np.nan
    return out
