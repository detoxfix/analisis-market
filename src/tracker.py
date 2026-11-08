"""Track record: setiap rekomendasi BUY yang masuk portofolio dicatat lalu dievaluasi tiap hari
(kena TP / SL / time-stop) memakai harga riil berikutnya. Ini cara jujur mengukur akurasi sinyal.

Kolom `strategy` menyimpan sidik jari versi strategi (lihat versions.py) saat rekomendasi dibuat;
baris lama tanpa label diberi "v0"."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .sim import simulate
from .versions import LEGACY, label_of
from .utils import ROOT, log

PATH = ROOT / "docs" / "data" / "recommendations.csv"
COLS = ["id", "date", "ticker", "code", "horizon", "signal", "score", "entry", "entry_low", "entry_high",
        "tp1", "tp2", "sl", "max_hold_days", "status", "outcome", "entry_date", "entry_px",
        "exit_date", "exit_px", "ret", "days", "tp1_hit", "entry_mode", "limit_days", "trail_ma",
        "market_exit", "market_exit_ma", "market_exit_confirm", "strategy"]


def _load() -> pd.DataFrame:
    if PATH.exists():
        df = pd.read_csv(PATH, dtype={"id": str})
        for c in COLS:
            if c not in df.columns:
                df[c] = np.nan
        df["strategy"] = df["strategy"].astype("object").where(df["strategy"].notna(), LEGACY)
        return df[COLS]
    return pd.DataFrame(columns=COLS)


def update(prices: dict[str, pd.DataFrame], new_recs: list[dict], fees: dict, as_of: pd.Timestamp,
           demo: bool = False, bench: pd.Series | None = None, exec_cfg: dict | None = None,
           versions: dict | None = None) -> dict:
    df = _load() if not demo else pd.DataFrame(columns=COLS)
    df = df.astype({"status": "object", "outcome": "object", "entry_date": "object",
                    "exit_date": "object", "tp1_hit": "object", "market_exit": "object", "market_exit_ma": "object",
                    "entry_mode": "object", "strategy": "object"})

    # 1) evaluasi rekomendasi yang masih terbuka
    for i in df.index[df["status"] == "OPEN"]:
        row = df.loc[i]
        p = prices.get(row["ticker"])
        if p is None:
            continue
        pos = p.index.get_indexer([pd.Timestamp(row["date"])], method="pad")[0]
        if pos < 0:
            continue
        res = simulate(p, int(pos), row.to_dict(), fees, bench, exec_cfg)
        if res["outcome"] == "MENUNGGU":
            continue
        open_ = res["outcome"] == "OPEN" or res["outcome"].endswith("OPEN")
        df.loc[i, "status"] = "OPEN" if open_ else "CLOSED"
        df.loc[i, "outcome"] = res["outcome"]
        for k in ("entry_px", "exit_px", "ret", "days", "tp1_hit"):
            df.loc[i, k] = res[k]
        for k in ("entry_date", "exit_date"):
            df.loc[i, k] = res[k].strftime("%Y-%m-%d") if res[k] is not None else None

    # 2) tambahkan rekomendasi baru (hindari duplikat posisi terbuka)
    open_keys = set(zip(df.loc[df["status"] == "OPEN", "ticker"], df.loc[df["status"] == "OPEN", "horizon"]))
    d = as_of.strftime("%Y-%m-%d")
    add = []
    for r in new_recs:
        key = (r["ticker"], r["horizon"])
        if key in open_keys:
            continue
        add.append({"id": f"{d}-{r['code']}-{r['horizon']}", "date": d, "ticker": r["ticker"], "code": r["code"],
                    "horizon": r["horizon"], "signal": r["signal"], "score": r["score"],
                    "entry": r["entry"], "entry_low": r["entry_low"], "entry_high": r["entry_high"],
                    "tp1": r["tp1"], "tp2": r["tp2"], "sl": r["sl"], "max_hold_days": r["max_hold_days"],
                    "entry_mode": r.get("entry_mode", "open"), "limit_days": r.get("limit_days", 3),
                    "trail_ma": r.get("trail_ma", 0), "market_exit": r.get("market_exit", "none"),
                    "market_exit_ma": r.get("market_exit_ma", "sma50"),
                    "market_exit_confirm": r.get("market_exit_confirm", 1),
                    "strategy": ((versions or {}).get(r["horizon"]) or {}).get("id", LEGACY),
                    "status": "OPEN", "outcome": "MENUNGGU"})
    if add:
        df = pd.concat([df, pd.DataFrame(add)], ignore_index=True) if len(df) else pd.DataFrame(add, columns=COLS)
        df = df.drop_duplicates("id", keep="first")
    if not demo:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(PATH, index=False)
    log.info("Track record: %d rekomendasi (%d terbuka, %d baru)", len(df), int((df["status"] == "OPEN").sum()), len(add))
    return summarize(df, versions)


def _stats(rets: pd.Series) -> dict:
    rets = rets.astype(float)
    if rets.empty:
        return {"n": 0}
    gains, losses = rets[rets > 0].sum(), -rets[rets < 0].sum()
    return {"n": int(len(rets)), "win_rate": float((rets > 0).mean()), "avg_ret": float(rets.mean()),
            "median_ret": float(rets.median()), "best": float(rets.max()), "worst": float(rets.min()),
            "profit_factor": float(gains / losses) if losses > 0 else None}


def summarize(df: pd.DataFrame, versions: dict | None = None) -> dict:
    df = df.copy()
    if "strategy" not in df:
        df["strategy"] = LEGACY
    df["strategy"] = df["strategy"].astype("object").where(df["strategy"].notna(), LEGACY)
    df["version"] = [label_of(versions, h, s) for h, s in zip(df["horizon"], df["strategy"])]
    closed = df[(df["status"] == "CLOSED") & (df["outcome"] != "BATAL")]
    by_h = {h: _stats(closed.loc[closed["horizon"] == h, "ret"]) for h in ("short", "medium", "long")}
    recent = closed.sort_values("exit_date", ascending=False).head(30)
    opened = df[df["status"] == "OPEN"].sort_values("date", ascending=False)
    keep = ["date", "code", "horizon", "signal", "entry", "tp1", "tp2", "sl", "outcome", "entry_px",
            "exit_px", "ret", "days", "exit_date", "strategy", "version"]
    srt = closed.sort_values(["exit_date", "date"])
    closed_rets = {h: [[str(d), float(r), str(s)] for d, r, s in zip(g["exit_date"], g["ret"], g["strategy"])]
                   for h, g in srt.groupby("horizon")}
    by_version = {}                     # hasil per versi strategi, versi terbaru di atas
    for h in ("short", "medium", "long"):
        rows = []
        for sid, g in df[df["horizon"] == h].groupby("strategy"):
            c = closed[(closed["horizon"] == h) & (closed["strategy"] == sid)]
            cur = ((versions or {}).get(h) or {}).get("id") == sid
            rows.append({"strategy": sid, "version": label_of(versions, h, sid), "current": cur,
                         "first": str(g["date"].min()), "n_recs": int(len(g)),
                         "n_open": int((g["status"] == "OPEN").sum()), **_stats(c["ret"])})
        rows.sort(key=lambda r: r["first"], reverse=True)
        by_version[h] = sorted(rows, key=lambda r: not r["current"])     # versi aktif di atas
    current = {h: {k: v for k, v in (versions or {}).get(h, {}).items()} for h in ("short", "medium", "long")
               if (versions or {}).get(h)}
    return {"by_horizon": by_h, "all": _stats(closed["ret"]), "closed_rets": closed_rets,
            "by_version": by_version, "versions": current,
            "cancelled": int((df["outcome"] == "BATAL").sum()),
            "open": opened[keep].to_dict("records"), "recent_closed": recent[keep].to_dict("records")}
