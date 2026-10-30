"""Tuning parameter strategi dengan data asli (dijalankan di GitHub Actions).

Dua tahap per horizon (pendek & menengah):
  1. Syarat masuk : skor minimum x filter pasar (IHSG) x filter tren saham x cara masuk
  2. Cara keluar  : untuk 6 kombinasi terbaik tahap 1 -> lebar cut loss, target TP, trailing, time-stop

Anti-overfitting: kombinasi dipilih HANYA dari periode in-sample (sebelum backtest.split_date);
periode sesudahnya (out-of-sample) dipakai untuk menguji apakah keunggulannya bertahan.
Hasil: docs/data/tuning.json (dibaca untuk menetapkan config.yaml).

    python tune.py            # mode "exits": uji aturan keluar saat pasar berbalik (pakai config sekarang)
    python tune.py --full     # grid lengkap syarat masuk + cara keluar
    python tune.py --demo     # uji coba data sintetis
"""
from __future__ import annotations

import argparse
import copy
import itertools
import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from src import backtest as bt
from src import portsim
from src.utils import load_json
from src import data as D
from src.indicators import add_indicators
from src.universe import candidate_list, filter_universe
from src.utils import ROOT, dump_json, log

STAGE1 = {
    "min_score": [30, 45, 60],
    "market_filter": ["none", "ema20", "sma50", "sma200"],
    "trend_filter": ["none", "sma50", "sma200"],
    "entry_mode": ["open", "limit"],
}
STAGE2 = {
    "short": {"sl_atr": [1.5, 2.0, 2.5], "max_sl_pct": [0.07, 0.10], "rr": [[1.0, 2.0], [1.5, 2.5], [2.0, 3.0]],
              "trail_ma": [0, 9], "hold_max_days": [10, 15]},
    "medium": {"sl_atr": [2.5, 3.0, 3.5], "max_sl_pct": [0.12, 0.15], "rr": [[1.5, 3.0], [2.0, 3.5], [2.5, 4.0]],
               "trail_ma": [0, 20], "hold_max_days": [40, 60]},
}
MIN_N_IS = {"short": 120, "medium": 50}
TOP_STAGE1 = 6


def load_data(cfg: dict, demo: bool):
    if demo:
        prices, bench, shares, _ = D.demo_dataset()
    else:
        idx_df = D.fetch_idx_list()
        extra = D.discover_by_screener(cfg["universe"]["min_market_cap"]) if idx_df is None else []
        tickers, shares, _ = candidate_list(cfg, idx_df, extra)
        bpx = D.download_prices([cfg["data"]["benchmark"]], period=cfg["data"]["history_period"])
        bench = bpx[cfg["data"]["benchmark"]]["Close"]
        prices = D.download_prices(tickers, period=cfg["data"]["history_period"])
        missing = [t for t in prices if t not in shares]
        if missing:
            shares.update(D.get_shares(missing, cfg["data"]["shares_cache_days"]))
    as_of = max(df.index[-1] for df in prices.values())
    uni = filter_universe(prices, shares, cfg, as_of)
    ind = {t: add_indicators(prices[t], bench) for t in uni["ticker"]}
    return ind, len(uni)


def objective(st: dict, min_n: int) -> float:
    """t-stat rata-rata return in-sample (menghargai return tinggi DAN konsisten DAN cukup sampel)."""
    s = st.get("in_sample", {})
    n = s.get("n", 0)
    if n < min_n or s.get("avg_ret") is None:
        return -math.inf
    # perkiraan std dari win/loss tidak tersedia -> pakai PF & avg sebagai proxy stabil
    pf = s.get("profit_factor") or 0
    return s["avg_ret"] * math.sqrt(n) * (1 if pf >= 1 else 0.5)


def slim(st: dict) -> dict:
    keep = ("n", "win_rate", "avg_ret", "median_ret", "profit_factor", "avg_days", "fill_rate", "worst", "best")
    out = {k: st.get(k) for k in keep}
    for part in ("in_sample", "out_sample"):
        if part in st:
            out[part] = {k: st[part].get(k) for k in keep}
    if "by_year" in st:
        out["by_year"] = {y: {k: v.get(k) for k in ("n", "win_rate", "avg_ret", "profit_factor")}
                          for y, v in st["by_year"].items()}
    if "outcomes" in st:
        out["outcomes"] = st["outcomes"]
    return out


def run_variant(prep, h, hcfg, cfg):
    tr = bt.trades_for(prep, h, hcfg, cfg)
    return bt.full_stats(tr, cfg["backtest"]["split_date"])


EXIT_GRID = [{"market_exit": "none"}] + [
    {"market_exit": mx, "market_exit_ma": ma, "market_exit_confirm": cf}
    for mx in ("half", "all") for ma in ("ema20", "sma50") for cf in (1, 2)]


