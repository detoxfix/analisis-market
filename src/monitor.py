"""Alarm penyimpangan: apakah hasil rekomendasi SUNGGUHAN (track record) masih sesuai perkiraan backtest?

Untuk tiap horizon dibandingkan transaksi yang sudah selesai dengan distribusi hasil backtest
(periode out-of-sample bila cukup sampelnya):
  - rata-rata return per transaksi  -> uji z: (rata live - rata backtest) / (std backtest / sqrt(n))
  - win rate                         -> uji z binomial
  - rentetan rugi terpanjang         -> peluang rentetan sepanjang itu terjadi dalam n transaksi
Hasil dihitung untuk semua transaksi live dan untuk 20 transaksi terakhir (deteksi memburuk baru-baru ini).

Status: BELUM CUKUP DATA · NORMAL · LEBIH BAIK · WASPADA · BAHAYA.
Alarm hanya MEMBERI TAHU; tidak mengubah parameter apa pun.
"""
from __future__ import annotations

import math

HZ = {"short": "Pendek", "medium": "Menengah", "long": "Panjang"}


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def streak_prob(n: int, k: int, q: float) -> float:
    """Peluang ada rentetan >= k rugi berturut-turut dalam n transaksi (peluang rugi q per transaksi)."""
    if k <= 0:
        return 1.0
    if k > n or q <= 0:
        return 0.0
    # dp[j] = peluang belum pernah ada rentetan k, dengan rentetan rugi saat ini = j
    dp = [1.0] + [0.0] * (k - 1)
    hit = 0.0
    for _ in range(n):
        new = [0.0] * k
        for j, pj in enumerate(dp):
            if not pj:
                continue
            new[0] += pj * (1 - q)
            if j + 1 >= k:
                hit += pj * q
            else:
                new[j + 1] += pj * q
        dp = new
    return min(1.0, hit)


def _longest_losses(rets: list[float]) -> int:
    best = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        best = max(best, cur)
    return best


def _check(rets: list[float], exp: dict, warn: float, danger: float) -> dict:
    n = len(rets)
    m = sum(rets) / n
    w = sum(r > 0 for r in rets) / n
    mu, sd, p = exp["avg_ret"], exp.get("std_ret") or 0.0, exp["win_rate"]
    z_m = (m - mu) / (sd / math.sqrt(n)) if sd > 0 else 0.0
    z_w = (w - p) / math.sqrt(p * (1 - p) / n) if 0 < p < 1 else 0.0
    k = _longest_losses(rets)
    p_k = streak_prob(n, k, 1 - p) if k >= 3 else 1.0
    worst_z = min(z_m, z_w)
    if worst_z <= -danger or p_k < 0.01:
        level = "BAHAYA"
    elif worst_z <= -warn or p_k < 0.05:
        level = "WASPADA"
    elif z_m >= warn:
        level = "LEBIH BAIK"
    else:
        level = "NORMAL"
    return {"n": n, "avg_ret": m, "win_rate": w, "z_mean": z_m, "z_win": z_w, "p_mean": _phi(z_m),
            "p_win": _phi(z_w), "loss_streak": k, "p_streak": p_k, "level": level}


RANK = {"BAHAYA": 0, "WASPADA": 1, "NORMAL": 2, "LEBIH BAIK": 3}


def check(track: dict, backtest: dict | None, cfg: dict) -> dict:
    """track = hasil tracker.summarize (berisi closed_rets); backtest = isi backtest.json."""
    mcfg = cfg.get("monitor", {}) or {}
    min_n = int(mcfg.get("min_trades", 10))
    recent_n = int(mcfg.get("recent_trades", 20))
    warn, danger = float(mcfg.get("warn_z", 1.65)), float(mcfg.get("danger_z", 2.33))
    results = (backtest or {}).get("results") or {}
    out = {"horizons": {}, "min_trades": min_n}
    for h, closed in (track.get("closed_rets") or {}).items():
        bt = results.get(h)
        rets = [float(r) for _, r in closed if r is not None and math.isfinite(float(r))]
        item = {"label": HZ.get(h, h), "n": len(rets)}
        if not bt or not bt.get("n"):
            item.update(level="TANPA PEMBANDING",
                        text="Horizon ini tidak di-backtest, jadi tidak ada perkiraan untuk dibandingkan.")
            out["horizons"][h] = item
            continue
        oos = bt.get("out_sample") or {}
        exp = oos if (oos.get("n") or 0) >= 30 and oos.get("std_ret") is not None else bt
        if exp.get("std_ret") is None:
            item.update(level="TANPA PEMBANDING", text="Backtest lama belum punya data sebaran; tunggu backtest berikutnya.")
            out["horizons"][h] = item
            continue
        item["expected"] = {"avg_ret": exp["avg_ret"], "win_rate": exp["win_rate"], "std_ret": exp["std_ret"],
                            "basis": "out-of-sample" if exp is oos else "seluruh periode"}
        if len(rets) < min_n:
            item.update(level="BELUM CUKUP DATA",
                        text=f"Baru {len(rets)} dari minimal {min_n} transaksi selesai. Alarm aktif setelah itu.")
            out["horizons"][h] = item
            continue
        allr = _check(rets, exp, warn, danger)
        item["all"] = allr
        level, where = allr["level"], "semua"
        if len(rets) > recent_n:
            rec = _check(rets[-recent_n:], exp, warn, danger)
            item["recent"] = rec
            if RANK[rec["level"]] < RANK[level]:
                level, where = rec["level"], "terakhir"
        item["level"] = level
        item["text"] = _text(item, where, recent_n)
        out["horizons"][h] = item
    levels = [v["level"] for v in out["horizons"].values() if v["level"] in RANK]
    out["level"] = min(levels, key=lambda x: RANK[x]) if levels else "BELUM CUKUP DATA"
    return out


def _p(x: float) -> str:
    return f"{x * 100:+.1f}%".replace(".", ",")


def _text(item: dict, where: str, recent_n: int) -> str:
    s = item["recent"] if where == "terakhir" else item["all"]
    e = item["expected"]
    scope = f"{recent_n} transaksi terakhir" if where == "terakhir" else f"{s['n']} transaksi"
    base = (f"{scope}: rata-rata {_p(s['avg_ret'])}, win rate {s['win_rate'] * 100:.0f}%; "
            f"perkiraan backtest {_p(e['avg_ret'])}, win rate {e['win_rate'] * 100:.0f}%.")
    lv = item["level"]
    if lv == "BAHAYA":
        chance = min(s["p_mean"], s["p_win"], s["p_streak"])
        return (base + f" Peluang hasil seburuk ini terjadi hanya karena kebetulan sekitar {f'{max(chance, 0.001) * 100:.1f}'.replace('.', ',')}%."
                " Strategi kemungkinan sedang tidak cocok dengan pasar: kecilkan ukuran posisi horizon ini"
                " atau berhenti sementara, lalu tinjau usulan tuning.")
    if lv == "WASPADA":
        extra = (f" Rentetan rugi {s['loss_streak']} kali berturut-turut." if s["p_streak"] < 0.05 else "")
        return base + extra + " Masih bisa kebetulan; belum perlu mengubah apa pun, pantau terus."
    if lv == "LEBIH BAIK":
        return base + " Lebih baik dari perkiraan; jangan menaikkan ukuran posisi hanya karena ini."
    return base + " Masih dalam rentang wajar."
