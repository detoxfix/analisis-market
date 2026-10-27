"""Simulasi satu transaksi mengikuti rencana (dipakai track record & backtest).

Aturan:
- Masuk di OPEN hari berikutnya bila open <= batas kejar (entry_high) dan > SL; jika tidak -> 'BATAL'.
- Setiap hari: cek SL dulu (konservatif), lalu TP1 (jual 50%, SL naik ke harga beli), lalu TP2.
- Time-stop: setelah `max_hold_days` hari bursa, sisa posisi dijual di harga penutupan.
"""
from __future__ import annotations

import pandas as pd


def simulate(df: pd.DataFrame, signal_pos: int, plan: dict, fees: dict) -> dict:
    n = len(df)
    fb, fs = fees["buy"], fees["sell"]
    res = {"filled": False, "outcome": "BATAL", "ret": 0.0, "days": 0,
           "entry_date": None, "entry_px": None, "exit_date": None, "exit_px": None, "tp1_hit": False,
           "exit_pos": signal_pos}
    e = signal_pos + 1
    if e >= n:
        res["outcome"] = "MENUNGGU"
        return res
    o = float(df["Open"].iat[e])
    if o > plan["entry_high"] or o <= plan["sl"]:
        res["exit_pos"] = e
        return res

    entry = o
    sl, tp1, tp2 = plan["sl"], plan["tp1"], plan["tp2"]
    tp1_hit = False
    part1 = None
    exit_px, outcome, j = None, None, e
    max_hold = plan["max_hold_days"]
    for j in range(e, n):
        hi, lo, op, cl = (float(df[k].iat[j]) for k in ("High", "Low", "Open", "Close"))
        if lo <= sl:
            exit_px = min(op, sl) if j > e else sl
            outcome = "BE" if tp1_hit else "SL"
            break
        if not tp1_hit and hi >= tp1:
            tp1_hit, part1, sl = True, tp1, max(sl, entry)
        if hi >= tp2:
            exit_px, outcome = tp2, "TP2"
            break
        if j - e + 1 >= max_hold:
            exit_px, outcome = cl, "TIME"
            break
    if exit_px is None:                       # data habis -> posisi masih terbuka
        exit_px, outcome = float(df["Close"].iat[n - 1]), "OPEN"
        j = n - 1

    def net(px):
        return px * (1 - fs) / (entry * (1 + fb)) - 1

    ret = 0.5 * net(part1) + 0.5 * net(exit_px) if tp1_hit else net(exit_px)
    if tp1_hit and outcome in ("BE", "TIME", "OPEN"):
        outcome = "TP1+" + outcome
    res.update({"filled": True, "outcome": outcome, "ret": ret, "days": j - e + 1,
                "entry_date": df.index[e], "entry_px": entry, "exit_date": df.index[j],
                "exit_px": exit_px, "tp1_hit": tp1_hit, "exit_pos": j})
    return res
