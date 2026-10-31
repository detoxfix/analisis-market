"""Tuning parameter strategi dengan data asli (dijalankan di GitHub Actions).

Dua tahap per horizon (pendek & menengah):
  1. Syarat masuk : skor minimum x filter pasar (IHSG) x filter tren saham x cara masuk
  2. Cara keluar  : untuk 6 kombinasi terbaik tahap 1 -> lebar cut loss, target TP, trailing, time-stop

Anti-overfitting: kombinasi dipilih HANYA dari periode in-sample (sebelum backtest.split_date);
periode sesudahnya (out-of-sample) dipakai untuk menguji apakah keunggulannya bertahan.
Hasil: docs/data/tuning.json (dibaca untuk menetapkan config.yaml).

    python tune.py            # mode "exits": uji aturan keluar saat pasar berbalik (pakai config sekarang)
    python tune.py --full     # grid lengkap syarat masuk + cara keluar
    python tune.py --propose  # usulan parameter bulanan (walk-forward + uji 6 bulan terakhir), TIDAK diterapkan
    python tune.py --realism  # bandingkan backtest lama vs realistis (universe per tanggal, slippage, ARB)
    python tune.py --demo     # uji coba data sintetis
"""
from __future__ import annotations

import argparse
import copy
import os
import itertools
import math
import time

import pandas as pd
import yaml

from src import backtest as bt
from src import portsim
from src.utils import load_json
from src import data as D
from src.indicators import add_indicators
from src.universe import backtest_set, candidate_list, filter_universe
from src.utils import ROOT, dump_json, log, now_wib

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
    if cfg.get("backtest", {}).get("point_in_time", True):
        ind = backtest_set(prices, shares, cfg, list(ind),
                           lambda t: ind[t] if t in ind else add_indicators(prices[t], bench))
    return ind, len(uni)


REALISM = [
    ("Cara lama (universe hari ini, eksekusi ideal)", {"point_in_time": False, "execution": {"enabled": False}}),
    ("+ universe per tanggal", {"point_in_time": True, "execution": {"enabled": False}}),
    ("+ slippage cut loss & antrean limit", {"point_in_time": True,
                                           "execution": {"enabled": True, "slippage_ticks": 1,
                                                         "limit_through": True, "arb": False}}),
    ("+ ARB (realistis, dipakai dashboard)", {"point_in_time": True,
                                              "execution": {"enabled": True, "slippage_ticks": 1,
                                                            "limit_through": True, "arb": True}}),
    ("Uji ketahanan: + 1 tick di setiap lelang", {"point_in_time": True,
                                                  "execution": {"enabled": True, "slippage_ticks": 1,
                                                                "auction_slippage_ticks": 1,
                                                                "limit_through": True, "arb": True}}),
]


def run_realism(prep, ind, cfg, n_uni, demo, t0):
    """Seberapa besar hasil backtest lama terlalu optimistis: tambahkan realisme selangkah demi selangkah."""
    split = cfg["backtest"]["split_date"]
    cut = pd.Timestamp(split)
    out = {"generated_at": now_wib().strftime("%Y-%m-%d %H:%M"), "demo": demo, "universe_today": n_uni,
           "universe_backtest": len(ind), "split_date": split, "steps": []}
    for name, b in REALISM:
        c2 = copy.deepcopy(cfg)
        c2["backtest"].update(copy.deepcopy(b))
        row = {"name": name, "settings": b, "trades": {}, "portfolio": {}}
        for h in ("short", "medium"):
            row["trades"][h] = slim(run_variant(prep, h, c2["horizons"][h], c2))
        ps = portsim.run(ind, c2, prep=prep)
        for h, bk in ps.get("buckets", {}).items():
            row["portfolio"][h] = pslim(bk)
        comb = ps.get("combined", {})
        row["portfolio"]["combined"] = pslim(comb)
        eq = pd.Series({pd.Timestamp(d): v for d, v in comb.get("equity", [])})
        if len(eq):
            row["portfolio"]["combined_oos"] = pslim(portsim.metrics(eq[eq.index >= cut]))
        out["steps"].append(row)
        log.info("%s: pendek %s trx avg %.2f%% | menengah %s trx avg %.2f%% | gabungan return %.1f%% DD %.1f%%",
                 name, row["trades"]["short"].get("n"), 100 * (row["trades"]["short"].get("avg_ret") or 0),
                 row["trades"]["medium"].get("n"), 100 * (row["trades"]["medium"].get("avg_ret") or 0),
                 100 * (comb.get("total_return") or 0), 100 * (comb.get("max_drawdown") or 0))
    out["seconds"] = round(time.time() - t0)
    path = ROOT / ("output/tuning_demo.json" if demo else "docs/data/tuning.json")
    prev = load_json(path, {}) or {}
    prev["realism"] = out
    dump_json(prev, path)
    log.info("Perbandingan realisme selesai dalam %d dtk -> %s", out["seconds"], path)


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
    out = {"generated_at": now_wib().strftime("%Y-%m-%d %H:%M"),
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


# ------------------------------------------------------------------ usulan parameter bulanan
# Satu parameter diubah per usulan (mudah dipahami & tidak berlebihan menyesuaikan diri dengan masa lalu).
PROPOSE_GRID = {
    "short": {"min_score": [45, 60, 75], "market_filter": ["none", "ema20", "sma50"],
              "trend_filter": ["none", "sma50", "sma200"], "entry_mode": ["open", "limit"],
              "sl_atr": [1.5, 2.0, 2.5, 3.0], "rr": [[1.5, 2.5], [2.0, 3.0], [2.5, 4.0]],
              "hold_max_days": [10, 15, 20], "market_exit": ["none", "half", "all"]},
    "medium": {"min_score": [45, 60, 75], "market_filter": ["none", "ema20", "sma50", "sma200"],
               "trend_filter": ["none", "sma50", "sma200"], "entry_mode": ["open", "limit"],
               "sl_atr": [2.5, 3.0, 3.5, 4.0], "rr": [[2.0, 3.5], [2.5, 4.0], [3.0, 5.0]],
               "hold_max_days": [30, 40, 60], "market_exit": ["none", "half", "all"]},
}
BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
         "November", "Desember"]
