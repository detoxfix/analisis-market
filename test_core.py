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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
