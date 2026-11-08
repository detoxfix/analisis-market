"""Mesin skor & sinyal untuk 3 horizon.

Setiap horizon terdiri dari beberapa komponen bernilai -1..+1 dengan bobot tertentu.
Skor = 100 x (jumlah bobot x komponen) / (jumlah bobot komponen yang datanya tersedia),
sehingga skor selalu di rentang -100..+100.

    skor >=  60  STRONG BUY        skor <= -60  STRONG SELL
    skor >=  30  BUY               skor <= -30  SELL
    lainnya      HOLD / NETRAL
Semua fungsi vektor (per tanggal) sehingga sama persis dipakai untuk sinyal harian & backtest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BUY_SIGNALS = ("STRONG BUY", "BUY")
SELL_SIGNALS = ("STRONG SELL", "SELL")


def _mask(values, *inputs) -> pd.Series:
    idx = inputs[0].index
    valid = np.ones(len(idx), dtype=bool)
    for s in inputs:
        valid &= s.notna().to_numpy()
    return pd.Series(np.where(valid, values, np.nan), index=idx, dtype=float)


def _bin(cond: pd.Series, *inputs) -> pd.Series:
    return _mask(np.where(cond, 1.0, -1.0), *inputs)


# =============================================================== JANGKA PENDEK (swing 3-10 hari)
SHORT_W = {"trend_ema20": 20, "ema_cross": 15, "macd_mom": 15, "rsi_zone": 15,
           "volume": 15, "breakout": 10, "market": 10}


def short_components(d: pd.DataFrame) -> pd.DataFrame:
    c = d["Close"]
    h, hp = d["MACD_hist"], d["MACD_hist"].shift(1)
    r = d["RSI14"]
    up_day = c > c.shift(1)
    vr = d["VOL_RATIO"]
    comp = {
        "trend_ema20": _bin(c > d["EMA20"], c, d["EMA20"]),
        "ema_cross": _bin(d["EMA9"] > d["EMA20"], d["EMA9"], d["EMA20"]),
        "macd_mom": _mask(np.select([(h > 0) & (h >= hp), h > 0, (h <= 0) & (h > hp)], [1.0, 0.3, -0.3], -1.0),
                          h, hp),
        "rsi_zone": _mask(np.select([r < 30, r < 45, r < 50, r <= 68, r <= 75], [0.2, -0.6, 0.0, 1.0, 0.3], -0.7), r),
        "volume": _mask(np.select([(vr >= 1.5) & up_day, (vr >= 1.5) & ~up_day], [1.0, -1.0], 0.0), vr),
        "breakout": _mask(np.select([c > d["HH20"], c < d["LL20"]], [1.0, -1.0], 0.0), d["HH20"], d["LL20"]),
        "market": _mask(np.where(d["BENCH_UP"] > 0.5, 1.0, -1.0), d["BENCH_UP"]),
    }
    return pd.DataFrame(comp)


# =============================================================== JANGKA MENENGAH (1-3 bulan)
MEDIUM_W = {"above_sma50": 15, "ma_structure": 15, "adx_trend": 15, "momentum_60": 15,
            "rel_strength": 15, "rsi_regime": 10, "macd_trend": 15}


def medium_components(d: pd.DataFrame) -> pd.DataFrame:
    c = d["Close"]
    a = np.where(d["SMA50"] > d["SMA100"], 1.0, -1.0)
    b = np.where(d["SMA50_slope"] > 0, 1.0, -1.0)
    adx_, pdi, mdi = d["ADX14"], d["PDI"], d["MDI"]
    r = d["RSI14"]
    m, ms = d["MACD"], d["MACD_signal"]
    comp = {
        "above_sma50": _bin(c > d["SMA50"], c, d["SMA50"]),
        "ma_structure": _mask((a + b) / 2, d["SMA100"], d["SMA50_slope"]),
        "adx_trend": _mask(np.select([(adx_ >= 20) & (pdi > mdi), (adx_ >= 20) & (pdi <= mdi)], [1.0, -1.0], 0.0),
                           adx_, pdi, mdi),
        "momentum_60": _mask(np.clip(d["RET_60"] / 0.15, -1, 1), d["RET_60"]),
        "rel_strength": _mask(np.clip(d["RS_60"] / 0.10, -1, 1), d["RS_60"]),
        "rsi_regime": _mask(np.select([r > 75, r >= 50, r < 40], [-0.5, 1.0, -1.0], 0.0), r),
        "macd_trend": _mask(np.select([(m > ms) & (m > 0), (m < ms) & (m < 0)], [1.0, -1.0], 0.0), m, ms),
    }
    return pd.DataFrame(comp)


# =============================================================== JANGKA PANJANG (6-24 bulan)
LONG_W = {"above_sma200": 15, "sma200_slope": 10, "momentum_12_1": 15,
          "roe": 15, "pe_rel": 10, "pb_rel": 10, "der": 10, "dividend": 5, "growth": 10}


def _fund_scores(f: dict, med: dict) -> dict:
    """Skor fundamental (skalar). None = data tidak tersedia (tidak ikut dihitung)."""
    out = {}
    roe = f.get("roe")
    out["roe"] = None if roe is None else (1.0 if roe >= 0.15 else 0.3 if roe >= 0.10 else -0.3 if roe >= 0.05 else -1.0)

    def rel(v, m):
        if v is None:
            return None
        if v <= 0:
            return -1.0
        if not m:
            return None
        x = v / m
        return 1.0 if x <= 0.8 else 0.2 if x <= 1.2 else -0.4 if x <= 1.6 else -0.8

    out["pe_rel"] = rel(f.get("pe"), med.get("pe"))
    out["pb_rel"] = rel(f.get("pb"), med.get("pb"))
    der = f.get("der")
    if f.get("sector") == "Financial Services" or der is None:
        out["der"] = None                       # DER tidak relevan untuk bank / data kosong
    else:
        out["der"] = 1.0 if der < 0.5 else 0.3 if der < 1.0 else -0.3 if der < 2.0 else -1.0
    dy = f.get("div_yield")
    out["dividend"] = None if dy is None else (1.0 if dy >= 0.05 else 0.6 if dy >= 0.03 else 0.2 if dy >= 0.01 else -0.2)
    g = f.get("eps_growth")
    out["growth"] = None if g is None else (1.0 if g >= 0.15 else 0.3 if g >= 0 else -0.7)
    return out


def long_components(d: pd.DataFrame, fund: dict | None, sector_med: dict | None) -> pd.DataFrame:
    c = d["Close"]
    comp = {
        "above_sma200": _bin(c > d["SMA200"], c, d["SMA200"]),
        "sma200_slope": _mask(np.clip(d["SMA200_slope"] / 0.03, -1, 1), d["SMA200_slope"]),
        "momentum_12_1": _mask(np.clip(d["MOM_12_1"] / 0.30, -1, 1), d["MOM_12_1"]),
    }
    fs = _fund_scores(fund or {}, sector_med or {})
    for k, v in fs.items():
        comp[k] = pd.Series(np.nan if v is None else v, index=d.index, dtype=float)
    return pd.DataFrame(comp)


# =============================================================== komposisi
def compose(comp: pd.DataFrame, weights: dict, min_coverage: float = 0.6) -> tuple[pd.Series, pd.Series]:
    w = pd.Series(weights, dtype=float)[comp.columns]
    avail = comp.notna()
    num = (comp.fillna(0.0) * w).sum(axis=1)
    den = (avail * w).sum(axis=1)
    coverage = den / w.sum()
    score = (100 * num / den.replace(0, np.nan)).where(coverage >= min_coverage)
    return score.round(1), coverage


def label(score: float | None, th: dict) -> str:
    if score is None or not np.isfinite(score):
        return "N/A"
    if score >= th["strong_buy"]:
        return "STRONG BUY"
    if score >= th["buy"]:
        return "BUY"
    if score <= th["strong_sell"]:
        return "STRONG SELL"
    if score <= th["sell"]:
        return "SELL"
    return "HOLD"


# =============================================================== penjelasan (alasan sinyal)
def _f(x, fmt="{:.0f}"):
    try:
        return fmt.format(x)
    except (TypeError, ValueError):
        return "-"


TEXT = {
    "trend_ema20": (lambda r, f: "Harga di atas EMA20 (tren pendek naik)",
                    lambda r, f: "Harga di bawah EMA20 (tren pendek turun)"),
    "ema_cross": (lambda r, f: "EMA9 di atas EMA20 (golden cross pendek)",
                  lambda r, f: "EMA9 di bawah EMA20 (dead cross pendek)"),
    "macd_mom": (lambda r, f: "Histogram MACD positif & menguat",
                 lambda r, f: "Histogram MACD negatif / melemah"),
    "rsi_zone": (lambda r, f: f"RSI {_f(r['RSI14'])} di zona momentum sehat",
                 lambda r, f: f"RSI {_f(r['RSI14'])} kurang mendukung (lemah/jenuh beli)"),
    "volume": (lambda r, f: f"Volume {_f(r['VOL_RATIO'], '{:.1f}')}x rata-rata pada hari naik (akumulasi)",
               lambda r, f: f"Volume {_f(r['VOL_RATIO'], '{:.1f}')}x rata-rata pada hari turun (distribusi)"),
    "breakout": (lambda r, f: "Breakout di atas resistance 20 hari",
                 lambda r, f: "Breakdown di bawah support 20 hari"),
    "market": (lambda r, f: "IHSG di atas EMA20 (pasar mendukung)",
               lambda r, f: "IHSG di bawah EMA20 (pasar lemah)"),
    "above_sma50": (lambda r, f: "Harga di atas SMA50", lambda r, f: "Harga di bawah SMA50"),
    "ma_structure": (lambda r, f: "SMA50 > SMA100 & SMA50 menanjak (uptrend menengah)",
                     lambda r, f: "Struktur MA menengah melemah"),
    "adx_trend": (lambda r, f: f"ADX {_f(r['ADX14'])}: tren naik kuat",
                  lambda r, f: f"ADX {_f(r['ADX14'])}: tren turun kuat"),
    "momentum_60": (lambda r, f: f"Momentum 3 bulan {_f(100 * r['RET_60'], '{:+.1f}')}%",
                    lambda r, f: f"Momentum 3 bulan {_f(100 * r['RET_60'], '{:+.1f}')}%"),
    "rel_strength": (lambda r, f: f"Outperform IHSG {_f(100 * r['RS_60'], '{:+.1f}')}% (3 bulan)",
                     lambda r, f: f"Underperform IHSG {_f(100 * r['RS_60'], '{:+.1f}')}% (3 bulan)"),
    "rsi_regime": (lambda r, f: f"RSI {_f(r['RSI14'])} di rezim bullish",
                   lambda r, f: f"RSI {_f(r['RSI14'])} di rezim bearish / jenuh beli"),
    "macd_trend": (lambda r, f: "MACD di atas sinyal & di atas nol",
                   lambda r, f: "MACD di bawah sinyal & di bawah nol"),
    "above_sma200": (lambda r, f: "Harga di atas SMA200 (uptrend primer)",
                     lambda r, f: "Harga di bawah SMA200 (downtrend primer)"),
    "sma200_slope": (lambda r, f: "SMA200 menanjak", lambda r, f: "SMA200 menurun"),
    "momentum_12_1": (lambda r, f: f"Momentum 12 bulan {_f(100 * r['MOM_12_1'], '{:+.0f}')}%",
                      lambda r, f: f"Momentum 12 bulan {_f(100 * r['MOM_12_1'], '{:+.0f}')}%"),
    "roe": (lambda r, f: f"ROE {_f(100 * (f.get('roe') or 0), '{:.1f}')}% (profitabilitas tinggi)",
            lambda r, f: f"ROE {_f(100 * (f.get('roe') or 0), '{:.1f}')}% (profitabilitas rendah)"),
    "pe_rel": (lambda r, f: f"PER {_f(f.get('pe'), '{:.1f}')}x lebih murah dari median sektor",
               lambda r, f: f"PER {_f(f.get('pe'), '{:.1f}')}x mahal / laba negatif"),
    "pb_rel": (lambda r, f: f"PBV {_f(f.get('pb'), '{:.2f}')}x di bawah median sektor",
               lambda r, f: f"PBV {_f(f.get('pb'), '{:.2f}')}x di atas median sektor"),
    "der": (lambda r, f: f"DER {_f(f.get('der'), '{:.2f}')}x (utang rendah)",
            lambda r, f: f"DER {_f(f.get('der'), '{:.2f}')}x (utang tinggi)"),
    "dividend": (lambda r, f: f"Dividend yield {_f(100 * (f.get('div_yield') or 0), '{:.1f}')}%",
                 lambda r, f: "Dividen kecil / tidak ada"),
    "growth": (lambda r, f: f"Laba tumbuh {_f(100 * (f.get('eps_growth') or 0), '{:+.0f}')}% YoY",
               lambda r, f: f"Laba turun {_f(100 * (f.get('eps_growth') or 0), '{:+.0f}')}% YoY"),
}


def explain(comp_row: pd.Series, weights: dict, ind_row: pd.Series, fund: dict | None,
            bullish: bool, n_main: int = 3, n_risk: int = 2) -> tuple[list[str], list[str]]:
    contrib = {k: weights[k] * v for k, v in comp_row.items() if pd.notna(v) and v != 0}
    pos = sorted([k for k, v in contrib.items() if v > 0], key=lambda k: -contrib[k])
    neg = sorted([k for k, v in contrib.items() if v < 0], key=lambda k: contrib[k])
    f = fund or {}

    def txt(k, positive):
        try:
            return TEXT[k][0 if positive else 1](ind_row, f)
        except Exception:  # noqa: BLE001
            return k

    if bullish:
        return [txt(k, True) for k in pos[:n_main]], [txt(k, False) for k in neg[:n_risk]]
    return [txt(k, False) for k in neg[:n_main]], [txt(k, True) for k in pos[:n_risk]]


MKT_TEXT = {"ema20": "EMA20", "sma50": "SMA50", "sma200": "SMA200"}


def entry_mask(d: pd.DataFrame, score: pd.Series, hcfg: dict, th: dict) -> tuple[pd.Series, pd.Series]:
    """Syarat tambahan sebelum sinyal BUY boleh dieksekusi.
    Return (boleh_masuk, alasan_tertahan) per tanggal."""
    min_score = hcfg.get("min_score", th["buy"])
    ok = score >= min_score
    why = pd.Series("", index=d.index, dtype=object)
    mf = hcfg.get("market_filter", "none") or "none"
    if mf != "none":
        mkt = d[f"MKT_{mf}"]
        bad = ~(mkt > 0.5)
        why = why.mask(bad & ok, f"IHSG di bawah {MKT_TEXT[mf]} (filter pasar)")
        ok &= ~bad
    tf = hcfg.get("trend_filter", "none") or "none"
    if tf != "none":
        col = {"sma50": "SMA50", "sma200": "SMA200"}[tf]
        bad = ~(d["Close"] > d[col])
        why = why.mask(bad & ok & (why == ""), f"Harga di bawah {col} (filter tren)")
        ok &= ~bad
    sm = hcfg.get("sentiment_min")
    if sm is not None and "SENT" in d:
        sent = d["SENT"]
        bad = ~(sent >= float(sm))                   # NaN (belum dihitung) -> tertahan
        txt = sent.map(lambda v: f"{v:+.0f}" if pd.notna(v) else "?")
        why = why.mask(bad & ok & (why == ""), "Sentimen pasar " + txt + f" di bawah batas {float(sm):+.0f}")
        ok &= ~bad
    low = score < min_score
    why = why.mask(low & (score >= th["buy"]) & (why == ""), f"Skor di bawah minimum masuk {min_score:g}")
    return ok.fillna(False), why


HORIZON_FUNCS = {
    "short": (short_components, SHORT_W),
    "medium": (medium_components, MEDIUM_W),
    "long": (None, LONG_W),
}
