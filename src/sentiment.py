"""Indeks sentimen pasar dari angka (bukan berita): seberapa luas saham besar BEI ikut naik atau turun.

Dihitung per tanggal atas saham universe (>= Rp 5 T; saat backtest memakai universe per tanggal / kolom ELIG):

| Komponen | Cara hitung | Bobot |
|---|---|---|
| Breadth SMA50 | % saham dengan harga di atas SMA50 | 20 |
| Breadth SMA200 | % saham dengan harga di atas SMA200 | 15 |
| Naik vs turun | (naik − turun) / jumlah saham, rata-rata 10 hari | 15 |
| Puncak vs dasar baru | (tembus tertinggi 20 hari − tembus terendah 20 hari) / jumlah saham, rata-rata 10 hari | 15 |
| Arus volume | (naik ≥ 2% dgn volume ≥ 1,5× − turun ≤ −2% dgn volume ≥ 1,5×) / jumlah saham, rata-rata 10 hari | 15 |
| Tekanan ARB | % saham yang ditutup terkunci di batas ARB, rata-rata 5 hari (hanya bisa negatif) | 20 |

Setiap komponen diubah ke −1…+1, lalu dirata-rata berbobot dan dikali 100 → skor −100…+100.
Data transaksi asing (hanya tersedia dari laptop) ditampilkan terpisah dan tidak masuk skor karena tidak bisa di-backtest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .sim import arb_lock

WEIGHTS = {"breadth50": 20, "breadth200": 15, "adv_dec": 15, "high_low": 15, "vol_flow": 15, "arb": 20}
NAMES = {"breadth50": "Saham di atas SMA50", "breadth200": "Saham di atas SMA200",
         "adv_dec": "Naik vs turun (10 hari)", "high_low": "Tembus puncak vs dasar 20 hari (10 hari)",
         "vol_flow": "Naik vs turun bervolume besar (10 hari)", "arb": "Saham terkunci ARB (5 hari)"}
# skala: nilai mentah yang dianggap ekstrem (→ ±1)
SCALE = {"breadth50": 0.35, "breadth200": 0.35, "adv_dec": 0.25, "high_low": 0.08, "vol_flow": 0.05, "arb": 0.03}

MIN_STOCKS = 15            # di bawah ini skor tidak dihitung (terlalu sedikit saham)


def label(score) -> str | None:
    if score is None or not np.isfinite(score):
        return None
    if score <= -50:
        return "Sangat pesimis"
    if score <= -20:
        return "Pesimis"
    if score < 20:
        return "Netral"
    return "Optimis" if score < 50 else "Sangat optimis"


def compute(ind: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return DataFrame per tanggal: kolom mentah (raw_*), komponen −1…+1, `n` (jumlah saham) dan `SENT`."""
    if not ind:
        return pd.DataFrame(columns=["SENT"])
    cols = {}
    for t, d in ind.items():
        if len(d) < 2:
            continue
        c = d["Close"]
        lc, _ = arb_lock(d.index, d["Open"].to_numpy(float), d["High"].to_numpy(float), d["Low"].to_numpy(float),
                         c.to_numpy(float))
        uni = d["ELIG"].astype(bool) if "ELIG" in d else c.notna()
        valid = uni & c.notna()
        chg = d["CHG_1D"] if "CHG_1D" in d else c.pct_change()
        vr = d["VOL_RATIO"] if "VOL_RATIO" in d else pd.Series(np.nan, index=d.index)
        cols[t] = pd.DataFrame({
            "valid": valid,
            "a50": valid & d["SMA50"].notna(), "u50": valid & (c > d["SMA50"]),
            "a200": valid & d["SMA200"].notna(), "u200": valid & (c > d["SMA200"]),
            "adv": valid & (chg > 0), "dec": valid & (chg < 0),
            "hi": valid & d["HH20"].notna() & (c > d["HH20"]), "lo": valid & d["LL20"].notna() & (c < d["LL20"]),
            "vup": valid & (chg >= 0.02) & (vr >= 1.5), "vdn": valid & (chg <= -0.02) & (vr >= 1.5),
            "arb": valid & pd.Series(lc, index=d.index),
        })
    if not cols:
        return pd.DataFrame(columns=["SENT"])
    panel = pd.concat(cols, axis=1).sort_index()
    panel = panel.fillna(False).astype(bool)

    def tot(k: str) -> pd.Series:
        return panel.xs(k, axis=1, level=1).sum(axis=1).astype(float)

    n = tot("valid")
    nn = n.where(n >= MIN_STOCKS)
    raw = pd.DataFrame({
        "breadth50": tot("u50") / tot("a50").where(tot("a50") >= MIN_STOCKS),
        "breadth200": tot("u200") / tot("a200").where(tot("a200") >= MIN_STOCKS),
        "adv_dec": ((tot("adv") - tot("dec")) / nn).rolling(10, min_periods=5).mean(),
        "high_low": ((tot("hi") - tot("lo")) / nn).rolling(10, min_periods=5).mean(),
        "vol_flow": ((tot("vup") - tot("vdn")) / nn).rolling(10, min_periods=5).mean(),
        "arb": (tot("arb") / nn).rolling(5, min_periods=3).mean(),
    })
    comp = pd.DataFrame(index=raw.index)
    for k in WEIGHTS:
        x = raw[k] - 0.5 if k in ("breadth50", "breadth200") else raw[k]
        v = (x / SCALE[k]).clip(-1, 1)
        comp[k] = -(raw[k] / SCALE[k]).clip(0, 1) if k == "arb" else v
    w = pd.Series(WEIGHTS, dtype=float)
    have = comp.notna()
    num = (comp.fillna(0) * w).sum(axis=1)
    den = (have * w).sum(axis=1)
    sent = (100 * num / den).where(den >= 0.6 * w.sum())
    out = pd.concat([raw.add_prefix("raw_"), comp, n.rename("n")], axis=1)
    out["SENT"] = sent.round(1)
    return out


