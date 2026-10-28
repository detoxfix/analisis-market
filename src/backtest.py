"""Backtest aturan jangka pendek & menengah (juga dipakai oleh tune.py).

Setiap kali syarat masuk terpenuhi (skor >= minimum DAN lolos filter pasar/tren) setelah sebelumnya
tidak terpenuhi, rencana trading dibuat dari data hari itu lalu disimulasikan ke depan
(masuk T+1, TP/SL/trailing/time-stop, termasuk biaya). Satu posisi per saham per horizon.
Catatan: universe memakai market cap SAAT INI (survivorship bias) -> hasil cenderung optimistis.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .risk import make_plan
from .signals import HORIZON_FUNCS, compose, entry_mask
from .sim import ema_np, simulate_arr
from .utils import log


def prepare(ind: dict[str, pd.DataFrame], horizons=("short", "medium")) -> dict:
    """Hitung sekali: array harga + skor per horizon (tidak bergantung parameter yang di-tuning)."""
    prep = {}
    for t, d in ind.items():
        item = {"d": d, "dates": d.index,
                **{k: d[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close", "ATR14", "EMA20", "SMA50")},
                "ema": {}}
        for h in horizons:
            fn, W = HORIZON_FUNCS[h]
            score, _ = compose(fn(d), W)
            item[f"score_{h}"] = score
        prep[t] = item
    return prep


def trades_for(prep: dict, h: str, hcfg: dict, cfg: dict, detail: bool = False) -> pd.DataFrame:
    th, fees = cfg["thresholds"], cfg["fees"]
    tm = int(hcfg.get("trail_ma") or 0)
    rows = []
    for t, it in prep.items():
        score = it[f"score_{h}"]
        key = (h, hcfg.get("min_score", th["buy"]), hcfg.get("market_filter"), hcfg.get("trend_filter"))
        cache = it.setdefault("mask", {})
        if key not in cache:
            ok, _ = entry_mask(it["d"], score, hcfg, th)
            cache[key] = ok.to_numpy()
        okv = cache[key]
        prev = np.r_[False, okv[:-1]]
        events = np.where(okv & ~prev)[0]
        if not len(events):
            continue
        trail = None
        if tm:
            trail = it["ema"].get(tm)
            if trail is None:
                trail = it["ema"][tm] = ema_np(it["Close"], tm)
        sv = score.to_numpy()
        next_free = 0
        for pos in events:
            if pos < next_free or pos >= len(okv) - 1:
                continue
            row = {"Close": it["Close"][pos], "ATR14": it["ATR14"][pos], "EMA20": it["EMA20"][pos],
                   "SMA50": it["SMA50"][pos]}
            plan = make_plan(row, h, hcfg, fees, texts=False)
            if plan is None:
                continue
            res = simulate_arr(it["Open"], it["High"], it["Low"], it["Close"], int(pos), plan, fees, trail)
            next_free = res["exit_pos"] + 1
            if res["filled"] and "OPEN" not in res["outcome"]:
                row_ = {"ticker": t, "date": it["dates"][pos], "score": sv[pos], "ret": res["ret"],
                        "days": res["days"], "outcome": res["outcome"]}
                if detail:
                    d_ = it["dates"]
                    row_.update({"entry_date": d_[res["entry_pos"]], "exit_date": d_[res["exit_pos"]],
                                 "tp1_date": d_[res["tp1_pos"]] if res["tp1_pos"] is not None else pd.NaT,
                                 "entry_px": res["entry_px"], "exit_px": res["exit_px"],
                                 "tp1_px": res["tp1_px"], "sl": plan["sl"],
                                 "atr_pct": it["ATR14"][pos] / it["Close"][pos]})
                rows.append(row_)
            elif not res["filled"] and res["outcome"] == "BATAL":
                rows.append({"ticker": t, "date": it["dates"][pos], "score": sv[pos], "ret": np.nan,
                             "days": 0, "outcome": "BATAL"})
    cols = ["ticker", "date", "score", "ret", "days", "outcome"]
    if detail:
        cols += ["entry_date", "exit_date", "tp1_date", "entry_px", "exit_px", "tp1_px", "sl", "atr_pct"]
    return pd.DataFrame(rows, columns=cols)


def stats(tr: pd.DataFrame) -> dict:
    filled = tr[tr["outcome"] != "BATAL"] if len(tr) else tr
    if filled.empty:
        return {"n": 0}
    r = filled["ret"].astype(float)
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    return {
        "n": int(len(r)), "win_rate": float((r > 0).mean()), "avg_ret": float(r.mean()),
        "median_ret": float(r.median()), "profit_factor": float(gains / losses) if losses > 0 else None,
        "avg_days": float(filled["days"].mean()), "worst": float(r.min()), "best": float(r.max()),
        "fill_rate": float(len(filled) / len(tr)),
        "outcomes": {k: int(v) for k, v in filled["outcome"].value_counts().items()},
    }


def full_stats(tr: pd.DataFrame, split: str | None = None) -> dict:
    st = stats(tr)
    if tr.empty:
        return st
    st["period"] = [pd.Timestamp(tr["date"].min()).strftime("%Y-%m-%d"),
                    pd.Timestamp(tr["date"].max()).strftime("%Y-%m-%d")]
    if split:
        cut = pd.Timestamp(split)
        st["in_sample"] = stats(tr[tr["date"] < cut])
        st["out_sample"] = stats(tr[tr["date"] >= cut])
    st["by_year"] = {str(y): stats(g) for y, g in tr.groupby(pd.to_datetime(tr["date"]).dt.year)}
    return st


def run(ind: dict[str, pd.DataFrame], cfg: dict) -> dict:
    hs = cfg.get("backtest", {}).get("horizons", ["short", "medium"])
    prep = prepare(ind, hs)
    split = cfg.get("backtest", {}).get("split_date")
    out = {}
    for h in hs:
        tr = trades_for(prep, h, cfg["horizons"][h], cfg)
        st = full_stats(tr, split)
        if not tr.empty:
            strong = cfg["thresholds"]["strong_buy"]
            st["strong_only"] = stats(tr[tr["score"] >= strong])
        out[h] = st
        log.info("Backtest %s: %s transaksi, win rate %s, PF %s", h, st.get("n"),
                 f"{st['win_rate']:.0%}" if st.get("n") else "-",
                 f"{st['profit_factor']:.2f}" if st.get("profit_factor") else "-")
    return out
