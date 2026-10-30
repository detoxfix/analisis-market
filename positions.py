"""Pemantau posisi pribadi.

Anda mencatat saham yang benar-benar dibeli di `positions.csv` (root repo, private). Setiap hari aplikasi
mengecek harga sejak tanggal beli dan memberi instruksi per posisi:
  JUAL SEMUA  : cut loss tersentuh, TP2 tercapai, time-stop, atau aturan keluar pasar ("all")
  JUAL 50%    : TP1 tercapai (atau aturan keluar pasar "half") dan Anda belum menandai tp1_done
  WASPADA     : sinyal horizon itu sekarang SELL / STRONG SELL
  TAHAN       : semua aman; ditampilkan jarak ke SL & TP

Kolom positions.csv:
  code, horizon (pendek/menengah/panjang), buy_date (YYYY-MM-DD), buy_price, lots,
  tp1_done (ya/kosong), sl, tp1, tp2 (opsional: isi untuk memakai level sendiri), note
Baris yang diawali # diabaikan. Hapus barisnya setelah posisi dijual habis.
"""
from __future__ import annotations

import re

import pandas as pd

from .data import jk
from .indicators import add_indicators
from .risk import make_plan
from .sim import market_flag
from .utils import ROOT, fnum, log, round_tick

COLS = ["code", "horizon", "buy_date", "buy_price", "lots", "tp1_done", "sl", "tp1", "tp2", "note"]
H_ALIAS = {"pendek": "short", "short": "short", "swing": "short", "menengah": "medium", "medium": "medium",
           "panjang": "long", "long": "long", "investasi": "long"}
H_LABEL = {"short": "pendek", "medium": "menengah", "long": "panjang"}
YES = {"ya", "y", "yes", "1", "true", "sudah", "v", "x"}

TEMPLATE = """code,horizon,buy_date,buy_price,lots,tp1_done,sl,tp1,tp2,note
# Contoh (hapus tanda # di depan untuk mengaktifkan, satu baris = satu posisi):
# BBCA,pendek,2026-10-29,4900,10,,,,,beli dari sinyal swing
# ASII,menengah,2026-10-29,4630,5,ya,,,,sudah jual separuh di TP1
# PTBA,panjang,2026-10-29,3250,7,,2900,,,cut loss pakai level sendiri
"""


def _num(x) -> float | None:
    """'4900', '4.900', '4,900', '4900.0' -> 4900.0 ; kosong -> None."""
    if x is None:
        return None
    t = str(x).strip()
    if not t or t.lower() == "nan":
        return None
    if re.fullmatch(r"\d+[.,]\d{1,2}", t):          # desimal (mis. 4900.0)
        return float(t.replace(",", "."))
    digits = re.sub(r"[^\d]", "", t)               # pemisah ribuan
    return float(digits) if digits else None


def load(path=None) -> tuple[pd.DataFrame, list[str]]:
    path = path or ROOT / "positions.csv"
    if not path.exists():
        path.write_text(TEMPLATE, encoding="utf-8")
        return pd.DataFrame(columns=COLS), []
    try:
        df = pd.read_csv(path, comment="#", dtype=str, skip_blank_lines=True).fillna("")
    except Exception as e:  # noqa: BLE001
        return pd.DataFrame(columns=COLS), [f"positions.csv tidak bisa dibaca: {e}"]
    df.columns = [c.strip().lower() for c in df.columns]
    for c in COLS:
        if c not in df.columns:
            df[c] = ""
    errs, rows = [], []
    for i, r in df.iterrows():
        code = str(r["code"]).strip().upper().replace(".JK", "")
        if not code:
            continue
        h = H_ALIAS.get(str(r["horizon"]).strip().lower())
        price, lots = _num(r["buy_price"]), _num(r["lots"])
        try:
            date = pd.Timestamp(str(r["buy_date"]).strip())
        except Exception:  # noqa: BLE001
            date = None
        if not h or not price or date is None or pd.isna(date):
            errs.append(f"Baris {i + 2} ({code}): horizon/tanggal/harga beli tidak valid")
            continue
        rows.append({"code": code, "horizon": h, "buy_date": date.normalize(), "buy_price": price,
                     "lots": int(lots) if lots else 0,
                     "tp1_done": str(r["tp1_done"]).strip().lower() in YES,
                     "sl_user": _num(r["sl"]), "tp1_user": _num(r["tp1"]), "tp2_user": _num(r["tp2"]),
                     "note": str(r["note"]).strip()})
    return pd.DataFrame(rows), errs


def codes(pos: pd.DataFrame) -> list[str]:
    return sorted({jk(c) for c in pos["code"]}) if len(pos) else []


def _fmt_date(t) -> str:
    return pd.Timestamp(t).strftime("%d-%m-%Y")


def _rp(x) -> str:
    return f"{x:,.0f}".replace(",", ".")