def attach(ind: dict[str, pd.DataFrame], sent: pd.DataFrame) -> None:
    """Tambahkan kolom SENT (skor sentimen pasar hari itu) ke setiap DataFrame indikator."""
    s = sent["SENT"] if "SENT" in sent else pd.Series(dtype=float)
    for d in ind.values():
        d["SENT"] = s.reindex(d.index).ffill() if len(s) else np.nan


def summary(sent: pd.DataFrame, flows: dict | None = None, history_days: int = 130) -> dict | None:
    """Ringkasan untuk dashboard/Telegram: skor terakhir, label, perubahan 5 hari, komponen, riwayat."""
    s = sent["SENT"].dropna() if "SENT" in sent else pd.Series(dtype=float)
    if s.empty:
        return None
    last_d = s.index[-1]
    row = sent.loc[last_d]
    score = float(s.iloc[-1])
    prev5 = float(s.iloc[-6]) if len(s) > 5 else None
    comps = []
    for k, wgt in WEIGHTS.items():
        rv = row.get(f"raw_{k}")
        comps.append({"key": k, "name": NAMES[k], "weight": wgt,
                      "raw": None if rv is None or pd.isna(rv) else float(rv),
                      "score": None if pd.isna(row.get(k)) else round(float(row[k]), 3)})
    score = float(round(score))
    out = {"date": last_d.strftime("%Y-%m-%d"), "score": score, "label": label(score),
           "chg_5d": None if prev5 is None else round(score - prev5, 1), "n": int(row.get("n") or 0),
           "components": comps,
           "history": [[d.strftime("%Y-%m-%d"), round(float(v), 1)] for d, v in s.iloc[-history_days:].items()],
           "pct_rank_1y": round(float((s.iloc[-250:] <= score).mean()), 3)}
    if flows:                                   # transaksi asing (tidak masuk skor)
        f5 = [v.get("foreign_5d") for v in flows.values() if v.get("foreign_5d") is not None]
        f20 = [v.get("foreign_20d") for v in flows.values() if v.get("foreign_20d") is not None]
        if f5:
            out["foreign"] = {"net_5d": float(np.nansum(f5)), "net_20d": float(np.nansum(f20)) if f20 else None,
                              "n": len(f5), "buy_5d": int(sum(x > 0 for x in f5))}
    return out
