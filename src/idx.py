"""Klien data publik idx.co.id (Bursa Efek Indonesia).

- Ringkasan perdagangan harian per saham (GetStockSummary): harga, nilai transaksi, ForeignBuy/ForeignSell.
  Disimpan per tanggal di data/idx_summary/YYYYMMDD.csv; ~1 tahun diisi sekali di awal, lalu 1 hari per run.
- Net transaksi asing (dalam Rupiah) 5 & 20 hari per saham, untuk ditampilkan di dashboard/Telegram.

Situs IDX dilindungi Cloudflare: dari server cloud (mis. GitHub) biasanya diblokir, dari internet rumah
biasanya lolos. Bila diblokir, semua fungsi di sini mengembalikan None dan aplikasi tetap jalan tanpa data IDX.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

import pandas as pd

from .utils import ROOT, dump_json, load_json, log

BASE = "https://www.idx.co.id"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0")
DIR = ROOT / "data" / "idx_summary"
STATE = ROOT / "data" / "cache" / "idx_access.json"
COLS = ["code", "close", "volume", "value", "foreign_buy", "foreign_sell"]
_BLOCKED = False
_WORKING: str | None = None
_SESS: dict = {}


# ------------------------------------------------------------------ cara-cara akses (dicoba berurutan)
def _looks_json(text: str) -> bool:
    return text.lstrip().startswith("{")


def _http_get(kind: str, url: str, referer: str, timeout: int):
    """Klien HTTP biasa (curl_cffi meniru browser / cloudscraper / requests). Return (json|None, keterangan)."""
    s = _SESS.get(kind)
    if s is None:
        if kind.startswith("curl_"):
            from curl_cffi import requests as creq
            s = creq.Session(impersonate=kind[5:])
        elif kind == "cloudscraper":
            import cloudscraper
            s = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "desktop": True})
        else:
            import requests
            s = requests.Session()
            s.headers["User-Agent"] = UA
        try:                                           # kunjungi beranda dulu: ambil cookie Cloudflare
            s.get(BASE + "/id", timeout=timeout)
        except Exception:  # noqa: BLE001
            pass
        _SESS[kind] = s
    headers = {"Accept": "application/json, text/plain, */*", "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
               "Referer": BASE + referer, "X-Requested-With": "XMLHttpRequest"}
    r = s.get(url, headers=headers, timeout=timeout)
    if r.status_code == 200 and _looks_json(r.text):
        return r.json(), "OK"
    snippet = re.sub(r"\s+", " ", r.text[:80])
    return None, f"HTTP {r.status_code}: {snippet}"


def _browser_exe() -> str | None:
    """Microsoft Edge (bawaan Windows) atau Chrome yang terpasang."""
    cands = [os.environ.get("IHSG_BROWSER")]
    if sys.platform.startswith("win"):
        for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
            if base:
                cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    cands += [shutil.which(x) for x in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser")]
    return next((c for c in cands if c and os.path.exists(c)), None)


def _browser_get(url: str, timeout: int):
    """Buka URL dengan browser asli tanpa jendela (headless) lalu ambil teks JSON-nya."""
    exe = _browser_exe()
    if not exe:
        return None, "browser Edge/Chrome tidak ditemukan"
    prof = ROOT / "data" / "cache" / "browser_profile"            # profil tetap: cookie Cloudflare tersimpan
    prof.mkdir(parents=True, exist_ok=True)
    cmd = [exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
           "--disable-extensions", "--disable-background-networking", "--disable-component-update",
           "--disable-sync", "--disable-default-apps", "--metrics-recording-only", "--mute-audio",
           f"--user-data-dir={prof}", f"--user-agent={UA}",
           "--virtual-time-budget=8000", "--timeout=25000", "--dump-dom", url]
    if hasattr(os, "geteuid") and os.geteuid() == 0:            # Linux sebagai root (server uji) butuh ini
        cmd.insert(1, "--no-sandbox")
    flags = 0x08000000 if sys.platform.startswith("win") else 0  # tanpa jendela hitam
    r = subprocess.run(cmd, capture_output=True, timeout=max(timeout, 45), creationflags=flags)
    dom = r.stdout.decode("utf-8", errors="replace")
    m = re.search(r"<pre[^>]*>(.*?)</pre>", dom, re.S)
    text = html.unescape(m.group(1) if m else re.sub(r"<[^>]+>", "", dom))
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(text[i:j + 1]), "OK"
        except ValueError:
            pass
    return None, "halaman bukan JSON (" + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", dom))[:80].strip() + ")"


METHODS = ["curl_chrome", "curl_safari", "curl_firefox", "cloudscraper", "requests", "browser"]


def _try(method: str, url: str, referer: str, timeout: int):
    try:
        if method == "browser":
            return _browser_get(url, timeout)
        return _http_get(method, url, referer, timeout)
    except Exception as e:  # noqa: BLE001
        return None, f"{e.__class__.__name__}: {str(e)[:80]}"


def _order() -> list[str]:
    st = load_json(STATE, {}) or {}
    ok = st.get("method")
    order = ([ok] if ok in METHODS else []) + [m for m in METHODS if m != ok]
    # cara yang gagal < 3 hari lalu dilewati (kecuali cara yang terakhir berhasil)
    fresh_fail = {m for m, t in (st.get("failed") or {}).items()
                  if datetime.fromisoformat(t) > datetime.now() - timedelta(days=3)}
    return [m for m in order if m == ok or m not in fresh_fail]


def get_json(path: str, params: dict, referer: str, timeout: int = 20):
    """GET JSON dari idx.co.id; None bila semua cara gagal (setelah itu run ini tidak mencoba lagi)."""
    global _BLOCKED, _WORKING
    if _BLOCKED:
        return None
    url = BASE + path + ("?" + urlencode(params) if params else "")
    methods = [_WORKING] if _WORKING else _order()
    notes = []
    for m in methods:
        js, why = _try(m, url, referer, timeout)
        if js is not None:
            if _WORKING != m:
                log.info("Akses IDX berhasil dengan cara: %s", m)
                st = load_json(STATE, {}) or {}
                st["method"] = m
                st.get("failed", {}).pop(m, None)
                dump_json(st, STATE)
            _WORKING = m
            return js
        notes.append(f"{m} → {why}")
        if _WORKING:                                     # cara yang tadinya berhasil mendadak gagal: coba semua
            _WORKING = None
            return get_json(path, params, referer, timeout)
    st = load_json(STATE, {}) or {}
    st.setdefault("failed", {}).update({n.split(" → ")[0]: datetime.now().isoformat(timespec="seconds") for n in notes})
    dump_json(st, STATE)
    _BLOCKED = True
    log.warning("Situs IDX tidak bisa diakses dari jaringan ini. Lanjut tanpa data IDX. Rincian: %s", " | ".join(notes))
    return None


def diagnose() -> list[tuple[str, bool, str]]:
    """Uji semua cara akses (untuk tombol 'Tes koneksi IDX')."""
    url = BASE + "/primary/StockData/GetSecuritiesStock?" + urlencode({"start": 0, "length": 5})
    out = []
    for m in METHODS:
        t0 = time.time()
        js, why = _try(m, url, "/id/data-pasar/data-saham/daftar-saham/", 20)
        out.append((m, js is not None, f"{why} ({time.time() - t0:.0f} dtk)"))
    ok = [m for m, good, _ in out if good]
    if ok:
        st = load_json(STATE, {}) or {}
        st["method"], st["failed"] = ok[0], {}
        dump_json(st, STATE)
    return out


def blocked() -> bool:
    return _BLOCKED


def working_method() -> str | None:
    return _WORKING


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
    from .utils import now_wib
    now = now_wib()
    recent = d.normalize() >= pd.Timestamp(now.date()) - pd.Timedelta(days=3)
    if (df.empty and recent) or (d.normalize() == pd.Timestamp(now.date()) and now.hour < 17):
        return df                                    # data hari ini/terbaru belum final: jangan disimpan
    DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(_path(d), index=False)                 # kosong = hari libur (tidak dicoba lagi)
    return df


def update_summaries(trading_days: pd.DatetimeIndex, backfill: int = 260, max_per_run: int = 300,
                     pause: float = 0.3) -> int:
    """Lengkapi arsip ringkasan harian untuk `backfill` hari bursa terakhir. Return jumlah hari baru."""
    days = sorted(pd.DatetimeIndex(trading_days).normalize().unique())[-backfill:]
    todo = [d for d in reversed(days) if not _path(d).exists()]                  # terbaru dulu
    if not todo:
        return 0
    if fetch_summary(todo[0]) is None:                   # cek akses sekali (sekaligus memilih cara akses)
        return 0
    if _WORKING == "browser":                            # lewat browser lebih lambat: cicil 40 hari per run
        max_per_run = min(max_per_run, 40)
    todo = todo[1:max_per_run]
    if not todo:
        return 1
    remaining = len([d for d in days if not _path(d).exists()]) - len(todo)
    log.info("Data IDX (cara: %s): mengambil ringkasan perdagangan %d hari%s", _WORKING, len(todo) + 1,
             f"; sisa {remaining} hari riwayat dilanjutkan pada update berikutnya" if remaining > 0 else "")
    got = 1
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
