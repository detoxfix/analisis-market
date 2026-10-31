"""Simulasi satu transaksi mengikuti rencana (dipakai track record, backtest & tuning).

Aturan:
- entry_mode "open"  : masuk di OPEN hari berikutnya bila open <= batas kejar (entry_high) dan > SL.
  entry_mode "limit" : antre beli di harga `entry` (area bawah) selama `limit_days` hari bursa;
                       terisi di open bila open <= entry, atau di harga entry bila low menyentuhnya.
  Tidak terisi -> 'BATAL'.
- Setiap hari: cek SL dulu (konservatif), lalu TP1 (jual 50%, SL naik ke harga beli), lalu TP2.
- Trailing (opsional, `trail_ma` > 0): setelah TP1, sisa posisi dijual bila close < EMA(trail_ma).
- Keluar saat pasar berbalik (opsional, `market_exit`): bila IHSG close di bawah MA `market_exit_ma`
  selama `market_exit_confirm` hari berturut-turut saat posisi terbuka:
    "half" -> jual 50% di close (sekali saja; tidak berlaku bila separuh sudah dijual di TP1)
    "all"  -> jual seluruh sisa posisi di close
- Time-stop: setelah `max_hold_days` hari bursa sejak masuk, sisa posisi dijual di close.

Eksekusi realistis (opsional, argumen `ex`, dipakai backtest/tuning/track record):
- slippage: cut loss yang tersentuh di tengah sesi (order pasar menyeberang spread) terisi `slip` tick
  lebih buruk; transaksi di harga pembukaan/penutupan (lelang pra-pembukaan & pra-penutupan BEI)
  terisi di harga lelang + `slip_auction` tick (default 0)
- antrean limit (`through`): order limit (beli di area bawah, TP) baru dianggap terisi bila harga
  menembus 1 tick melewati harga order (sekadar menyentuh belum tentu kebagian antrean)
- ARB: hari saham terkunci di batas auto-reject bawah, jual di close tidak bisa (`lock_close`);
  bila sejak pembukaan sudah di ARB (`lock_open`) jual di pagi hari juga tidak bisa -> dicoba hari
  berikutnya di harga pembukaan
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _num(x, default):
    try:
        f = float(x)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def ema_np(c: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(c).ewm(span=n, adjust=False).mean().to_numpy()


def market_flag(mkt_up, confirm: int = 1) -> np.ndarray:
    """mkt_up: 1 bila IHSG di atas MA, 0 bila di bawah, NaN = belum diketahui.
    Return True pada hari IHSG sudah `confirm` hari berturut-turut di bawah MA."""
    up = np.asarray(mkt_up, dtype=float)
    bad = up < 0.5                                   # NaN -> False
    out = bad.copy()
    for k in range(1, max(1, int(confirm))):
        out[k:] &= bad[:-k]
        out[:k] = False
    return out


# Riwayat batas auto-reject bawah (ARB) BEI: (berlaku mulai, persen | "sym" = sama dengan ARA)
ARB_HISTORY = [
    ("2000-01-01", "sym"),
    ("2020-03-10", 0.07),       # masa pandemi
    ("2023-06-05", 0.15),       # normalisasi tahap I
    ("2023-09-04", "sym"),      # ARB simetris (tahap II)
    ("2025-04-08", 0.15),       # setelah koreksi tajam April 2025
    ("2026-10-19", 0.07),       # Kep-00157/BEI/10-2026 (s.d. 31 Des 2026)
]


def ara_pct(prev: float) -> float:
    return 0.35 if prev <= 200 else 0.25 if prev <= 5000 else 0.20


def arb_lock(dates, o, h, l, c, history=ARB_HISTORY) -> tuple[np.ndarray, np.ndarray]:
    """(lock_close, lock_open): close di batas ARB (dan close = low); lock_open = juga dibuka di ARB."""
    from .utils import tick_size
    n = len(c)
    lc, lo = np.zeros(n, bool), np.zeros(n, bool)
    if n < 2:
        return lc, lo
    when = pd.DatetimeIndex(dates)
    starts = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in history])
    rule_ix = np.searchsorted(starts.values, when.values, side="right") - 1
    for j in range(1, n):
        prev = c[j - 1]
        if not (prev > 0 and np.isfinite(l[j]) and np.isfinite(c[j])):
            continue
        rule = history[max(rule_ix[j], 0)][1]
        pct = ara_pct(prev) if rule == "sym" else float(rule)
        limit = prev * (1 - pct)
        tol = tick_size(limit) + prev * 0.002          # harga terkoreksi dividen -> beri toleransi
        if c[j] <= l[j] * (1 + 1e-6) and l[j] <= limit + tol:
            lc[j] = True
            lo[j] = o[j] <= l[j] * (1 + 1e-6)
    return lc, lo


def exec_arrays(dates, o, h, l, c, ecfg: dict | None) -> dict | None:
    """Siapkan parameter eksekusi realistis untuk satu saham dari config backtest.execution."""
    if not ecfg or not ecfg.get("enabled", True):
        return None
    ex = {"slip": int(ecfg.get("slippage_ticks", 1)), "slip_auction": int(ecfg.get("auction_slippage_ticks", 0)),
          "through": bool(ecfg.get("limit_through", True))}
    if ecfg.get("arb", True):
        ex["lock_close"], ex["lock_open"] = arb_lock(dates, o, h, l, c)
    return ex


def bench_up(bench: pd.Series, ma: str, index) -> np.ndarray:
    """Posisi IHSG terhadap MA (ema20/sma50/sma200), diselaraskan ke tanggal `index`."""
    b = bench.dropna().sort_index()
    line = (b.ewm(span=20, adjust=False, min_periods=20).mean() if ma == "ema20"
            else b.rolling(int(ma.replace("sma", "")), min_periods=int(ma.replace("sma", ""))).mean())
    up = (b > line).astype(float).where(line.notna())
    return up.reindex(pd.DatetimeIndex(index)).ffill().to_numpy()


def simulate_arr(o, h, l, c, signal_pos: int, plan: dict, fees: dict, trail_line=None, mkt_exit=None,
                 ex: dict | None = None) -> dict:
    from .utils import tick_size
    n = len(c)
    k_slip = int(ex.get("slip", 0)) if ex else 0
    k_auc = int(ex.get("slip_auction", 0)) if ex else 0
    through = bool(ex.get("through")) if ex else False
    lock_c = ex.get("lock_close") if ex else None
    lock_o = ex.get("lock_open") if ex else None

    def buy_px(px):                                   # beli di lelang pembukaan
        return px + k_auc * tick_size(px) if k_auc else px

    def sell_px(px, k=None):                          # jual di lelang (default) atau order pasar (k=k_slip)
        k = k_auc if k is None else k
        return max(px - k * tick_size(px), 1.0) if k else px

    def thr(px):                                       # selisih tembus antrean limit
        return tick_size(px) if through else 0.0

    fb, fs = fees["buy"], fees["sell"]
    res = {"filled": False, "outcome": "BATAL", "ret": 0.0, "days": 0, "entry_pos": None,
           "entry_px": None, "exit_pos": signal_pos, "exit_px": None, "tp1_hit": False}
    sl, tp1, tp2 = plan["sl"], plan["tp1"], plan["tp2"]
    mode = plan.get("entry_mode") or "open"
    if not isinstance(mode, str):
        mode = "open"
    max_hold = int(_num(plan.get("max_hold_days"), 10))
    first = signal_pos + 1
    if first >= n:
        res["outcome"] = "MENUNGGU"
        return res

    # ---------------- entry
    e, entry = None, None
    if mode == "limit":
        limit = plan["entry"]
        last = min(n - 1, signal_pos + int(_num(plan.get("limit_days"), 3)))
        for j in range(first, last + 1):
            if o[j] <= sl:                       # gap turun menembus SL -> batal
                res["exit_pos"] = j
                return res
            if o[j] <= limit:
                e, entry = j, o[j]
                break
            if l[j] <= limit - thr(limit):
                e, entry = j, limit
                break
        if e is None:
            if last < signal_pos + int(_num(plan.get("limit_days"), 3)):
                res["outcome"] = "MENUNGGU"
            res["exit_pos"] = last
            return res
    else:
        if o[first] > plan["entry_high"] or o[first] <= sl:
            res["exit_pos"] = first
            return res
        e, entry = first, buy_px(o[first])

    # ---------------- kelola posisi
    tp1_hit, part1, tp1_pos = False, None, None      # part1/tp1_pos = penjualan separuh pertama (TP1 atau pasar)
    mx = plan.get("market_exit") or "none"
    if not isinstance(mx, str) or mkt_exit is None:
        mx = "none"
    mkt_half = False
    exit_px, outcome, j = None, None, e
    pending, blocked = None, 0                        # jual tertunda karena saham terkunci ARB
    for j in range(e, n):
        if pending is not None:
            if lock_o is not None and lock_o[j]:
                blocked += 1
                continue
            exit_px, outcome = sell_px(o[j]), pending
            break
        if l[j] <= sl:                         # termasuk hari masuk (asumsi terburuk)
            out_ = "BE" if tp1_hit else "SL"
            if j > e and o[j] <= sl:                    # dibuka di bawah SL (gap turun)
                if lock_o is not None and lock_o[j]:    # sejak pagi terkunci ARB -> tidak bisa jual
                    pending, blocked = out_, blocked + 1
                    continue
                exit_px = sell_px(o[j])
            else:
                exit_px = sell_px(sl, k_slip)
            outcome = out_
            break
        if not tp1_hit and h[j] >= tp1 + thr(tp1):
            if part1 is None:
                part1, tp1_pos = tp1, j
            tp1_hit, sl = True, max(sl, entry)
        if h[j] >= tp2 + thr(tp2):
            exit_px, outcome = tp2, "TP2"
            break
        locked = lock_c is not None and lock_c[j]
        close_exit = None
        if tp1_hit and trail_line is not None and c[j] < trail_line[j]:
            close_exit = "TRAIL"
        elif mx != "none" and mkt_exit[j]:
            if mx == "all":
                close_exit = "MKT"
            elif part1 is None and not locked:          # "half": jual separuh sekali
                part1, tp1_pos, mkt_half = sell_px(c[j]), j, True
        if close_exit is None and j - e + 1 >= max_hold:
            close_exit = "TIME"
        if close_exit is not None:
            if locked:                                  # close terkunci ARB -> jual besok pagi
                pending, blocked = close_exit, blocked + 1
                continue
            exit_px, outcome = sell_px(c[j]), close_exit
            break
    if exit_px is None:                        # data habis -> posisi masih terbuka
        exit_px, outcome, j = c[n - 1], "OPEN", n - 1

    def net(px):
        return px * (1 - fs) / (entry * (1 + fb)) - 1

    ret = 0.5 * net(part1) + 0.5 * net(exit_px) if part1 is not None else net(exit_px)
    if mkt_half:
        outcome = "MKT½+" + outcome
    elif tp1_hit and outcome in ("BE", "TIME", "OPEN", "TRAIL", "MKT"):
        outcome = "TP1+" + outcome
    res.update({"filled": True, "outcome": outcome, "ret": float(ret), "days": j - e + 1,
                "entry_pos": e, "entry_px": float(entry), "exit_pos": j, "exit_px": float(exit_px),
                "tp1_hit": tp1_hit, "tp1_pos": tp1_pos, "tp1_px": part1, "arb_blocked": blocked})
    return res


def simulate(df: pd.DataFrame, signal_pos: int, plan: dict, fees: dict, bench: pd.Series | None = None,
             exec_cfg: dict | None = None) -> dict:
    """Versi DataFrame (untuk tracker). `bench` (IHSG) dibutuhkan untuk aturan keluar saat pasar berbalik."""
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close"))
    tm = int(_num(plan.get("trail_ma"), 0))
    trail = ema_np(c, tm) if tm > 0 else None
    mkt = None
    mx = plan.get("market_exit")
    if isinstance(mx, str) and mx != "none" and bench is not None and len(bench):
        ma = plan.get("market_exit_ma") if isinstance(plan.get("market_exit_ma"), str) else "sma50"
        mkt = market_flag(bench_up(bench, ma, df.index), int(_num(plan.get("market_exit_confirm"), 1)))
    ex = exec_arrays(df.index, o, h, l, c, exec_cfg)
    r = simulate_arr(o, h, l, c, signal_pos, plan, fees, trail, mkt, ex)
    r["entry_date"] = df.index[r["entry_pos"]] if r["entry_pos"] is not None else None
    r["exit_date"] = df.index[r["exit_pos"]] if r["filled"] else None
    return r
