"""Backtest tingkat PORTOFOLIO: menjalankan sinyal pendek & menengah sebagai akun sungguhan.

Setiap hari bursa:
  1. Posisi baru dibuka pada hari terisinya order (urut skor tertinggi) bila kuota posisi masih ada,
     saham belum dipegang, dan kas cukup. Ukuran = ekuitas bucket x min(max_weight, 1/max_positions),
     dibatasi aturan risiko (rugi ke SL <= risk_per_trade x modal total), dibulatkan ke lot (100 lembar).
  2. TP1 -> jual separuh lot; keluar akhir (TP2/SL/BE/trailing/time-stop) -> jual sisa. Biaya termasuk.
  3. Nilai portofolio = kas + jumlah lembar x harga penutupan (mark-to-market).
Bucket jangka panjang tidak bisa disimulasikan (butuh fundamental historis) -> diperlakukan sebagai kas.
Keterbatasan: universe memakai market cap saat ini (survivorship bias); bobot disederhanakan (setara).
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
import pandas as pd

from . import backtest as bt
from .utils import log


def metrics(eq: pd.Series, exposure: pd.Series | None = None) -> dict:
    eq = eq.dropna()
    if len(eq) < 20:
        return {}
    ret = eq.pct_change().dropna()
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    total = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else None
    peak = eq.cummax()
    dd = eq / peak - 1
    trough = dd.idxmin()
    peak_date = eq.loc[:trough].idxmax()
    rec = eq.loc[trough:]
    recovered = rec[rec >= eq.loc[peak_date]]
    vol = ret.std() * math.sqrt(252)
    monthly = eq.resample("ME").last().pct_change().dropna()
    yearly = eq.resample("YE").last()
    yearly = pd.concat([eq.iloc[:1], yearly]).pct_change().dropna()
    out = {
        "start": eq.index[0].strftime("%Y-%m-%d"), "end": eq.index[-1].strftime("%Y-%m-%d"),
        "total_return": float(total), "cagr": float(cagr) if cagr is not None else None,
        "max_drawdown": float(dd.min()), "dd_peak": peak_date.strftime("%Y-%m-%d"),
        "dd_trough": trough.strftime("%Y-%m-%d"),
        "dd_recovered": recovered.index[0].strftime("%Y-%m-%d") if len(recovered) else None,
        "volatility": float(vol), "sharpe": float(ret.mean() * 252 / vol) if vol > 0 else None,
        "calmar": float(cagr / -dd.min()) if cagr is not None and dd.min() < 0 else None,
        "best_month": float(monthly.max()) if len(monthly) else None,
        "worst_month": float(monthly.min()) if len(monthly) else None,
        "pct_months_up": float((monthly > 0).mean()) if len(monthly) else None,
        "by_year": {str(k.year): float(v) for k, v in yearly.items()},
    }
    if exposure is not None:
        out["avg_exposure"] = float(exposure.mean())
    return out


def _weekly(s: pd.Series, base: float) -> list:
    w = s.resample("W-FRI").last().dropna()
    if len(w) and w.index[-1] < s.index[-1]:
        w.loc[s.index[-1]] = s.iloc[-1]
    return [[d.strftime("%Y-%m-%d"), round(float(v) / base * 100, 2)] for d, v in w.items()]


def run_bucket(cands: pd.DataFrame, closes: pd.DataFrame, calendar: pd.DatetimeIndex, capital_total: float,
               hcfg: dict, cfg: dict) -> dict:
    fb, fs = cfg["fees"]["buy"], cfg["fees"]["sell"]
    alloc = hcfg["allocation"]
    cash = capital_total * alloc
    maxp = int(hcfg["max_positions"])
    slot = min(float(hcfg["max_weight"]), 1.0 / maxp)
    rpt = float(cfg["risk_per_trade"])

    by_day = defaultdict(list)
    for r in cands.itertuples(index=False):
        by_day[r.entry_date].append(r)
    for k in by_day:
        by_day[k].sort(key=lambda r: -r.score)

    pos: dict[str, dict] = {}
    last_eq = cash
    eq_vals, expo_vals = [], []
    taken, skipped_full, skipped_cash = [], 0, 0
    cl = closes.to_dict("series")
    for t in calendar:
        for r in by_day.get(t, ()):
            if r.ticker in pos:
                continue
            if len(pos) >= maxp:
                skipped_full += 1
                continue
            risk_ps = max(r.entry_px - r.sl, 1e-9)
            shares = min(last_eq * slot / r.entry_px, rpt * (last_eq / alloc) / risk_ps)
            lots = int(shares // 100)
            unit = 100 * r.entry_px * (1 + fb)
            lots = min(lots, int(cash // unit))
            if lots <= 0:
                skipped_cash += 1
                continue
            cash -= lots * unit
            pos[r.ticker] = {"shares": lots * 100, "r": r, "tp1_done": False, "cost": lots * unit,
                             "proceeds": 0.0}
        for tk in list(pos):
            p, r = pos[tk], pos[tk]["r"]
            if not p["tp1_done"] and isinstance(r.tp1_date, pd.Timestamp) and r.tp1_date == t:
                half = (p["shares"] // 200) * 100
                cash += half * r.tp1_px * (1 - fs)
                p["proceeds"] += half * r.tp1_px * (1 - fs)
                p["shares"] -= half
                p["tp1_done"] = True
            if r.exit_date == t:
                cash += p["shares"] * r.exit_px * (1 - fs)
                p["proceeds"] += p["shares"] * r.exit_px * (1 - fs)
                taken.append({"ticker": tk, "entry": r.entry_date, "exit": t, "outcome": r.outcome,
                              "pnl": p["proceeds"] - p["cost"], "ret": p["proceeds"] / p["cost"] - 1})
                del pos[tk]
        mv = 0.0
        for tk, p in pos.items():
            px = cl[tk].get(t)
            if px is None or not np.isfinite(px):
                px = p["r"].entry_px
            mv += p["shares"] * px
        last_eq = cash + mv
        eq_vals.append(last_eq)
        expo_vals.append(mv / last_eq if last_eq > 0 else 0.0)
    eq = pd.Series(eq_vals, index=calendar)
    expo = pd.Series(expo_vals, index=calendar)
    tr = pd.DataFrame(taken)
    st = metrics(eq, expo)
    st.update({
        "trades": int(len(tr)), "skipped_full": skipped_full, "skipped_cash": skipped_cash,
        "win_rate": float((tr["ret"] > 0).mean()) if len(tr) else None,
        "avg_trade": float(tr["ret"].mean()) if len(tr) else None,
        "max_positions": maxp, "slot": slot,
    })
    return {"stats": st, "equity": eq, "exposure": expo}


def run(ind: dict[str, pd.DataFrame], cfg: dict, horizons=("short", "medium"), prep: dict | None = None) -> dict:
    prep = prep or bt.prepare(ind, horizons)
    closes = pd.DataFrame({t: d["Close"] for t, d in ind.items()}).sort_index()
    calendar = closes.index
    closes = closes.ffill()
    bench = pd.concat([d["BENCH"] for d in ind.values()], axis=1).bfill(axis=1).iloc[:, 0].reindex(calendar).ffill()

    cands = {h: bt.trades_for(prep, h, cfg["horizons"][h], cfg, detail=True) for h in horizons}
    cands = {h: c[c["outcome"] != "BATAL"].dropna(subset=["entry_date"]) for h, c in cands.items()}
    first = min((c["date"].min() for c in cands.values() if len(c)), default=None)
    if first is None:
        return {}
    cal = calendar[calendar >= first]
    capital = float(cfg["capital"])

    out = {"start": cal[0].strftime("%Y-%m-%d"), "end": cal[-1].strftime("%Y-%m-%d"), "capital": capital,
           "buckets": {}}
    total_eq = pd.Series(capital * (1 - sum(cfg["horizons"][h]["allocation"] for h in horizons)), index=cal)
    total_mv = pd.Series(0.0, index=cal)
    for h in horizons:
        hcfg = cfg["horizons"][h]
        res = run_bucket(cands[h], closes, cal, capital, hcfg, cfg)
        base = capital * hcfg["allocation"]
        out["buckets"][h] = {**res["stats"], "allocation": hcfg["allocation"],
                             "equity": _weekly(res["equity"], base)}
        total_eq = total_eq + res["equity"]
        total_mv = total_mv + res["equity"] * res["exposure"]
        log.info("Portofolio %s: return %.1f%%, max DD %.1f%%, %d transaksi", h,
                 100 * res["stats"].get("total_return", 0), 100 * res["stats"].get("max_drawdown", 0),
                 res["stats"]["trades"])
    out["combined"] = {**metrics(total_eq, total_mv / total_eq), "equity": _weekly(total_eq, capital)}
    dd = total_eq / total_eq.cummax() - 1
    out["combined"]["drawdown"] = [[d, round(v - 100, 2)] for d, v in _weekly(dd + 1, 1)]   # dalam persen
    b = bench.loc[cal].dropna()
    if len(b) > 20:
        out["ihsg"] = {**metrics(b), "equity": _weekly(b, float(b.iloc[0]))}
    split = cfg.get("backtest", {}).get("split_date")
    if split:
        cut = pd.Timestamp(split)
        out["split"] = {"in_sample": metrics(total_eq[total_eq.index < cut]),
                        "out_sample": metrics(total_eq[total_eq.index >= cut]),
                        "ihsg_out_sample": metrics(b[b.index >= cut]) if len(b) else {}}
    return out