PROPOSE_RULES = {"holdout_months": 6, "block_months": 6, "min_n_select": {"short": 60, "medium": 30},
                 "min_n_holdout": 10, "min_gain": 0.0015, "min_blocks_won": 0.6, "max_dd_worse": 0.03}


def _seg(tr: pd.DataFrame, a=None, b=None) -> pd.DataFrame:
    d = pd.to_datetime(tr["date"])
    m = pd.Series(True, index=tr.index)
    if a is not None:
        m &= d >= a
    if b is not None:
        m &= d < b
    return tr[m & (tr["outcome"] != "BATAL")]


def _avg(tr: pd.DataFrame):
    return float(tr["ret"].mean()) if len(tr) else None


def propose_horizon(prep, ind, cfg, h, hold_start, rules) -> dict:
    base = cfg["horizons"][h]
    cur_tr = bt.trades_for(prep, h, base, cfg)
    if cur_tr.empty:
        return {"status": "data kurang", "reason": "Belum ada transaksi backtest untuk horizon ini."}
    first = pd.to_datetime(cur_tr["date"]).min()
    edges = list(pd.date_range(first, hold_start, freq=f"{rules['block_months']}MS")) + [hold_start]
    blocks = [(a, b) for a, b in zip(edges[:-1], edges[1:]) if b > a]
    sel_cur = _seg(cur_tr, None, hold_start)
    min_n = rules["min_n_select"][h]
    if len(sel_cur) < min_n:
        return {"status": "data kurang", "reason": f"Transaksi backtest sebelum {hold_start:%d-%m-%Y} baru "
                                                    f"{len(sel_cur)} (minimal {min_n})."}
    cur_avg = _avg(sel_cur)
    tried, cands = 0, []
    for param, values in PROPOSE_GRID[h].items():
        for v in values:
            if base.get(param) == v:
                continue
            tried += 1
            hc = {**copy.deepcopy(base), param: v}
            tr = bt.trades_for(prep, h, hc, cfg)
            sel = _seg(tr, None, hold_start)
            if len(sel) < max(min_n, 0.6 * len(sel_cur)):
                continue
            gain = _avg(sel) - cur_avg
            if gain < rules["min_gain"]:
                continue
            won = n_bl = 0
            for a, b in blocks:
                x, y = _seg(tr, a, b), _seg(cur_tr, a, b)
                if len(x) >= 5 and len(y) >= 5:
                    n_bl += 1
                    won += _avg(x) > _avg(y)
            if not n_bl or won / n_bl < rules["min_blocks_won"]:
                continue
            obj = _avg(sel) * math.sqrt(len(sel))
            cands.append({"param": param, "new": v, "tr": tr, "sel_avg": _avg(sel), "sel_n": len(sel),
                          "gain": gain, "blocks": [won, n_bl], "obj": obj})
    out = {"tried": tried, "passed_selection": len(cands), "select_cur": cur_avg, "select_n": len(sel_cur),
           "holdout_from": hold_start.strftime("%Y-%m-%d")}
    if not cands:
        out.update(status="tetap", reason=f"Dari {tried} perubahan yang diuji, tidak ada yang konsisten lebih baik "
                                          "di semua periode. Parameter sekarang tetap dipakai.")
        return out
    best = max(cands, key=lambda c: c["obj"])           # dipilih TANPA melihat 6 bulan terakhir
    ho_new, ho_cur = _seg(best["tr"], hold_start), _seg(cur_tr, hold_start)
    c2 = copy.deepcopy(cfg)
    c2["horizons"][h][best["param"]] = best["new"]
    p_cur = portsim.run(ind, cfg, horizons=(h,), prep=prep).get("buckets", {}).get(h, {})
    p_new = portsim.run(ind, c2, horizons=(h,), prep=prep).get("buckets", {}).get(h, {})
    ev = {"select_cur": cur_avg, "select_new": best["sel_avg"], "select_n_new": best["sel_n"],
          "blocks_won": best["blocks"], "holdout_cur": _avg(ho_cur), "holdout_new": _avg(ho_new),
          "holdout_n_cur": len(ho_cur), "holdout_n_new": len(ho_new),
          "port_ret_cur": p_cur.get("total_return"), "port_ret_new": p_new.get("total_return"),
          "port_dd_cur": p_cur.get("max_drawdown"), "port_dd_new": p_new.get("max_drawdown")}
    out["evidence"] = ev
    out["change"] = {"param": best["param"], "old": base.get(best["param"]), "new": best["new"]}
    fails = []
    if len(ho_new) < rules["min_n_holdout"]:
        fails.append(f"transaksi 6 bulan terakhir hanya {len(ho_new)}")
    elif ev["holdout_cur"] is not None and ev["holdout_new"] < ev["holdout_cur"]:
        fails.append("kalah di 6 bulan terakhir")
    if (ev["port_dd_new"] or 0) < (ev["port_dd_cur"] or 0) - rules["max_dd_worse"]:
        fails.append("drawdown portofolio lebih dalam")
    if (ev["port_ret_new"] or 0) < (ev["port_ret_cur"] or 0):
        fails.append("return portofolio lebih rendah")
    pp = lambda x: f"{x * 100:+.2f}%".replace(".", ",")  # noqa: E731
    if fails:
        out.update(status="tetap", reason=(f"Kandidat terbaik ({best['param']} {base.get(best['param'])} → {best['new']}) "
                                           f"gagal uji akhir: {', '.join(fails)}. Parameter sekarang tetap dipakai."))
    else:
        out.update(status="usulan", reason=(f"Rata-rata per transaksi {pp(cur_avg)} → {pp(best['sel_avg'])} sebelum "
                                            f"{BULAN[hold_start.month - 1]} {hold_start.year}, menang di {best['blocks'][0]} dari {best['blocks'][1]} "
                                            f"periode, dan tetap lebih baik di 6 bulan terakhir."))
    return out


