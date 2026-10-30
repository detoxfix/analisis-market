"""Simulasi satu transaksi mengikuti rencana (dipakai track record, backtest & tuning).

Aturan:
- entry_mode "open"  : masuk di OPEN hari berikutnya bila open <= batas kejar (entry_high) dan > SL.
  entry_mode "limit" : antre beli di harga `entry` (area bawah) selama `limit_days` hari bursa;
                       terisi di open bila open <= entry, atau di harga entry bila low menyentuhnya.
  Tidak terisi -> 'BATAL'.
- Setiap hari: cek SL dulu (konservatif), lalu TP1 (jual 50%, SL naik ke harga beli), lalu TP2.
- Trailing (opsional, `trail_ma` > 0): setelah TP1, sisa posisi dijual bila close < EMA(trail_ma).
- Keluar saat pasar berbalik (opsional, `market_exit`): bila IHSG close di bawah MA `market_exit_ma`
  selama `market_exit_confirm` hari berturut-turut saat posisi terbuka:
    "half" -> jual 50% di close (sekali saja; tidak berlaku bila separuh sudah dijual di TP1)
    "all"  -> jual seluruh sisa posisi di close
- Time-stop: setelah `max_hold_days` hari bursa sejak masuk, sisa posisi dijual di close.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _num(x, default):
    try:
        f = float(x)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def ema_np(c: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(c).ewm(span=n, adjust=False).mean().to_numpy()


def market_flag(mkt_up, confirm: int = 1) -> np.ndarray:
    """mkt_up: 1 bila IHSG di atas MA, 0 bila di bawah, NaN = belum diketahui.
    Return True pada hari IHSG sudah `confirm` hari berturut-turut di bawah MA."""
    up = np.asarray(mkt_up, dtype=float)
    bad = up < 0.5                                   # NaN -> False
    out = bad.copy()
    for k in range(1, max(1, int(confirm))):
        out[k:] &= bad[:-k]
        out[:k] = False
    return out


def bench_up(bench: pd.Series, ma: str, index) -> np.ndarray:
    """Posisi IHSG terhadap MA (ema20/sma50/sma200), diselaraskan ke tanggal `index`."""
    b = bench.dropna().sort_index()
    line = (b.ewm(span=20, adjust=False, min_periods=20).mean() if ma == "ema20"
            else b.rolling(int(ma.replace("sma", "")), min_periods=int(ma.replace("sma", ""))).mean())
    up = (b > line).astype(float).where(line.notna())
    return up.reindex(pd.DatetimeIndex(index)).ffill().to_numpy()


def simulate_arr(o, h, l, c, signal_pos: int, plan: dict, fees: dict, trail_line=None, mkt_exit=None) -> dict:
    n = len(c)
    fb, fs = fees["buy"], fees["sell"]
    res = {"filled": False, "outcome": "BATAL", "ret": 0.0, "days": 0, "entry_pos": None,
           "entry_px": None, "exit_pos": signal_pos, "exit_px": None, "tp1_hit": False}
    sl, tp1, tp2 = plan["sl"], plan["tp1"], plan["tp2"]
    mode = plan.get("entry_mode") or "open"
    if not isinstance(mode, str):
        mode = "open"
    max_hold = int(_num(plan.get("max_hold_days"), 10))
    first = signal_pos + 1
    if first >= n:
        res["outcome"] = "MENUNGGU"
        return res

    # ---------------- entry
    e, entry = None, None
    if mode == "limit":
        limit = plan["entry"]
        last = min(n - 1, signal_pos + int(_num(plan.get("limit_days"), 3)))
        for j in range(first, last + 1):
            if o[j] <= sl:                       # gap turun menembus SL -> batal
                res["exit_pos"] = j
                return res
            if o[j] <= limit:
                e, entry = j, o[j]
                break
            if l[j] <= limit:
                e, entry = j, limit
                break
        if e is None:
            if last < signal_pos + int(_num(plan.get("limit_days"), 3)):
                res["outcome"] = "MENUNGGU"
            res["exit_pos"] = last
            return res
    else:
        if o[first] > plan["entry_high"] or o[first] <= sl:
            res["exit_pos"] = first
            return res
        e, entry = first, o[first]

    # ---------------- kelola posisi
    tp1_hit, part1, tp1_pos = False, None, None      # part1/tp1_pos = penjualan separuh pertama (TP1 atau pasar)
    mx = plan.get("market_exit") or "none"
    if not isinstance(mx, str) or mkt_exit is None:
        mx = "none"
    mkt_half = False
    exit_px, outcome, j = None, None, e
    for j in range(e, n):
        if l[j] <= sl:                         # termasuk hari masuk (asumsi terburuk)
            exit_px = min(o[j], sl) if j > e else sl
            outcome = "BE" if tp1_hit else "SL"
            break
        if not tp1_hit and h[j] >= tp1:
            if part1 is None:
                part1, tp1_pos = tp1, j
            tp1_hit, sl = True, max(sl, entry)
        if h[j] >= tp2:
            exit_px, outcome = tp2, "TP2"
            break
        if tp1_hit and trail_line is not None and c[j] < trail_line[j]:
            exit_px, outcome = c[j], "TRAIL"
            break
        if mx != "none" and mkt_exit[j]:
            if mx == "all":
                exit_px, outcome = c[j], "MKT"
                break
            if part1 is None:                          # "half": jual separuh sekali
                part1, tp1_pos, mkt_half = c[j], j, True
        if j - e + 1 >= max_hold:
            exit_px, outcome = c[j], "TIME"
            break
    if exit_px is None:                        # data habis -> posisi masih terbuka
        exit_px, outcome, j = c[n - 1], "OPEN", n - 1

    def net(px):
        return px * (1 - fs) / (entry * (1 + fb)) - 1

    ret = 0.5 * net(part1) + 0.5 * net(exit_px) if part1 is not None else net(exit_px)
    if mkt_half:
        outcome = "MKT½+" + outcome
    elif tp1_hit and outcome in ("BE", "TIME", "OPEN", "TRAIL", "MKT"):
        outcome = "TP1+" + outcome
    res.update({"filled": True, "outcome": outcome, "ret": float(ret), "days": j - e + 1,
                "entry_pos": e, "entry_px": float(entry), "exit_pos": j, "exit_px": float(exit_px),
                "tp1_hit": tp1_hit, "tp1_pos": tp1_pos, "tp1_px": part1})
    return res


def simulate(df: pd.DataFrame, signal_pos: int, plan: dict, fees: dict, bench: pd.Series | None = None) -> dict:
    """Versi DataFrame (untuk tracker). `bench` (IHSG) dibutuhkan untuk aturan keluar saat pasar berbalik."""
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close"))
    tm = int(_num(plan.get("trail_ma"), 0))
    trail = ema_np(c, tm) if tm > 0 else None
    mkt = None
    mx = plan.get("market_exit")
    if isinstance(mx, str) and mx != "none" and bench is not None and len(bench):
        ma = plan.get("market_exit_ma") if isinstance(plan.get("market_exit_ma"), str) else "sma50"
        mkt = market_flag(bench_up(bench, ma, df.index), int(_num(plan.get("market_exit_confirm"), 1)))
    r = simulate_arr(o, h, l, c, signal_pos, plan, fees, trail, mkt)
    r["entry_date"] = df.index[r["entry_pos"]] if r["entry_pos"] is not None else None
    r["exit_date"] = df.index[r["exit_pos"]] if r["filled"] else None
    return r
