"""Pengambilan data harian dari sumber terbuka/publik.

Sumber:
  1. Harga OHLCV, jumlah saham & fundamental  -> Yahoo Finance via `yfinance`
     (library open source, lisensi Apache-2.0; data publik gratis, sufiks `.JK` untuk BEI)
  2. Daftar emiten + jumlah saham tercatat     -> endpoint publik idx.co.id
     (cadangan: data/tickers_seed.csv bila situs IDX memblokir permintaan otomatis)
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .utils import ROOT, dump_json, fnum, load_json, log

CACHE = ROOT / "data" / "cache"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def jk(code: str) -> str:
    return code if code.startswith("^") or code.endswith(".JK") else f"{code}.JK"


def code_of(ticker: str) -> str:
    return ticker.replace(".JK", "")


# ------------------------------------------------------------------ daftar emiten IDX
def fetch_idx_list(timeout: int = 25) -> pd.DataFrame | None:
    """Daftar seluruh saham tercatat dari situs BEI (kode, nama, jumlah saham, papan)."""
    url = "https://www.idx.co.id/primary/StockData/GetSecuritiesStock"
    params = {"start": 0, "length": 9999, "code": "", "sector": "", "board": "", "language": "id-id"}
    headers = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
               "Referer": "https://www.idx.co.id/id/data-pasar/data-saham/daftar-saham/"}
    try:
        try:
            import cloudscraper  # menembus proteksi Cloudflare dasar
            sess = cloudscraper.create_scraper()
        except ImportError:
            import requests
            sess = requests.Session()
        r = sess.get(url, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        js = r.json()
        rows = js.get("data") or js.get("Data") or []
        recs = []
        for row in rows:
            code = row.get("Code") or row.get("KodeEmiten") or row.get("code")
            if not code:
                continue
            recs.append({
                "code": str(code).strip().upper(),
                "name": (row.get("Name") or row.get("NamaEmiten") or "").strip(),
                "shares": fnum(row.get("Shares") or row.get("JumlahSaham")),
                "board": (row.get("ListingBoard") or row.get("PapanPencatatan") or "").strip(),
            })
        df = pd.DataFrame(recs)
        if len(df) < 300:          # respons tidak wajar
            log.warning("Daftar IDX hanya %d baris, diabaikan", len(df))
            return None
        dump_json(df.to_dict("records"), CACHE / "idx_list.json")
        log.info("Daftar emiten IDX: %d saham", len(df))
        return df
    except Exception as e:  # noqa: BLE001
        log.warning("Gagal mengambil daftar IDX (%s). Pakai cache/seed.", e.__class__.__name__)
        cached = load_json(CACHE / "idx_list.json")
        return pd.DataFrame(cached) if cached else None


# ------------------------------------------------------------------ harga
def _normalize(sub: pd.DataFrame) -> pd.DataFrame | None:
    cols = ["Open", "High", "Low", "Close", "Volume"]
    if not set(cols).issubset(sub.columns):
        return None
    sub = sub[cols].dropna(subset=["Open", "High", "Low", "Close"]).copy()
    idx = pd.to_datetime(sub.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    sub.index = idx.normalize()
    sub = sub[~sub.index.duplicated(keep="last")].sort_index()
    sub["Volume"] = sub["Volume"].fillna(0)
    return sub if len(sub) >= 60 else None


def download_prices(tickers: list[str], period: str = "3y", chunk: int = 60) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    tickers = [jk(t) for t in tickers]
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        raw = None
        for attempt in range(4):
            try:
                raw = yf.download(batch, period=period, interval="1d", auto_adjust=True,
                                  group_by="ticker", threads=True, progress=False)
                break
            except Exception as e:  # noqa: BLE001  (rate limit dsb.)
                wait = 10 * (attempt + 1)
                log.warning("Unduh batch %d gagal (%s), coba lagi %ds", i // chunk + 1, e, wait)
                time.sleep(wait)
        if raw is None or raw.empty:
            continue
        for t in batch:
            try:
                sub = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            except KeyError:
                continue
            norm = _normalize(sub)
            if norm is not None:
                out[t] = norm
        log.info("Harga: batch %d/%d selesai (%d ticker valid)", i // chunk + 1,
                 (len(tickers) - 1) // chunk + 1, len(out))
        time.sleep(1.0)
    return out


# ------------------------------------------------------------------ jumlah saham & fundamental
def _fresh(entry: dict | None, days: int) -> bool:
    if not entry or "ts" not in entry:
        return False
    try:
        return datetime.fromisoformat(entry["ts"]) > datetime.now() - timedelta(days=days)
    except ValueError:
        return False


def get_shares(tickers: list[str], max_age_days: int = 7) -> dict[str, float]:
    """Jumlah saham beredar (fast_info), di-cache mingguan."""
    import yfinance as yf

    path = CACHE / "shares.json"
    cache = load_json(path, {}) or {}
    todo = [t for t in tickers if not _fresh(cache.get(t), max_age_days)]
    if todo:
        log.info("Ambil jumlah saham %d ticker (cache %d)", len(todo), len(tickers) - len(todo))
    for n, t in enumerate(todo, 1):
        shares = None
        try:
            fi = yf.Ticker(t).fast_info
            try:
                shares = fi["shares"]
            except Exception:  # noqa: BLE001
                shares = getattr(fi, "shares", None)
        except Exception:  # noqa: BLE001
            pass
        if fnum(shares):
            cache[t] = {"shares": float(shares), "ts": datetime.now().isoformat(timespec="seconds")}
        if n % 25 == 0:
            dump_json(cache, path)
            time.sleep(1)
    dump_json(cache, path)
    return {t: cache[t]["shares"] for t in tickers if t in cache}


FUND_VERSION = 3


def _clean_fund(f: dict) -> dict:
    """Saring nilai fundamental Yahoo yang tidak masuk akal.

    - PBV: untuk emiten yang melapor dalam USD (batu bara, mineral, petrokimia) Yahoo membagi harga
      Rupiah dengan nilai buku USD sehingga PBV bisa ribuan kali -> dianggap tidak tersedia.
    - PER: di atas 500x atau negatif ekstrem -> tidak tersedia.
    - Dividend yield: yfinance >= 0.2.54 memberi angka PERSEN (7,7 = 7,7%) -> selalu dibagi 100.
    """
    f = dict(f)
    pb, pe = f.get("pb"), f.get("pe")
    if pb is not None and (pb <= 0 or pb > 40):
        f["pb"] = None
    if pe is not None and (pe > 500 or pe < -500):
        f["pe"] = None
    dy = f.get("div_yield_raw")
    f["div_yield"] = dy / 100 if dy is not None else None
    if f["div_yield"] is not None and f["div_yield"] > 0.25:   # >25% hampir pasti data salah
        f["div_yield"] = None
    return f


def discover_by_screener(min_mcap: float) -> list[str]:
    """Daftar saham BEI dari screener Yahoo (cadangan bila situs IDX memblokir runner)."""
    import yfinance as yf
    from yfinance import EquityQuery

    q = EquityQuery("and", [EquityQuery("eq", ["region", "id"]),
                            EquityQuery("gte", ["intradaymarketcap", min_mcap * 0.7])])
    found: list[str] = []
    for offset in range(0, 1000, 250):
        try:
            r = yf.screen(q, offset=offset, size=250, sortField="intradaymarketcap", sortAsc=False)
        except Exception as e:  # noqa: BLE001
            log.warning("Screener Yahoo gagal (%s)", e.__class__.__name__)
            break
        quotes = (r or {}).get("quotes", [])
        found += [x["symbol"] for x in quotes if str(x.get("symbol", "")).endswith(".JK")]
        if len(quotes) < 250:
            break
    log.info("Screener Yahoo: %d saham BEI ditemukan", len(found))
    return found


def get_fundamentals(tickers: list[str], max_age_days: int = 7) -> dict[str, dict]:
    import yfinance as yf

    path = CACHE / "fundamentals.json"
    cache = load_json(path, {}) or {}
    todo = [t for t in tickers if not _fresh(cache.get(t), max_age_days)
            or cache[t].get("v") != FUND_VERSION]
    if todo:
        log.info("Ambil fundamental %d ticker (cache %d)", len(todo), len(tickers) - len(todo))
    for n, t in enumerate(todo, 1):
        try:
            info = yf.Ticker(t).info or {}
        except Exception as e:  # noqa: BLE001
            log.debug("info %s gagal: %s", t, e)
            continue
        der = fnum(info.get("debtToEquity"))
        cache[t] = {
            "name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector") or "Lainnya",
            "industry": info.get("industry"),
            "pe": fnum(info.get("trailingPE")),
            "pb": fnum(info.get("priceToBook")),
            "roe": fnum(info.get("returnOnEquity")),
            "der": der / 100 if der is not None else None,       # Yahoo: dalam persen
            "div_yield_raw": fnum(info.get("dividendYield")),
            "eps_ttm": fnum(info.get("trailingEps")),
            "bvps": fnum(info.get("bookValue")),
            "fin_currency": info.get("financialCurrency"),
            "v": FUND_VERSION,
            "eps_growth": fnum(info.get("earningsGrowth")),
            "rev_growth": fnum(info.get("revenueGrowth")),
            "shares": fnum(info.get("sharesOutstanding")),
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        if n % 20 == 0:
            dump_json(cache, path)
        time.sleep(0.4)
    dump_json(cache, path)
    return {t: _clean_fund(cache[t]) for t in tickers if t in cache}


# ------------------------------------------------------------------ mode demo (offline)
def demo_dataset(n: int = 45, days: int = 760, seed: int = 7):
    """Data sintetis untuk uji coba tanpa internet. BUKAN data pasar asli."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    sectors = ["Financial Services", "Consumer Defensive", "Energy", "Basic Materials",
               "Communication Services", "Real Estate", "Industrials", "Healthcare"]
    market = np.cumsum(rng.normal(0.0003, 0.009, days))
    prices, funds, shares = {}, {}, {}
    for i in range(n):
        beta = rng.uniform(0.6, 1.4)
        drift = rng.normal(0.0002, 0.0006)
        vol = rng.uniform(0.012, 0.03)
        regime = np.repeat(rng.normal(0, 0.0015, days // 60 + 1), 60)[:days]
        r = beta * np.diff(np.r_[0, market]) + drift + regime + rng.normal(0, vol, days)
        p0 = rng.choice([150, 400, 900, 1800, 3500, 6000, 9000])
        close = p0 * np.exp(np.cumsum(r))
        openp = close * np.exp(rng.normal(0, vol / 3, days))
        high = np.maximum(openp, close) * (1 + np.abs(rng.normal(0, vol / 2, days)))
        low = np.minimum(openp, close) * (1 - np.abs(rng.normal(0, vol / 2, days)))
        volu = rng.lognormal(16, 0.5, days) * (1 + 3 * (np.abs(r) > 2 * vol))
        t = f"DMO{i + 1:02d}.JK"
        prices[t] = pd.DataFrame({"Open": openp, "High": high, "Low": low, "Close": close,
                                  "Volume": volu.round()}, index=dates)
        shares[t] = float(rng.uniform(1e9, 1.2e11))
        sec = sectors[i % len(sectors)]
        funds[t] = {"name": f"Emiten Demo {i + 1:02d}", "sector": sec, "industry": None,
                    "pe": float(rng.uniform(4, 35)), "pb": float(rng.uniform(0.5, 5)),
                    "roe": float(rng.uniform(-0.05, 0.3)),
                    "der": float(rng.uniform(0.1, 2.5)) if sec != "Financial Services" else None,
                    "div_yield": float(rng.uniform(0, 0.08)), "eps_growth": float(rng.normal(0.08, 0.2)),
                    "rev_growth": None, "shares": shares[t]}
    bench = pd.Series(7000 * np.exp(market), index=dates, name="^JKSE")
    return prices, bench, shares, funds
