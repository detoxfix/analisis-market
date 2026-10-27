"""Backtest sederhana untuk aturan jangka pendek & menengah.

Setiap kali skor menembus ambang BUY dari bawah, rencana trading dibuat dari data hari itu
lalu disimulasikan ke depan (masuk T+1 open, TP/SL/time-stop, termasuk biaya).
Catatan: universe memakai market cap SAAT INI (survivorship bias) -> hasil cenderung optimistis.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .risk import make_plan
from .signals import HORIZON_FUNCS, compose
from .sim import simulate
from .utils import log


def _stats(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"n": 0}
    r = tr["ret"]
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    return {
        "n": int(len(r)), "win_rate": float((r > 0).mean()), "avg_ret": float(r.mean()),
        "median_ret": float(r.median()), "profit_factor": float(gains / losses) if losses > 0 else None,
        "avg_days": float(tr["days"].mean()), "worst": float(r.min()), "best": float(r.max()),
        "outcomes": {k: int(v) for k, v in tr["outcome"].value_counts().items()},
    }


def run(ind: dict[str, pd.DataFrame], cfg: dict) -> dict:
    th = cfg["thresholds"]
    out = {}
    for h in cfg.get("backtest", {}).get("horizons", ["short", "medium"]):
        comp_fn, W = HORIZON_FUNCS[h]
        hcfg = cfg["horizons"][h]
        trades = []
        for t, d in ind.items():
            score, _ = compose(comp_fn(d), W)
            s = score.to_numpy()
            prev = np.r_[np.nan, s[:-1]]
            cross = np.where((s >= th["buy"]) & (prev < th["buy"]))[0]
            next_free = 0
            for pos in cross:
                if pos < next_free or pos >= len(d) - 1:
                    continue
                plan = make_plan(d.iloc[pos], h, hcfg, cfg["fees"])
                if plan is None:
                    continue
                res = simulate(d, int(pos), plan, cfg["fees"])
                next_free = res["exit_pos"] + 1
                if res["filled"] and "OPEN" not in res["outcome"]:
                    trades.append({"ticker": t, "date": d.index[pos], "score": s[pos], "ret": res["ret"],
                                   "days": res["days"], "outcome": res["outcome"]})
        tr = pd.DataFrame(trades)
        st = _stats(tr)
        if not tr.empty:
            st["strong_only"] = _stats(tr[tr["score"] >= th["strong_buy"]])
            st["period"] = [tr["date"].min().strftime("%Y-%m-%d"), tr["date"].max().strftime("%Y-%m-%d")]
        out[h] = st
        log.info("Backtest %s: %s transaksi, win rate %s", h, st.get("n"),
                 f"{st['win_rate']:.0%}" if st.get("n") else "-")
    return out
