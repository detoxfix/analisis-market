"""Uji unit inti. Jalankan: python -m pytest -q  (atau: python tests/test_core.py)"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.portfolio import _water_fill, allocate  # noqa: E402
from src.risk import make_plan  # noqa: E402
from src.sim import simulate  # noqa: E402
from src.utils import round_tick, tick_size  # noqa: E402

FEES = {"buy": 0.0015, "sell": 0.0025}


def test_tick_size():
    assert [tick_size(p) for p in (150, 300, 1500, 4000, 9000)] == [1, 2, 5, 10, 25]
    assert round_tick(9012, "down") == 9000 and round_tick(9012, "up") == 9025
    assert round_tick(1503, "nearest") == 1505


def test_plan_levels_valid():
    row = {"Close": 9300.0, "ATR14": 200.0, "EMA20": 9100.0, "SMA50": 8800.0, "HH250": 10000.0}
    h = {"entry_atr": 0.5, "chase_atr": 0.3, "sl_atr": 1.5, "max_sl_pct": 0.07, "rr": [1.5, 2.5],
         "hold_min_days": 3, "hold_max_days": 10}
    p = make_plan(row, "short", h, FEES)
    assert p["sl"] < p["entry_low"] <= p["entry"] <= p["entry_high"] < p["tp1"] < p["tp2"]
    for k in ("sl", "tp1", "tp2", "entry_low", "entry_high"):
        assert p[k] % tick_size(p[k]) == 0, k
    assert p["sl_pct"] >= -0.07 - 1e-9


def _bars(rows):
    idx = pd.bdate_range("2026-01-01", periods=len(rows))
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)


def test_sim_sl_and_tp():
    plan = {"entry_high": 1010, "sl": 950, "tp1": 1060, "tp2": 1100, "max_hold_days": 10}
    sl_case = _bars([[1000, 1000, 1000, 1000], [1000, 1010, 940, 945]])
    assert simulate(sl_case, 0, plan, FEES)["outcome"] == "SL"
    tp_case = _bars([[1000] * 4, [1000, 1070, 990, 1065], [1065, 1110, 1060, 1100]])
    r = simulate(tp_case, 0, plan, FEES)
    assert r["outcome"] == "TP2" and r["tp1_hit"] and r["ret"] > 0.07
    gap = _bars([[1000] * 4, [1050, 1060, 1040, 1050]])
    assert simulate(gap, 0, plan, FEES)["outcome"] == "BATAL"


def test_sim_limit_and_trail():
    plan = {"entry": 980, "entry_high": 980, "sl": 940, "tp1": 1020, "tp2": 1200, "max_hold_days": 10,
            "entry_mode": "limit", "limit_days": 3, "trail_ma": 0}
    miss = _bars([[1000] * 4, [1000, 1010, 990, 1000], [1000, 1010, 985, 1000], [1000, 1010, 990, 1000]])
    assert simulate(miss, 0, plan, FEES)["outcome"] == "BATAL"
    fill = _bars([[1000] * 4, [1000, 1010, 975, 990], [990, 1030, 985, 1025]])
    r = simulate(fill, 0, plan, FEES)
    assert r["entry_px"] == 980 and r["tp1_hit"]
    trail_plan = {**plan, "trail_ma": 2}
    rows = [[1000] * 4, [1000, 1010, 975, 990], [990, 1030, 985, 1025], [1025, 1026, 990, 991]]
    r2 = simulate(_bars(rows), 0, trail_plan, FEES)
    assert r2["outcome"] == "TP1+TRAIL", r2["outcome"]


def test_market_exit():
    from src.sim import market_flag
    assert market_flag([1, 0, 0, 1, 0], 1).tolist() == [False, True, True, False, True]
    assert market_flag([1, 0, 0, 1, 0], 2).tolist() == [False, False, True, False, False]
    plan = {"entry_high": 1010, "sl": 900, "tp1": 1100, "tp2": 1200, "max_hold_days": 20, "market_exit": "all"}
    rows = [[1000] * 4, [1000, 1010, 990, 1000], [1000, 1005, 980, 990], [990, 995, 950, 960]]
    import numpy as np
    from src.sim import simulate_arr
    o, h, l, c = (np.array([r[k] for r in rows], float) for k in range(4))
    flag = np.array([False, False, True, True])
    r = simulate_arr(o, h, l, c, 0, plan, FEES, None, flag)
    assert r["outcome"] == "MKT" and r["exit_px"] == 990
    r2 = simulate_arr(o, h, l, c, 0, {**plan, "market_exit": "half"}, FEES, None, flag)
    assert r2["outcome"].startswith("MKT½+") and r2["tp1_px"] == 990


def test_weights():
    w = _water_fill(np.array([10.0, 1, 1, 1]), 0.3)
    assert abs(w.sum() - 1) < 1e-9 and w.max() <= 0.3 + 1e-9
    picks = [{"score": 80, "atr_pct": 0.02, "sector": "A", "entry": 1000, "sl": 950},
             {"score": 40, "atr_pct": 0.04, "sector": "A", "entry": 500, "sl": 470}]
    h = {"max_positions": 5, "max_weight": 0.6, "sector_cap": 0.5, "allocation": 0.2}
    out, cash = allocate(picks, h, 100_000_000, 0.01)
    assert abs(sum(p["weight_bucket"] for p in out) - 0.5) < 1e-9 and abs(cash - 0.5) < 1e-9
    assert all(p["max_loss_value"] <= 1_000_000 + 1 for p in out)


def test_execution_realism():
    from src.sim import arb_lock, simulate_arr
    # beli di lelang pembukaan = harga open; SL di tengah sesi: 1 tick lebih murah (harga 900 -> tick 5)
    plan = {"entry_high": 1010, "sl": 900, "tp1": 1100, "tp2": 1200, "max_hold_days": 20}
    rows = [[1000] * 4, [1000, 1010, 990, 1000], [990, 995, 880, 890]]
    o, h, l, c = (np.array([r[k] for r in rows], float) for k in range(4))
    r = simulate_arr(o, h, l, c, 0, plan, FEES, ex={"slip": 1, "through": True})
    assert r["entry_px"] == 1000 and r["exit_px"] == 895 and r["outcome"] == "SL"
    r = simulate_arr(o, h, l, c, 0, plan, FEES, ex={"slip": 1, "slip_auction": 1, "through": True})
    assert r["entry_px"] == 1005
    # TP yang hanya disentuh tidak terisi bila limit_through aktif
    rows = [[1000] * 4, [1000, 1010, 990, 1000], [1000, 1100, 1000, 1050], [1050, 1110, 1040, 1100]]
    o, h, l, c = (np.array([r[k] for r in rows], float) for k in range(4))
    r = simulate_arr(o, h, l, c, 0, plan, FEES, ex={"slip": 0, "through": True})
    assert r["tp1_pos"] == 3
    r = simulate_arr(o, h, l, c, 0, plan, FEES)
    assert r["tp1_pos"] == 2
    # ARB: hari ke-3 dibuka & ditutup di batas bawah 15% (aturan 2025) -> jual baru bisa hari ke-4
    dates = pd.to_datetime(["2025-06-02", "2025-06-03", "2025-06-04", "2025-06-05"])
    rows = [[1000] * 4, [1000, 1010, 990, 1000], [850, 850, 850, 850], [840, 900, 830, 880]]
    o, h, l, c = (np.array([r[k] for r in rows], float) for k in range(4))
    lc, lo = arb_lock(dates, o, h, l, c)
    assert lo.tolist() == [False, False, True, False]
    r = simulate_arr(o, h, l, c, 0, plan, FEES, ex={"slip": 0, "through": True, "lock_close": lc, "lock_open": lo})
    assert r["outcome"] == "SL" and r["exit_pos"] == 3 and r["exit_px"] == 840 and r["arb_blocked"] == 1
    # tanpa ARB: dianggap terjual di open hari ke-3
    r = simulate_arr(o, h, l, c, 0, plan, FEES)
    assert r["exit_pos"] == 2 and r["exit_px"] == 850


def test_point_in_time():
    from src.universe import eligibility
    idx_ = pd.date_range("2025-01-01", periods=40, freq="B")
    df = pd.DataFrame({"Close": np.r_[np.full(20, 1000.0), np.full(20, 400.0)], "Volume": 1e7}, index=idx_)
    cfg = {"universe": {"min_market_cap": 5e12, "min_avg_value_20d": 5e9, "min_price": 50}}
    el = eligibility(df, 6e9, cfg)        # 6 miliar lembar: Rp 6 T lalu Rp 2,4 T
    assert not el.iloc[:14].any() and el.iloc[14:20].all() and not el.iloc[20:].any()


def test_monitor():
    from src.monitor import check, streak_prob
    assert abs(streak_prob(3, 3, 0.5) - 0.125) < 1e-9 and streak_prob(5, 1, 0.0) == 0.0
    bt = {"results": {"short": {"n": 300, "avg_ret": 0.01, "win_rate": 0.5, "std_ret": 0.05,
                                "out_sample": {"n": 100, "avg_ret": 0.01, "win_rate": 0.5, "std_ret": 0.05}}}}
    cfg = {"monitor": {"min_trades": 10}}
    few = {"closed_rets": {"short": [["2026-10-01", 0.01]] * 5}}
    assert check(few, bt, cfg)["horizons"]["short"]["level"] == "BELUM CUKUP DATA"
    ok = {"closed_rets": {"short": [["d", r] for r in [0.05, -0.04, 0.03, -0.02, 0.06, -0.03, 0.02, 0.01, -0.01, 0.04] * 2]}}
    assert check(ok, bt, cfg)["horizons"]["short"]["level"] in ("NORMAL", "LEBIH BAIK")
    bad = {"closed_rets": {"short": [["d", -0.04]] * 12}}
    r = check(bad, bt, cfg)
    assert r["horizons"]["short"]["level"] == "BAHAYA" and r["level"] == "BAHAYA"
    # memburuk baru-baru ini: 30 transaksi bagus lalu 20 buruk
    late = {"closed_rets": {"short": [["d", 0.03]] * 30 + [["d", -0.03]] * 20}}
    assert check(late, bt, cfg)["horizons"]["short"]["level"] == "BAHAYA"


def test_monitor_early_alarm():
    """Rugi beruntun harus memicu alarm walau < 10 transaksi, tanpa std_ret, dan tanpa backtest."""
    from src.monitor import check
    cfg = {"monitor": {"min_trades": 10, "early_trades": 5}}
    bt_nostd = {"results": {"short": {"n": 900, "avg_ret": 0.0, "win_rate": 0.41,
                                      "out_sample": {"n": 700, "avg_ret": 0.002, "win_rate": 0.415}}}}
    seven = {"closed_rets": {"short": [["d", -0.06, "v0"]] * 7}}
    r = check(seven, bt_nostd, cfg)["horizons"]["short"]
    assert r["level"] == "WASPADA" and r.get("early") and "berturut-turut" in r["text"]
    # tanpa backtest (jangka panjang): pembanding win rate 50%
    longs = {"closed_rets": {"long": [["d", -0.05]] * 8}}
    assert check(longs, None, cfg)["horizons"]["long"]["level"] == "BAHAYA"
    # sedikit transaksi & hasil wajar: tetap BELUM CUKUP DATA, bukan NORMAL
    mix = {"closed_rets": {"short": [["d", r_] for r_ in (0.03, -0.02, 0.04, -0.01, 0.02, -0.03)]}}
    assert check(mix, bt_nostd, cfg)["horizons"]["short"]["level"] == "BELUM CUKUP DATA"
    # versi aktif dinilai sendiri setelah punya >= min_trades; rugi versi lama tidak ikut
    hist = [["d", -0.05, "old"]] * 12 + [["d", r_, "new"] for r_ in (0.03, -0.02, 0.04, -0.01, 0.02) * 2]
    bt = {"results": {"short": {"n": 300, "avg_ret": 0.005, "win_rate": 0.5, "std_ret": 0.05}}}
    r = check({"closed_rets": {"short": hist}}, bt, cfg, {"short": {"id": "new"}})["horizons"]["short"]
    assert r["scope"] == "versi aktif" and r["n"] == 10 and r["level"] in ("NORMAL", "LEBIH BAIK")
    r = check({"closed_rets": {"short": hist[:15]}}, bt, cfg, {"short": {"id": "new"}})["horizons"]["short"]
    assert r["scope"] == "semua versi" and r["level"] == "BAHAYA" and "versi lama" in r["text"]


def test_versions(tmp_path):
    from src import versions as V
    cfg = {"horizons": {"short": {"label": "A", "sl_atr": 2.5}, "medium": {"sl_atr": 3.5}, "long": {"sl_atr": 4}},
           "thresholds": {"buy": 30}, "fees": {"buy": 0.0015}}
    path = tmp_path / "v.json"
    a = V.register(cfg, "2026-11-09", path=path)
    assert a["short"]["v"] == 1 and a["short"]["since"] == "2026-11-09"
    cfg["horizons"]["short"]["label"] = "B"                       # kosmetik: versi tetap
    assert V.register(cfg, "2026-11-10", path=path)["short"]["id"] == a["short"]["id"]
    cfg["horizons"]["short"]["sl_atr"] = 3.0                      # parameter berubah: versi baru
    b = V.register(cfg, "2026-11-11", path=path)
    assert b["short"]["v"] == 2 and b["short"]["since"] == "2026-11-11" and b["medium"]["v"] == 1
    assert V.label_of(b, "short", a["short"]["id"]).startswith("v1") and V.label_of(b, "short", None).startswith("v0")


def test_tracker_versions():
    from src.tracker import COLS, summarize
    rows = [dict.fromkeys(COLS) for _ in range(3)]
    for r_, (sid, ret) in zip(rows, ((None, -0.05), ("abc", 0.04), ("abc", None))):
        r_.update(id=f"x{ret}", date="2026-11-03", ticker="A.JK", code="A", horizon="short", status="CLOSED",
                  outcome="SL" if ret else "BATAL", ret=ret if ret else 0.0, exit_date="2026-11-05", strategy=sid)
    df = pd.DataFrame(rows, columns=COLS)
    vers = {"short": {"id": "abc", "v": 1, "since": "2026-11-03", "label": "v1 · sejak 2026-11-03"},
            "_all": {"short": {"abc": "v1 · sejak 2026-11-03"}}}
    s = summarize(df, vers)
    bv = {v["strategy"]: v for v in s["by_version"]["short"]}
    assert bv["abc"]["current"] and bv["abc"]["n"] == 1 and bv["v0"]["n"] == 1 and s["by_version"]["short"][0]["current"]
    assert sorted(c[2] for c in s["closed_rets"]["short"]) == ["abc", "v0"]


def test_data_freshness():
    from datetime import datetime
    from src.utils import data_freshness
    # Sabtu dini hari, data terakhir Kamis -> Jumat terlewat
    f = data_freshness("2026-11-05", datetime(2026, 11, 7, 0, 37))
    assert f["stale"] and f["lag"] == 1 and f["expected"] == "2026-11-06"
    # Jumat sore setelah jam siap, data Jumat ada -> segar
    assert not data_freshness("2026-11-06", datetime(2026, 11, 6, 17, 40))["stale"]
    # Jumat 16:00 (sebelum jam siap): data Kamis masih wajar
    assert not data_freshness("2026-11-05", datetime(2026, 11, 6, 16, 0))["stale"]
    # libur bursa dilewati
    assert not data_freshness("2026-12-24", datetime(2026, 12, 26, 9, 0), ["2026-12-25"])["stale"]


def test_news_rules():
    from src import news as N
    assert [c for c, _ in N.classify("BBRI Umumkan Rights Issue Rp 40 Triliun")] == ["Right issue (dilusi)"]
    assert N.classify("Laba bersih ADRO anjlok 40% di kuartal III")[0][0] == "Kinerja memburuk"
    assert N.classify("Kreditur ajukan PKPU terhadap emiten konstruksi")[0][1] == "tinggi"
    assert N.classify("Saham BBCA naik 2%, asing borong") == []
    alias = N._name_alias("PT Bank Rakyat Indonesia (Persero) Tbk")
    assert alias == "bank rakyat indonesia" and N._name_alias("PT Indonesia Tbk") is None
    assert N.mentions("Bank Rakyat Indonesia digugat nasabah", "BBRI", alias)
    assert N.mentions("Emiten tambang (CUAN) right issue", "CUAN", None)
    assert not N.mentions("Strategi cari cuan saat rights issue", "CUAN", None)
    assert not N.mentions("CUAN besar dari right issue", "CUAN", None)
    al = {"BUMI": "bumi resources", "BRMS": "bumi resources minerals", "MBMA": None, "MEDC": None}
    t = "Saham Bumi Resources Minerals (BRMS) Kena Downgrade"
    assert N.mentions(t, "BRMS", al["BRMS"], al) and not N.mentions(t, "BUMI", al["BUMI"], al)
    t = "IHSG Rebound 0,75%: MEDC & TAPG Bagikan Dividen Interim, MBMA Siapkan Private Placement"
    hit = lambda c: [x for x in N.clauses(t) if N.mentions(x, c, None) and N.classify(x)]  # noqa: E731
    assert hit("MBMA") and not hit("MEDC")
    xml = ("<rss><channel><item><title>BBRI digugat Rp 1 T - Kontan</title><link>http://x</link>"
           "<pubDate>Fri, 06 Nov 2026 03:00:00 GMT</pubDate><source url='k'>Kontan</source></item></channel></rss>")
    it = N.parse_rss(xml)[0]
    assert it["title"] == "BBRI digugat Rp 1 T" and it["source"] == "Kontan" and it["published"].day == 6


def test_config_edit():
    import yaml
    from src.configedit import set_horizon_param
    t = "horizons:\n  short:\n    sl_atr: 2.5     # lama\n    rr: [2.0, 3.0]\n  medium:\n    sl_atr: 3.5\n\nfees:\n  buy: 0.1\n"
    t2 = set_horizon_param(t, "medium", "sl_atr", 4.0, "usulan")
    t2 = set_horizon_param(t2, "short", "rr", [2.5, 4.0])
    t2 = set_horizon_param(t2, "medium", "trend_filter", "sma200")
    y = yaml.safe_load(t2)
    assert y["horizons"]["medium"] == {"sl_atr": 4.0, "trend_filter": "sma200"}
    assert y["horizons"]["short"] == {"sl_atr": 2.5, "rr": [2.5, 4.0]} and y["fees"] == {"buy": 0.1}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            import inspect
            import tempfile
            if "tmp_path" in inspect.signature(fn).parameters:
                with tempfile.TemporaryDirectory() as td:
                    fn(Path(td))
            else:
                fn()
            print("OK", name)
