"""Penyaringan universe: kapitalisasi pasar >= Rp 5 T, likuid, dan masih aktif diperdagangkan."""
from __future__ import annotations

import pandas as pd

from .data import code_of, jk
from .utils import ROOT, log

SPECIAL_BOARDS = ("pemantauan", "watchlist", "special monitoring")


def candidate_list(cfg: dict, idx_df: pd.DataFrame | None,
                   extra: list[str] | None = None) -> tuple[list[str], dict, dict]:
    """Return (tickers .JK, shares_from_idx, names_from_idx). `extra` = hasil screener Yahoo."""
    ucfg = cfg["universe"]
    exclude = {c.upper() for c in ucfg.get("exclude", [])}
    shares, names = {}, {}
    if idx_df is not None and len(idx_df):
        df = idx_df.copy()
        board = df.get("board", pd.Series("", index=df.index)).fillna("").str.lower()
        df = df[~board.str.contains("|".join(SPECIAL_BOARDS))]     # buang papan pemantauan khusus
        codes = [c for c in df["code"] if c.isalpha() and len(c) == 4 and c not in exclude]
        for _, r in df.iterrows():
            t = jk(r["code"])
            if r.get("shares"):
                shares[t] = float(r["shares"])
            names[t] = r.get("name")
        src = "idx.co.id"
    else:
        seed = pd.read_csv(ROOT / ucfg["seed_file"])
        codes = [c.strip().upper() for c in seed["code"] if c.strip().upper() not in exclude]
        src = "seed list"
    extra = [e for e in (extra or []) if code_of(e).upper() not in exclude]
    if extra:
        src += f" + screener Yahoo ({len(set(map(jk, extra)) - set(map(jk, codes)))} tambahan)"
    tickers = sorted({jk(c) for c in codes} | {jk(e) for e in extra})
    log.info("Kandidat awal: %d saham (sumber: %s)", len(tickers), src)
    return tickers, shares, names


def filter_universe(prices: dict[str, pd.DataFrame], shares: dict[str, float], cfg: dict,
                    as_of: pd.Timestamp) -> pd.DataFrame:
    """Hitung market cap = jumlah saham x harga penutupan terakhir, lalu saring."""
    u = cfg["universe"]
    rows = []
    for t, df in prices.items():
        last = df.index[-1]
        close = float(df["Close"].iloc[-1])
        val20 = float((df["Close"] * df["Volume"]).tail(20).mean())
        sh = shares.get(t)
        mcap = sh * close if sh else None
        stale = (as_of - last).days
        reason = None
        if mcap is None:
            reason = "jumlah saham tidak tersedia"
        elif mcap < u["min_market_cap"]:
            reason = "market cap < batas"
        elif stale > u["max_stale_days"]:
            reason = f"tidak aktif {stale} hari (suspensi?)"
        elif val20 < u["min_avg_value_20d"]:
            reason = "kurang likuid"
        elif close < u["min_price"]:
            reason = "harga di bawah minimum"
        rows.append({"ticker": t, "code": code_of(t), "close": close, "mcap": mcap,
                     "avg_value_20d": val20, "last_date": last, "excluded": reason})
    uni = pd.DataFrame(rows)
    if uni.empty:
        return uni
    kept = uni[uni["excluded"].isna()].sort_values("mcap", ascending=False)
    log.info("Universe akhir: %d saham lolos (dari %d) | market cap >= Rp %.1f T",
             len(kept), len(uni), u["min_market_cap"] / 1e12)
    return kept.reset_index(drop=True)