def evaluate(pos: pd.DataFrame, prices: dict, bench: pd.Series, cfg: dict, signals: dict,
             as_of: pd.Timestamp) -> list[dict]:
    fb, fs = cfg["fees"]["buy"], cfg["fees"]["sell"]
    out = []
    for r in pos.itertuples(index=False):
        t = jk(r.code)
        base = {"code": r.code, "horizon": r.horizon, "buy_date": r.buy_date.strftime("%Y-%m-%d"),
                "buy_price": r.buy_price, "lots": r.lots, "tp1_done": r.tp1_done, "note": r.note}
        df = prices.get(t)
        if df is None or len(df) < 30:
            out.append({**base, "status": "DATA", "rank": 9, "action": "Data harga tidak tersedia (cek kode saham)"})
            continue
        d = add_indicators(df, bench)
        hcfg = cfg["horizons"][r.horizon]
        p0 = d.index.get_indexer([r.buy_date], method="pad")[0]
        p0 = max(p0, 0)
        row = d.iloc[p0].to_dict()
        row["Close"] = r.buy_price
        plan = make_plan(row, r.horizon, {**hcfg, "entry_mode": "open"}, cfg["fees"], texts=False) or {}
        sl0 = fnum(r.sl_user) or plan.get("sl") or round_tick(r.buy_price * 0.9, "down")
        tp1 = fnum(r.tp1_user) or plan.get("tp1")
        tp2 = fnum(r.tp2_user) or plan.get("tp2")
        sl = sl0

        mx = hcfg.get("market_exit") or "none"
        mflag = None
        if mx != "none":
            col = f"MKT_{hcfg.get('market_exit_ma') or 'sma50'}"
            if col in d:
                mflag = market_flag(d[col].to_numpy(dtype=float), int(hcfg.get("market_exit_confirm") or 1))

        hi, lo, cl = (d[k].to_numpy(dtype=float) for k in ("High", "Low", "Close"))
        dates = d.index
        n = len(d)
        half_at, half_why, final, final_why = None, None, None, None
        half_done = r.tp1_done
        tp1_seen = False
        for j in range(p0 + 1, n):
            if lo[j] <= sl:
                final = j
                final_why = (f"harga menyentuh cut loss {_rp(sl)}" if sl < r.buy_price
                             else f"harga turun kembali ke harga beli {_rp(sl)} (cut loss impas setelah TP1)")
                break
            if tp1 and hi[j] >= tp1 and not tp1_seen:
                tp1_seen, sl = True, max(sl, r.buy_price)           # setelah TP1, cut loss naik ke harga beli
                if half_at is None and not r.tp1_done:
                    half_at, half_why = j, f"TP1 {_rp(tp1)} tercapai"
            if tp2 and hi[j] >= tp2:
                final, final_why = j, f"TP2 {_rp(tp2)} tercapai"
                break
            if mflag is not None and mflag[j]:
                ma = (hcfg.get("market_exit_ma") or "sma50").upper()
                if mx == "all":
                    final, final_why = j, f"IHSG close di bawah {ma} (aturan keluar pasar)"
                    break
                if half_at is None and not half_done:
                    half_at, half_why = j, f"IHSG close di bawah {ma} (aturan keluar pasar)"
            if j - p0 >= hcfg["hold_max_days"]:
                final, final_why = j, f"batas waktu hold {hcfg['hold_max_days']} hari bursa"
                break

        price = float(cl[-1])
        days = n - 1 - p0
        pnl = price * (1 - fs) / (r.buy_price * (1 + fb)) - 1
        sig = (signals.get(r.code) or {}).get(r.horizon) or {}
        def when(j):
            k = n - 1 - j
            return (f"hari ini ({_fmt_date(dates[j])})" if k == 0
                    else f"pada {_fmt_date(dates[j])}, {k} hari bursa lalu — segera eksekusi")
        if final is not None:
            status, rank = "JUAL SEMUA", 0
            action = f"Jual seluruh sisa posisi: {final_why} {when(final)}."
        elif half_at is not None:
            status, rank = "JUAL 50%", 1
            action = (f"Jual 50% posisi: {half_why} {when(half_at)}. "
                      + (f"Cut loss sisa posisi naik ke harga beli {_rp(r.buy_price)}. " if tp1_seen else "")
                      + "Setelah dijual, isi tp1_done = ya di positions.csv.")
        elif sig.get("signal") in ("STRONG SELL", "SELL"):
            status, rank = "WASPADA", 2
            action = (f"Sinyal {H_LABEL[r.horizon]} sekarang {sig['signal']} (skor {sig.get('score', 0):.0f}). "
                      + ("Pertimbangkan jual seluruh posisi." if sig["signal"] == "STRONG SELL"
                         else "Pertimbangkan kurangi posisi; tetap disiplin pada cut loss."))
        else:
            status, rank = "TAHAN", 3
            action = f"Tahan. Cut loss {_rp(sl)}" + (f", target TP1 {_rp(tp1)}" if tp1 and not tp1_seen
                                                    else f", target TP2 {_rp(tp2)}" if tp2 else "") + "."
        out.append({**base, "status": status, "rank": rank, "action": action, "price": price,
                    "chg_1d": fnum(d["CHG_1D"].iloc[-1]), "pnl_pct": pnl,
                    "pnl_value": (price * (1 - fs) - r.buy_price * (1 + fb)) * 100 * r.lots if r.lots else None,
                    "value": price * 100 * r.lots if r.lots else None,
                    "sl": sl, "tp1": tp1, "tp2": tp2, "sl_dist": sl / price - 1,
                    "tp1_dist": (tp1 / price - 1) if tp1 else None, "tp2_dist": (tp2 / price - 1) if tp2 else None,
                    "days": int(days), "max_days": int(hcfg["hold_max_days"]),
                    "signal": sig.get("signal"), "score": sig.get("score")})
    out.sort(key=lambda x: (x["rank"], x["code"]))
    if out:
        log.info("Posisi pribadi: %d (%s)", len(out),
                 ", ".join(f"{s}: {sum(1 for x in out if x['status'] == s)}"
                           for s in ("JUAL SEMUA", "JUAL 50%", "WASPADA", "TAHAN", "DATA")
                           if any(x["status"] == s for x in out)))
    return out


def public_view(items: list[dict], mode: str) -> list[dict] | None:
    """Versi untuk dashboard publik. mode: full | percent (tanpa lot & nominal) | hidden."""
    if mode == "hidden":
        return None
    if mode == "full":
        return items
    drop = ("lots", "pnl_value", "value", "note")
    return [{k: v for k, v in x.items() if k not in drop} for x in items]