def run_propose(prep, ind, cfg, n_uni, demo, t0, rules=None):
    rules = {**PROPOSE_RULES, **(rules or {})}
    last = max(d.index[-1] for d in ind.values())
    hold_start = (last - pd.DateOffset(months=rules["holdout_months"])).normalize()
    out = {"generated_at": now_wib().strftime("%Y-%m-%d %H:%M"), "demo": demo, "universe": n_uni,
           "holdout_from": hold_start.strftime("%Y-%m-%d"), "rules": rules, "horizons": {}}
    for h in ("short", "medium"):
        out["horizons"][h] = propose_horizon(prep, ind, cfg, h, hold_start, rules)
        v = out["horizons"][h]
        log.info("Usulan %s: %s — %s", h, v["status"], v.get("reason"))
    out["seconds"] = round(time.time() - t0)
    path = ROOT / ("output/proposal_demo.json" if demo else "docs/data/proposal.json")
    dump_json(out, path)
    log.info("Usulan parameter selesai dalam %d dtk -> %s", out["seconds"], path)
    token, chats = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if token and chats and not demo:
        from src.notify import proposal_message, send
        msg = proposal_message(load_json(path), cfg.get("notify", {}).get("dashboard_url"))
        for cid in [c.strip() for c in chats.split(",") if c.strip()]:
            send(token, cid, msg)
    return out


def propose(cfg: dict, demo: bool = False) -> dict:
    """Dipanggil aplikasi Windows: unduh data, cari usulan, simpan proposal.json."""
    t0 = time.time()
    ind, n_uni = load_data(cfg, demo)
    prep = bt.prepare(ind, ("short", "medium"))
    return run_propose(prep, ind, cfg, n_uni, demo, t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--full", action="store_true", help="grid lengkap syarat masuk & cara keluar")
    ap.add_argument("--realism", action="store_true", help="bandingkan backtest lama vs realistis")
    ap.add_argument("--propose", action="store_true", help="usulan parameter bulanan (tidak diterapkan)")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    t0 = time.time()
    ind, n_uni = load_data(cfg, a.demo)
    prep = bt.prepare(ind, ("short", "medium"))
    log.info("Data siap: %d saham, %.0f dtk", n_uni, time.time() - t0)
    if a.propose:
        run_propose(prep, ind, cfg, n_uni, a.demo, t0)
        return
    if a.realism:
        run_realism(prep, ind, cfg, n_uni, a.demo, t0)
        return
    if not a.full:
        run_exits(prep, ind, cfg, n_uni, a.demo, t0)
        return

    result = {"generated_at": now_wib().strftime("%Y-%m-%d %H:%M"),
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
    for k in ("exits", "realism"):
        if k in prev:
            result[k] = prev[k]
    dump_json(result, path)
    log.info("Selesai dalam %d dtk -> %s", result["seconds"], path)


if __name__ == "__main__":
    main()
