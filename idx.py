"""Klien data publik idx.co.id (Bursa Efek Indonesia).

- Ringkasan perdagangan harian per saham (GetStockSummary): harga, nilai transaksi, ForeignBuy/ForeignSell.
  Disimpan per tanggal di data/idx_summary/YYYYMMDD.csv; ~1 tahun diisi sekali di awal, lalu 1 hari per run.
- Net transaksi asing (dalam Rupiah) 5 & 20 hari per saham, untuk ditampilkan di dashboard/Telegram.

Situs IDX dilindungi Cloudflare: dari server cloud (mis. GitHub) biasanya diblokir, dari internet rumah
biasanya lolos. Bila diblokir, semua fungsi di sini mengembalikan None dan aplikasi tetap jalan tanpa data IDX.
"""
from __future__ import annotations

import time

import pandas as pd

from .utils import ROOT, log

BASE = "https://www.idx.co.id"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
DIR = ROOT / "data" / "idx_summary"
COLS = ["code", "close", "volume", "value", "foreign_buy", "foreign_sell"]
_SESSION = None
_BLOCKED = False


def _session():
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    try:                                             # meniru sidik TLS Chrome (paling sering lolos Cloudflare)
        from curl_cffi import requests as creq
        _SESSION = ("curl", creq.Session(impersonate="chrome"))
    except Exception:  # noqa: BLE001
        try:
            import cloudscraper
            _SESSION = ("cloudscraper", cloudscraper.create_scraper())
        except Exception:  # noqa: BLE001
            import requests
            _SESSION = ("requests", requests.Session())
    return _SESSION


def get_json(path: str, params: dict, referer: str, timeout: int = 25):
    """GET JSON dari idx.co.id; None bila gagal/diblokir (setelah gagal sekali, run ini tidak mencoba lagi)."""
    global _BLOCKED
    if _BLOCKED:
        return None
    kind, s = _session()
    headers = {"Accept": "application/json, text/plain, */*", "Referer": BASE + referer}
    if kind != "curl":
        headers["User-Agent"] = UA
    for attempt in range(2):
        try:
            r = s.get(BASE + path, params=params, headers=headers, timeout=timeout)
            if r.status_code == 200 and r.text.lstrip().startswith("{"):
                return r.json()
            log.debug("IDX %s -> HTTP %s", path, r.status_code)
        except Exception as e:  # noqa: BLE001
            log.debug("IDX %s gagal: %s", path, e)
        time.sleep(1.5)
    _BLOCKED = True
    log.warning("Situs IDX tidak bisa diakses dari jaringan ini (%s). Lanjut tanpa data IDX.", kind)
    return None


def blocked() -> bool:
    return _BLOCKED


# ------------------------------------------------------------------ ringkasan harian & transaksi asing
def _path(d: pd.Timestamp):
    return DIR / f"{d:%Y%m%d}.csv"


def fetch_summary(d: pd.Timestamp) -> pd.DataFrame | None:
    js = get_json("/primary/TradingSummary/GetStockSummary",
                  {"length": 9999, "start": 0, "date": f"{d:%Y%m%d}"},
                  "/id/data-pasar/ringkasan-perdagangan/ringkasan-saham/")
    if js is None:
        return None
    rows = js.get("data") or []
    df = pd.DataFrame([{"code": str(x.get("StockCode", "")).strip().upper(), "close": x.get("Close"),
                        "volume": x.get("Volume"), "value": x.get("Value"),
                        "foreign_buy": x.get("ForeignBuy"), "foreign_sell": x.get("ForeignSell")}
                       for x in rows], columns=COLS)
    DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(_path(d), index=False)                 # kosong = hari libur (tidak dicoba lagi)
    return df


def update_summaries(trading_days: pd.DatetimeIndex, backfill: int = 260, max_per_run: int = 300,
                     pause: float = 0.3) -> int:
    """Lengkapi arsip ringkasan harian untuk `backfill` hari bursa terakhir. Return jumlah hari baru."""
    days = sorted(pd.DatetimeIndex(trading_days).normalize().unique())[-backfill:]
    todo = [d for d in reversed(days) if not _path(d).exists()][:max_per_run]   # terbaru dulu
    if not todo:
        return 0
    log.info("Data IDX: mengambil ringkasan perdagangan %d hari (sekali di awal, berikutnya 1 hari/run)", len(todo))
    got = 0
    for i, d in enumerate(todo, 1):
        if fetch_summary(d) is None:
            break
        got += 1
        if i % 25 == 0:
            log.info("Data IDX: %d/%d hari", i, len(todo))
        time.sleep(pause)
    return got


def foreign_flow(codes: list[str], days: int = 60) -> dict[str, dict]:
    """Net beli asing (Rp) 5 & 20 hari terakhir per saham + porsinya terhadap nilai transaksi 20 hari."""
    files = sorted(DIR.glob("*.csv"))[-days:] if DIR.exists() else []
    if not files:
        return {}
    parts = []
    for f in files:
        try:
            df = pd.read_csv(f)
        except Exception:  # noqa: BLE001
            continue
        if len(df):
            df["date"] = pd.Timestamp(f.stem)
            parts.append(df)
    if not parts:
        return {}
    a = pd.concat(parts, ignore_index=True)
    a = a[a["code"].isin(codes)]
    a["net"] = (a["foreign_buy"].fillna(0) - a["foreign_sell"].fillna(0)) * a["close"].fillna(0)
    a = a.sort_values("date")
    out = {}
    for code, g in a.groupby("code"):
        g20, g5 = g.tail(20), g.tail(5)
        val20 = g20["value"].sum()
        out[code] = {"foreign_5d": float(g5["net"].sum()), "foreign_20d": float(g20["net"].sum()),
                     "foreign_20d_pct": float(g20["net"].sum() / val20) if val20 else None,
                     "foreign_days": int(len(g20)), "foreign_last": g["date"].max().strftime("%Y-%m-%d")}
    return out