def pslim(st: dict) -> dict:
    keep = ("total_return", "cagr", "max_drawdown", "dd_peak", "dd_trough", "worst_month", "sharpe",
            "avg_exposure", "trades", "win_rate", "avg_trade", "by_year")
    return {k: st.get(k) for k in keep}


def run_exits(prep, ind, cfg, n_uni, demo, t0):
    """Uji aturan keluar-saat-pasar-berbalik untuk horizon pendek & menengah (parameter lain tetap)."""
    split = cfg["backtest"]["split_date"]
    out = {"generated_at": datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M"),
           "demo": demo, "universe": n_uni, "split_date": split, "horizons": {}}
    for h in ("short", "medium"):
        rows = []
        for v in EXIT_GRID:
            c2 = copy.deepcopy(cfg)
            c2["horizons"][h].update(v)
            st = run_variant(prep, h, c2["horizons"][h], c2)
            ps = portsim.run(ind, c2, prep=prep)
            b = ps.get("buckets", {}).get(h, {})
            cut = pd.Timestamp(split)
            eq = pd.Series({pd.Timestamp(d): val for d, val in b.get("equity", [])})
            rows.append({"params": v, "trades": slim(st), "portfolio": pslim(b),
                         "port_is": pslim(portsim.metrics(eq[eq.index < cut])) if len(eq) else {},
                         "port_oos": pslim(portsim.metrics(eq[eq.index >= cut])) if len(eq) else {}})
            log.info("exit %s %s: return %.1f%%, max DD %.1f%%", h, v,
                     100 * (b.get("total_return") or 0), 100 * (b.get("max_drawdown") or 0))
        out["horizons"][h] = rows
    out["seconds"] = round(time.time() - t0)
    path = ROOT / ("output/tuning_demo.json" if demo else "docs/data/tuning.json")
    prev = load_json(path, {}) or {}
    prev["exits"] = out                       # simpan berdampingan dengan hasil grid lengkap sebelumnya
    dump_json(prev, path)
    log.info("Tuning aturan keluar selesai dalam %d dtk -> %s", out["seconds"], path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--full", action="store_true", help="grid lengkap syarat masuk & cara keluar")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    t0 = time.time()
    ind, n_uni = load_data(cfg, a.demo)
    prep = bt.prepare(ind, ("short", "medium"))
    log.info("Data siap: %d saham, %.0f dtk", n_uni, time.time() - t0)
    if not a.full:
        run_exits(prep, ind, cfg, n_uni, a.demo, t0)
        return

    result = {"generated_at": datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M"),
              "demo": a.demo, "universe": n_uni, "split_date": cfg["backtest"]["split_date"], "horizons": {}}
    for h in ("short", "medium"):
        base = cfg["horizons"][h]
        out = {"baseline": {"params": {}, "stats": slim(run_variant(prep, h, base, cfg))}}

        # ---------- tahap 1: syarat masuk
        s1 = []
        keys = list(STAGE1)
        for combo in itertools.product(*STAGE1.values()):
            p = dict(zip(keys, combo))
            hc = {**copy.deepcopy(base), **p}
            st = run_variant(prep, h, hc, cfg)
            s1.append({"params": p, "obj": objective(st, MIN_N_IS[h]), "stats": slim(st)})
        s1.sort(key=lambda x: -x["obj"])
        log.info("%s tahap 1 selesai (%d varian), terbaik: %s", h, len(s1), s1[0]["params"])

        # ---------- tahap 2: cara keluar
        s2 = []
        keys2 = list(STAGE2[h])
        for top in [x for x in s1 if x["obj"] > -math.inf][:TOP_STAGE1]:
            for combo in itertools.product(*STAGE2[h].values()):
                p = {**top["params"], **dict(zip(keys2, combo))}
                hc = {**copy.deepcopy(base), **p}
                st = run_variant(prep, h, hc, cfg)
                s2.append({"params": p, "obj": objective(st, MIN_N_IS[h]), "stats": slim(st)})
        s2.sort(key=lambda x: -x["obj"])
        log.info("%s tahap 2 selesai (%d varian)", h, len(s2))

        for x in s1 + s2:
            x["obj"] = None if x["obj"] == -math.inf else round(x["obj"], 4)
        out["stage1_top"] = s1[:20]
        out["stage1_all"] = [{"params": x["params"], "obj": x["obj"],
                              "is": x["stats"].get("in_sample"), "oos": x["stats"].get("out_sample")} for x in s1]
        out["stage2_top"] = s2[:25]
        result["horizons"][h] = out

    result["seconds"] = round(time.time() - t0)
    path = ROOT / ("output/tuning_demo.json" if a.demo else "docs/data/tuning.json")
    prev = load_json(path, {}) or {}
    if "exits" in prev:
        result["exits"] = prev["exits"]
    dump_json(result, path)
    log.info("Selesai dalam %d dtk -> %s", result["seconds"], path)


if __name__ == "__main__":
    main()
