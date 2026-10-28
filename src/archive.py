"""Arsip data fundamental, agar suatu saat bagian jangka panjang bisa di-backtest.

1. Snapshot harian  -> data/fundamentals_history/daily_YYYY.csv
   Satu baris per saham per hari: harga, market cap, EPS, nilai buku/saham, PER, PBV, ROE, DER, yield, dll.
2. Laporan keuangan -> data/fundamentals_history/statements/<KODE>.csv
   Kuartalan & tahunan (pendapatan, laba bersih, EPS, ekuitas, utang, aset, kas, jumlah saham) dari Yahoo.
   Yahoo hanya memberi ~5 kuartal & ~4 tahun terakhir; dengan menyimpan setiap minggu dan menggabungkannya,
   histori akan terus bertambah. Kolom `first_seen` mencatat kapan angka itu pertama kali tersedia
   (penting agar backtest tidak memakai data yang belum terbit pada tanggal tersebut).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pandas as pd

from .utils import ROOT, dump_json, fnum, load_json, log

DIR = ROOT / "data" / "fundamentals_history"
ITEMS = {  # nama baris Yahoo (tanpa spasi, huruf kecil) -> nama kolom arsip
    "totalrevenue": "revenue", "operatingincome": "operating_income", "netincome": "net_income",
    "netincomecommonstockholders": "net_income_common", "dilutedeps": "eps_diluted", "basiceps": "eps_basic",
    "stockholdersequity": "equity", "totaldebt": "total_debt", "totalassets": "total_assets",
    "cashandcashequivalents": "cash", "ordinarysharesnumber": "shares",
}
DAILY_COLS = ["date", "code", "sector", "price", "mcap", "shares", "eps_ttm", "bvps", "pe", "pb", "roe", "der",
              "div_yield", "eps_growth", "rev_growth", "fin_currency"]


def snapshot_daily(as_of: pd.Timestamp, uni: pd.DataFrame, funds: dict[str, dict], shares: dict[str, float]):
    d = as_of.strftime("%Y-%m-%d")
    rows = []
    for r in uni.itertuples(index=False):
        f = funds.get(r.ticker, {}) or {}
        rows.append({"date": d, "code": r.code, "sector": f.get("sector"), "price": r.close, "mcap": r.mcap,
                     "shares": shares.get(r.ticker), "eps_ttm": f.get("eps_ttm"), "bvps": f.get("bvps"),
                     "pe": f.get("pe"), "pb": f.get("pb"), "roe": f.get("roe"), "der": f.get("der"),
                     "div_yield": f.get("div_yield"), "eps_growth": f.get("eps_growth"),
                     "rev_growth": f.get("rev_growth"), "fin_currency": f.get("fin_currency")})
    new = pd.DataFrame(rows, columns=DAILY_COLS)
    path = DIR / f"daily_{as_of.year}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = pd.read_csv(path, dtype={"date": str, "code": str})
        new = pd.concat([old[old["date"] != d], new], ignore_index=True)
    new.sort_values(["date", "code"]).to_csv(path, index=False)
    log.info("Arsip harian: %d saham -> %s", len(rows), path.name)


def _tidy(df: pd.DataFrame | None, freq: str) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    out = []
    for name, row in df.iterrows():
        key = ITEMS.get(str(name).replace(" ", "").lower())
        if not key:
            continue
        for period, val in row.items():
            v = fnum(val)
            if v is not None:
                out.append({"freq": freq, "period_end": pd.Timestamp(period).strftime("%Y-%m-%d"),
                            "item": key, "value": v})
    return pd.DataFrame(out)


def fetch_statements(ticker: str) -> pd.DataFrame:
    import yfinance as yf

    tk = yf.Ticker(ticker)
    parts = []
    for freq, yf_freq in (("Q", "quarterly"), ("A", "yearly")):
        for getter in (tk.get_income_stmt, tk.get_balance_sheet):
            try:
                parts.append(_tidy(getter(freq=yf_freq), freq))
            except Exception as e:  # noqa: BLE001
                log.debug("%s %s gagal: %s", ticker, getter.__name__, e)
    parts = [p for p in parts if len(p)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def merge_statements(code: str, fresh: pd.DataFrame, today: str):
    path = DIR / "statements" / f"{code}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = fresh.assign(first_seen=today, last_seen=today)
    if path.exists():
        old = pd.read_csv(path, dtype={"period_end": str, "first_seen": str, "last_seen": str})
        key = ["freq", "period_end", "item"]
        m = old.merge(fresh[key + ["value"]], on=key, how="outer", suffixes=("", "_new"), indicator=True)
        is_new = m["_merge"] == "right_only"
        m.loc[is_new, "value"] = m.loc[is_new, "value_new"]
        m.loc[is_new, "first_seen"] = today
        seen = m["_merge"] != "left_only"
        m.loc[seen, "last_seen"] = today
        revised = (m["_merge"] == "both") & (m["value_new"].notna()) & (m["value"] != m["value_new"])
        m.loc[revised, "value"] = m.loc[revised, "value_new"]          # revisi laporan: pakai angka terbaru
        fresh = m[key + ["value", "first_seen", "last_seen"]]
    fresh.sort_values(["freq", "period_end", "item"]).to_csv(path, index=False)


def update_statements(tickers: list[str], max_age_days: int = 7, max_per_run: int = 60):
    """Perbarui laporan keuangan secara bergilir (maks. `max_per_run` saham per hari, masing-masing mingguan)."""
    meta_path = DIR / "statements" / "_meta.json"
    meta = load_json(meta_path, {}) or {}
    cutoff = datetime.now() - timedelta(days=max_age_days)
    due = sorted([t for t in tickers if datetime.fromisoformat(meta.get(t, "2000-01-01")) < cutoff],
                 key=lambda t: meta.get(t, "2000-01-01"))[:max_per_run]
    today = datetime.now().strftime("%Y-%m-%d")
    ok = 0
    for t in due:
        df = fetch_statements(t)
        if len(df):
            merge_statements(t.replace(".JK", ""), df, today)
            ok += 1
        meta[t] = datetime.now().isoformat(timespec="seconds")
        time.sleep(0.5)
    if due:
        dump_json(meta, meta_path)
    log.info("Arsip laporan keuangan: %d/%d saham diperbarui (%d total terpantau)", ok, len(due), len(meta))
