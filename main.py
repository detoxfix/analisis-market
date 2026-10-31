"""PANDU — rekomendasi beli/jual harian saham BEI berkapitalisasi >= Rp 5 T.

Pemakaian:
    python main.py                # jalankan dengan data asli (butuh internet)
    python main.py --demo         # uji coba offline dengan data sintetis
    python main.py --backtest always
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yaml

from src import backtest as bt
from src import data as D
from src import archive, idx, monitor, notify, portsim, positions, report, tracker
from src.indicators import add_indicators
from src.portfolio import allocate
from src.sim import bench_up, market_flag
from src.risk import make_plan, sell_plan
from src.signals import (BUY_SIGNALS, HORIZON_FUNCS, LONG_W, SELL_SIGNALS, compose, entry_mask, explain, label,
                         long_components)
from src.universe import backtest_set, candidate_list, filter_universe
from src.utils import ROOT, dump_json, fnum, load_json, log, now_wib, to_jsonable

HORIZONS = ("short", "medium", "long")


def sector_medians(funds: dict[str, dict]) -> dict[str, dict]:
    df = pd.DataFrame.from_dict(funds, orient="index")
    if df.empty:
        return {}
    for c in ("pe", "pb"):
        if c not in df:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce").where(lambda s: s > 0)
    overall = {"pe": df["pe"].median(), "pb": df["pb"].median()}
    meds = {}
    for sec, g in df.groupby(df.get("sector", pd.Series("Lainnya", index=df.index)).fillna("Lainnya")):
        meds[sec] = {k: (g[k].median() if g[k].notna().sum() >= 3 else overall[k]) for k in ("pe", "pb")}
    meds["_all"] = overall
    return meds


def mkt_exit_text(hcfg: dict, bench: pd.Series) -> str | None:
    """Teks peringatan bila aturan keluar-saat-pasar-berbalik sedang aktif hari ini."""
    mx = hcfg.get("market_exit") or "none"
    if mx == "none" or bench is None or len(bench) < 60:
        return None
    ma = hcfg.get("market_exit_ma") or "sma50"
    cf = int(hcfg.get("market_exit_confirm") or 1)
    if not market_flag(bench_up(bench, ma, bench.index), cf)[-1]:
        return None
    hari = f" {cf} hari berturut-turut" if cf > 1 else ""
    return (f"IHSG close di bawah {ma.upper()}{hari}: " +
            ("jual seluruh posisi horizon ini yang masih terbuka." if mx == "all"
             else "jual 50% posisi horizon ini yang masih terbuka (bila belum)."))


def run(cfg: dict, demo: bool = False, backtest_mode: str = "auto") -> dict:
    now = now_wib()   # runner GitHub memakai UTC
    sources = []
    # ------------------------------------------------------------ 1. data
    if demo:
        log.warning("MODE DEMO: data sintetis, bukan data pasar asli!")
        prices, bench, shares, funds_all = D.demo_dataset()
        names = {t: f["name"] for t, f in funds_all.items()}
        sources.append("DEMO — data sintetis")
        _ts = sorted(prices)[:4]
        _d0 = prices[_ts[0]].index[-8]
        pos_df = pd.DataFrame([{"code": t.replace(".JK", ""), "horizon": hz, "buy_date": _d0,
                                "buy_price": float(prices[t].loc[_d0, "Close"]), "lots": 10, "tp1_done": False,
                                "sl_user": None, "tp1_user": None, "tp2_user": None, "note": "demo"}
                               for t, hz in zip(_ts, ("short", "medium", "long", "short"))])
        pos_errs = []
    else:
        idx_df = D.fetch_idx_list() if cfg["universe"].get("use_idx_list", True) else None
        extra = D.discover_by_screener(cfg["universe"]["min_market_cap"]) if idx_df is None else []
        tickers, shares, names = candidate_list(cfg, idx_df, extra)
        sources.append("Daftar emiten & jumlah saham: idx.co.id (publik)" if shares
                       else "Daftar emiten: data/tickers_seed.csv" + (" + screener Yahoo Finance" if extra else ""))
        bench_px = D.download_prices([cfg["data"]["benchmark"]], period=cfg["data"]["history_period"])
        bench = bench_px[cfg["data"]["benchmark"]]["Close"] if bench_px else None
        prices = D.download_prices(tickers, period=cfg["data"]["history_period"])
        sources.append("Harga OHLCV harian, jumlah saham & fundamental: Yahoo Finance via yfinance (open source, Apache-2.0)")
        sources.append("Arsip fundamental harian & laporan keuangan (kuartalan/tahunan) disimpan di repo: "
                       "data/fundamentals_history")
        pos_df, pos_errs = positions.load()
        extra_pos = [t for t in positions.codes(pos_df) if t not in prices]
        if extra_pos:
            prices.update(D.download_prices(extra_pos, period=cfg["data"]["history_period"]))
        missing = [t for t in prices if t not in shares]
        if missing:
            shares.update(D.get_shares(missing, cfg["data"]["shares_cache_days"]))
        funds_all = None

    if not prices:
        raise SystemExit("Tidak ada data harga yang berhasil diunduh.")
    as_of = max(df.index[-1] for df in prices.values())
    if bench is None or len(bench) == 0:     # proxy IHSG: rata-rata return universe
        rets = pd.DataFrame({t: df["Close"].pct_change() for t, df in prices.items()}).mean(axis=1)
        bench = 1000 * (1 + rets.fillna(0)).cumprod()
        log.warning("Benchmark ^JKSE tidak tersedia, memakai proxy rata-rata universe")

    # ------------------------------------------------------------ 2. universe >= Rp 5 T
    uni = filter_universe(prices, shares, cfg, as_of)
    if uni.empty:
        raise SystemExit("Tidak ada saham yang lolos filter universe.")
    tick_list = uni["ticker"].tolist()
    if demo:
        funds = {t: funds_all[t] for t in tick_list}
    else:
        funds = D.get_fundamentals(tick_list, cfg["data"]["fundamentals_cache_days"])
    meds = sector_medians(funds)
    if not demo:                                   # arsip fundamental (gagal di sini tidak boleh menghentikan sinyal)
        try:
            archive.snapshot_daily(as_of, uni, funds, shares)
            archive.update_statements(tick_list, cfg.get("archive", {}).get("statements_days", 7),
                                      cfg.get("archive", {}).get("statements_per_run", 60))
        except Exception as e:  # noqa: BLE001
            log.warning("Arsip fundamental gagal: %s", e)

    # ------------------------------------------------------------ 2b. transaksi asing (idx.co.id, bila bisa diakses)
    flows = {}
    icfg = cfg.get("idx", {})
    if demo:
        rng = np.random.default_rng(3)
        flows = {c: {"foreign_5d": float(rng.normal(0, 2e10)), "foreign_20d": float(rng.normal(0, 6e10)),
                     "foreign_20d_pct": float(rng.normal(0, 0.05)), "foreign_days": 20,
                     "foreign_last": as_of.strftime("%Y-%m-%d")} for c in uni["code"]}
    elif icfg.get("foreign_flow", True):
        try:
            got = idx.update_summaries(bench.index, icfg.get("backfill_days", 260), icfg.get("max_per_run", 300))
            flows = idx.foreign_flow(uni["code"].tolist())
            if flows:
                sources.append("Transaksi asing harian: idx.co.id (ringkasan perdagangan saham)")
                log.info("Transaksi asing: %d saham (%d hari baru diunduh)", len(flows), got)
        except Exception as e:  # noqa: BLE001
            log.warning("Data transaksi asing gagal: %s", e)

    # ------------------------------------------------------------ 3. indikator & skor
    th = cfg["thresholds"]
    ind, rows_all, per_h = {}, [], {h: {"buys": [], "sells": [], "held": []} for h in HORIZONS}
    for _, u in uni.iterrows():
        t = u["ticker"]
        d = add_indicators(prices[t], bench)
        ind[t] = d
        f = funds.get(t, {}) or {}
        sector = f.get("sector") or "Lainnya"
        name = f.get("name") or names.get(t) or u["code"]
        last = d.iloc[-1]
        rec = {"ticker": t, "code": u["code"], "name": name, "sector": sector, "price": float(last["Close"]),
               "chg_1d": fnum(last["CHG_1D"]), "mcap": float(u["mcap"]), "avg_value_20d": float(u["avg_value_20d"]),
               "pe": f.get("pe"), "pb": f.get("pb"), "roe": f.get("roe"), "div_yield": f.get("div_yield"),
               **flows.get(u["code"], {})}
        for h in HORIZONS:
            if h == "long":
                comp = long_components(d, f, meds.get(sector, meds.get("_all", {})))
                W = LONG_W
            else:
                fn, W = HORIZON_FUNCS[h]
                comp = fn(d)
            score_s, cov_s = compose(comp, W)
            sc = fnum(score_s.iloc[-1])
            sig = label(sc, th)
            cov = float(cov_s.iloc[-1])
            rec[h] = {"score": sc, "signal": sig}
            if sig in BUY_SIGNALS or sig in SELL_SIGNALS:
                bull = sig in BUY_SIGNALS
                reasons, risks = explain(comp.iloc[-1], W, last, f, bullish=bull)
                item = {"ticker": t, "code": u["code"], "name": name, "sector": sector, "horizon": h,
                        "price": float(last["Close"]), "chg_1d": fnum(last["CHG_1D"]), "mcap": float(u["mcap"]),
                        "score": sc, "signal": sig, "confidence": round(min(1, abs(sc) / 100) * cov, 3),
                        "atr_pct": fnum(last["ATR_pct"]), "reasons": reasons, "risks": risks,
                        **flows.get(u["code"], {})}
                if bull:
                    plan = make_plan(last, h, cfg["horizons"][h], cfg["fees"])
                    if plan:
                        item.update(plan)
                        ok, why = entry_mask(d.iloc[-1:], score_s.iloc[-1:], cfg["horizons"][h], th)
                        item["held"] = None if bool(ok.iloc[-1]) else (why.iloc[-1] or "Tidak lolos syarat masuk")
                        per_h[h]["buys" if item["held"] is None else "held"].append(item)
                else:
                    item.update(sell_plan(last, sig))
                    per_h[h]["sells"].append(item)
        rows_all.append(rec)

    # ------------------------------------------------------------ 4. bobot portofolio
    new_recs = []
    # posisi IHSG terhadap SMA50 & SMA200 -> pengali porsi (opsi `regime_scale` per horizon)
    b_sma50 = bench.rolling(50).mean().iloc[-1]
    b_sma200 = bench.rolling(200).mean().iloc[-1] if len(bench) >= 200 else np.nan
    b_now = bench.iloc[-1]
    level = ("above_sma200" if b_now > b_sma200 else "above_sma50" if b_now > b_sma50 else "below")
    level_text = {"above_sma200": "IHSG di atas SMA200",
                  "above_sma50": "IHSG di bawah SMA200 tetapi di atas SMA50",
                  "below": "IHSG di bawah SMA50 dan SMA200"}[level]
    for h in HORIZONS:
        hcfg = cfg["horizons"][h]
        scale = float((hcfg.get("regime_scale") or {}).get(level, 1.0))
        picked, cash = allocate(per_h[h]["buys"], hcfg, cfg["capital"], cfg["risk_per_trade"], scale)
        picked_codes = {p["code"] for p in picked}
        watch = [b for b in sorted(per_h[h]["buys"], key=lambda x: -x["score"]) if b["code"] not in picked_codes]
        for b in watch:
            b["held"] = "Di luar kuota posisi"
        watch = watch + sorted(per_h[h]["held"], key=lambda x: -x["score"])
        per_h[h] = {"label": hcfg["label"], "allocation": hcfg["allocation"], "cash_weight": cash,
                    "regime_scale": scale, "regime_text": level_text if scale < 1 else None,
                    "buys": picked, "watchlist": watch[:15], "n_held": len(per_h[h]["held"]),
                    "rules": {k: hcfg.get(k) for k in ("min_score", "market_filter", "trend_filter", "entry_mode",
                                                       "limit_days", "trail_ma", "sl_atr", "max_sl_pct", "rr",
                                                       "market_exit", "market_exit_ma", "market_exit_confirm")},
                    "market_exit_active": mkt_exit_text(hcfg, bench),
                    "sells": sorted(per_h[h]["sells"], key=lambda x: x["score"])}
        new_recs += [p for p in picked if p["lots"] > 0]

    # ------------------------------------------------------------ 5. track record & backtest
    track = tracker.update(prices, new_recs, cfg["fees"], as_of, demo=demo, bench=bench,
                           exec_cfg=cfg.get("backtest", {}).get("execution"))

    # ------------------------------------------------------------ 5b. posisi pribadi
    signals = {r["code"]: {h: r[h] for h in HORIZONS} for r in rows_all}
    try:
        pos_items = positions.evaluate(pos_df, prices, bench, cfg, signals, as_of)
    except Exception as e:  # noqa: BLE001
        log.warning("Pemantau posisi gagal: %s", e)
        pos_items, pos_errs = [], pos_errs + [f"Pemantau posisi gagal: {e}"]
    bt_path = ROOT / "docs" / "data" / "backtest.json"
    bt_res = load_json(bt_path) if not demo else None
    cfg_hash = hashlib.md5(json.dumps({"h": {h: cfg["horizons"][h] for h in ("short", "medium")}, "v": 3,
                                       "cap": cfg["capital"], "risk": cfg["risk_per_trade"],
                                       "bt": {k: v for k, v in cfg.get("backtest", {}).items()
                                              if k in ("point_in_time", "execution", "split_date")}},
                                      sort_keys=True, default=str)
                           .encode()).hexdigest()[:10]
    stale = (bt_res is None or bt_res.get("config_hash") != cfg_hash        # parameter berubah -> backtest ulang
             or datetime.fromisoformat(bt_res.get("generated_at", "2000-01-01"))
             < now - timedelta(days=cfg.get("backtest", {}).get("refresh_days", 7)))
    if backtest_mode == "always" or (backtest_mode == "auto" and stale):
        log.info("Menjalankan backtest...")
        ind_bt = ind
        if cfg.get("backtest", {}).get("point_in_time", True):
            try:                                   # universe per tanggal: termasuk saham yang dulu lolos
                ind_bt = backtest_set(prices, shares, cfg, list(ind),
                                      lambda t: ind[t] if t in ind else add_indicators(prices[t], bench))
            except Exception as e:  # noqa: BLE001
                log.warning("Universe backtest per tanggal gagal, memakai universe hari ini: %s", e)
        bt_res = {"generated_at": now.isoformat(timespec="seconds"), "config_hash": cfg_hash,
                  "assumptions": bt.assumptions(cfg, ind_bt), "results": bt.run(ind_bt, cfg)}
        try:
            bt_res["portfolio"] = portsim.run(ind_bt, cfg)
        except Exception as e:  # noqa: BLE001  (simulasi portofolio tidak boleh menggagalkan sinyal harian)
            log.warning("Simulasi portofolio gagal: %s", e)
        if not demo:
            dump_json(bt_res, bt_path)
    try:                                           # alarm penyimpangan: track record vs perkiraan backtest
        mon = monitor.check(track, bt_res, cfg)
        for h_, v_ in mon["horizons"].items():
            if v_["level"] in ("WASPADA", "BAHAYA"):
                log.warning("Alarm %s: %s — %s", v_["label"], v_["level"], v_.get("text", ""))
    except Exception as e:  # noqa: BLE001
        log.warning("Alarm penyimpangan gagal: %s", e)
        mon = None
    proposal = load_json(ROOT / ("output/proposal_demo.json" if demo else "docs/data/proposal.json"))
    for h_, v_ in ((proposal or {}).get("horizons") or {}).items():   # usulan yang sudah ada di config = diterapkan
        ch_ = v_.get("change") or {}
        if v_.get("status") == "usulan" and not v_.get("applied_at") and ch_ and \
                cfg["horizons"].get(h_, {}).get(ch_.get("param")) == ch_.get("new"):
            v_["applied_at"] = "sudah sesuai config.yaml"
    if bt_res is not None:                         # perbandingan backtest lama vs realistis (hasil tune.py --realism)
        tun = load_json(ROOT / ("output/tuning_demo.json" if demo else "docs/data/tuning.json"), {}) or {}
        if tun.get("realism"):
            bt_res = {**bt_res, "realism": tun["realism"]}

    # ------------------------------------------------------------ 6. ringkasan pasar & output
    # data grafik untuk dashboard: garis IHSG 6 bulan + SMA50/SMA200, dan harga 60 hari per saham bersinyal
    bs = bench.dropna()
    tail = pd.DataFrame({"c": bs, "m50": bs.rolling(50).mean(), "m200": bs.rolling(200).mean()}).tail(130)
    series = [[d.strftime("%Y-%m-%d"), round(float(r.c), 2),
               None if pd.isna(r.m50) else round(float(r.m50), 2),
               None if pd.isna(r.m200) else round(float(r.m200), 2)] for d, r in tail.iterrows()]

    def spark(t):
        px = prices.get(t)
        return [round(float(v), 2) for v in px["Close"].tail(60)] if px is not None else None
    for blk in per_h.values():
        for kind in ("buys", "watchlist", "sells"):
            for it in blk[kind]:
                it["spark"] = spark(it["ticker"])
    for it in pos_items:
        it["spark"] = spark(D.jk(it["code"]))
    b_last, b_prev = float(bench.iloc[-1]), float(bench.iloc[-2])
    b_ema20 = float(bench.ewm(span=20, adjust=False).mean().iloc[-1])
    b_sma200 = float(bench.rolling(200).mean().iloc[-1]) if len(bench) >= 200 else None
    regime = ("Bullish" if b_last > b_ema20 and (b_sma200 is None or b_last > b_sma200)
              else "Bearish" if b_last < b_ema20 and (b_sma200 is not None and b_last < b_sma200) else "Sideways")
    result = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M"), "as_of": as_of.strftime("%Y-%m-%d"), "demo": demo,
        "params": {"min_market_cap": cfg["universe"]["min_market_cap"], "min_avg_value_20d": cfg["universe"]["min_avg_value_20d"],
                   "capital": cfg["capital"], "risk_per_trade": cfg["risk_per_trade"], "fees": cfg["fees"],
                   "split_date": cfg.get("backtest", {}).get("split_date"),
                   "thresholds": th},
        "market": {"bench": b_last, "bench_chg": b_last / b_prev - 1, "regime": regime,
                   "universe": len(uni), "scanned": len(prices), "series": series,
                   "above_sma50": bool(series and series[-1][2] and series[-1][1] > series[-1][2]),
                   "above_sma200": bool(series and series[-1][3] and series[-1][1] > series[-1][3])},
        "horizons": per_h,
        "positions": positions.public_view(pos_items, cfg.get("positions", {}).get("dashboard", "percent")),
        "positions_errors": pos_errs,
        "_positions_full": pos_items,
        "all": sorted(rows_all, key=lambda r: -r["mcap"]),
        "track": track,
        "monitor": mon,
        "proposal": proposal,
        "backtest": bt_res,
        "sources": sources,
    }
    return result


def write_outputs(res: dict, demo: bool):
    docs = ROOT / ("output/demo" if demo else "docs")
    data_dir = docs / "data"
    dump_json(res, data_dir / "latest.json")
    if not demo:
        dump_json(res, data_dir / "history" / f"signals_{res['as_of']}.json")
    report.write_html(to_jsonable(res), docs / "index.html")
    flat = []
    for h, blk in res["horizons"].items():
        for kind in ("buys", "watchlist", "sells"):
            for it in blk[kind]:
                flat.append({"horizon": h, "list": kind, **{k: v for k, v in it.items()
                                                            if k not in ("reasons", "risks", "when_buy", "when_sell")},
                             "reasons": "; ".join(it.get("reasons", [])), "risks": "; ".join(it.get("risks", []))})
    out_csv = ROOT / "output" / ("demo_signals.csv" if demo else "signals_latest.csv")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(flat).to_csv(out_csv, index=False)
    log.info("Selesai. Dashboard: %s | CSV: %s", docs / "index.html", out_csv)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--demo", action="store_true", help="data sintetis offline (untuk uji coba)")
    ap.add_argument("--backtest", choices=["never", "auto", "always"], default="auto")
    ap.add_argument("--no-notify", action="store_true")
    a = ap.parse_args()
    with open(a.config, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    res = run(cfg, demo=a.demo, backtest_mode=a.backtest)
    pos_full = res.pop("_positions_full", None)        # lengkap (lot & nominal) hanya untuk Telegram
    write_outputs(res, a.demo)
    if not a.no_notify and not a.demo and cfg.get("notify", {}).get("telegram"):
        notify.telegram(res, os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID"),
                        cfg.get("notify", {}).get("dashboard_url"), pos_full)


if __name__ == "__main__":
    main()
