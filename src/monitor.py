"""Alarm penyimpangan: apakah hasil rekomendasi SUNGGUHAN (track record) masih sesuai perkiraan backtest?

Untuk tiap horizon dibandingkan transaksi yang sudah selesai dengan distribusi hasil backtest
(periode out-of-sample bila cukup sampelnya):
  - rata-rata return per transaksi  -> uji z: (rata live - rata backtest) / (std backtest / sqrt(n))
  - win rate                         -> uji binomial eksak (peluang menang sesedikit ini)
  - rentetan rugi terpanjang         -> peluang rentetan sepanjang itu terjadi dalam n transaksi
Hasil dihitung untuk semua transaksi live dan untuk 20 transaksi terakhir (deteksi memburuk baru-baru ini).
Alarm dini (mulai 5 transaksi) memakai uji yang sama; di bawah 10 transaksi hanya WASPADA/BAHAYA yang dilaporkan.

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


def _binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k), X ~ Binomial(n, p): peluang menang sesedikit ini (atau lebih sedikit)."""
    return min(1.0, sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(0, k + 1)))


def _trailing_losses(rets: list[float]) -> int:
    cur = 0
    for r in reversed(rets):
        if r > 0:
            break
        cur += 1
    return cur


def _check(rets: list[float], exp: dict, warn: float, danger: float, streak_min: int = 3) -> dict:
    n = len(rets)
    m = sum(rets) / n
    wins = sum(r > 0 for r in rets)
    w = wins / n
    mu, sd, p = exp.get("avg_ret"), exp.get("std_ret") or 0.0, exp["win_rate"]
    z_m = (m - mu) / (sd / math.sqrt(n)) if sd > 0 and mu is not None else 0.0
    z_w = (w - p) / math.sqrt(p * (1 - p) / n) if 0 < p < 1 else 0.0
    p_b = _binom_cdf(wins, n, p) if 0 < p < 1 else 1.0          # uji binomial eksak (akurat untuk n kecil)
    k = _longest_losses(rets)
    p_k = streak_prob(n, k, 1 - p) if k >= streak_min else 1.0
    p_min = min(p_b, p_k)               # win rate dinilai dengan uji eksak, bukan pendekatan z (n kecil)
    worst_z = z_m
    if worst_z <= -danger or p_min < 0.01:
        level = "BAHAYA"
    elif worst_z <= -warn or p_min < 0.05:
        level = "WASPADA"
    elif z_m >= warn:
        level = "LEBIH BAIK"
    else:
        level = "NORMAL"
    return {"n": n, "avg_ret": m, "win_rate": w, "z_mean": z_m, "z_win": z_w, "p_mean": _phi(z_m),
            "p_win": _phi(z_w), "p_binom": p_b, "loss_streak": k, "loss_streak_now": _trailing_losses(rets),
            "p_streak": p_k, "level": level}


RANK = {"BAHAYA": 0, "WASPADA": 1, "NORMAL": 2, "LEBIH BAIK": 3}


def _closed(rows) -> list[tuple[float, str | None]]:
    out = []
    for c in rows or []:
        r = c[1] if len(c) > 1 else None
        if r is None or not math.isfinite(float(r)):
            continue
        out.append((float(r), c[2] if len(c) > 2 else None))
    return out


def check(track: dict, backtest: dict | None, cfg: dict, versions: dict | None = None) -> dict:
    """track = hasil tracker.summarize (berisi closed_rets [tanggal, return, versi]); backtest = isi backtest.json.

    - Versi strategi aktif dinilai sendiri bila sudah punya >= min_trades transaksi; sebelum itu dinilai
      bersama versi lama (uang yang hilang tetap nyata), dan teksnya menyebut hal itu.
    - Sebelum min_trades, alarm DINI tetap aktif: uji binomial eksak & rentetan rugi (mulai `early_trades`).
    - Tanpa sebaran backtest (std_ret) uji rata-rata dilewati; win rate & rentetan rugi tetap diuji.
    - Horizon tanpa backtest dibandingkan dengan win rate asumsi (`assumed_win_rate`, bawaan 50%).
    """
    mcfg = cfg.get("monitor", {}) or {}
    min_n = int(mcfg.get("min_trades", 10))
    early_n = int(mcfg.get("early_trades", 5))
    recent_n = int(mcfg.get("recent_trades", 20))
    streak_min = int(mcfg.get("streak_min", 3))
    assumed = float(mcfg.get("assumed_win_rate", 0.5))
    warn, danger = float(mcfg.get("warn_z", 1.65)), float(mcfg.get("danger_z", 2.33))
    results = (backtest or {}).get("results") or {}
    out = {"horizons": {}, "min_trades": min_n, "early_trades": early_n}
    for h, closed in (track.get("closed_rets") or {}).items():
        bt = results.get(h)
        allc = _closed(closed)
        cur_id = ((versions or {}).get(h) or {}).get("id")
        cur = [r for r, s in allc if cur_id and s == cur_id]
        if cur_id and len(cur) >= min_n:
            rets, scope = cur, "versi aktif"
        else:
            rets, scope = [r for r, _ in allc], ("semua versi" if cur_id and len(cur) < len(allc) else "semua")
        item = {"label": HZ.get(h, h), "n": len(rets), "n_current": len(cur), "scope": scope}
        if bt and bt.get("n"):
            oos = bt.get("out_sample") or {}
            exp = oos if (oos.get("n") or 0) >= 30 else bt
            basis = "out-of-sample" if exp is oos else "seluruh periode"
            if exp.get("std_ret") is None:
                basis += ", tanpa sebaran: hanya win rate & rentetan rugi"
            item["expected"] = {"avg_ret": exp.get("avg_ret"), "win_rate": exp["win_rate"],
                                "std_ret": exp.get("std_ret"), "basis": basis}
        else:
            item["expected"] = {"avg_ret": None, "win_rate": assumed, "std_ret": None,
                                "basis": f"tanpa backtest: asumsi win rate {assumed * 100:.0f}%"}
        exp = item["expected"]
        if len(rets) < early_n:
            item.update(level="BELUM CUKUP DATA",
                        text=f"Baru {len(rets)} transaksi selesai. Alarm dini aktif mulai {early_n} transaksi, "
                             f"penuh mulai {min_n}.")
            out["horizons"][h] = item
            continue
        allr = _check(rets, exp, warn, danger, streak_min)
        item["all"] = allr
        level, where = allr["level"], "semua"
        if len(rets) < min_n:                       # alarm dini: hanya peringatan, bukan "NORMAL"
            item["early"] = True
            if level not in ("WASPADA", "BAHAYA"):
                level = "BELUM CUKUP DATA"
        elif len(rets) > recent_n:
            rec = _check(rets[-recent_n:], exp, warn, danger, streak_min)
            item["recent"] = rec
            if RANK[rec["level"]] < RANK[level]:
                level, where = rec["level"], "terakhir"
        item["level"] = level
        item["text"] = _text(item, where, recent_n, min_n)
        out["horizons"][h] = item
    levels = [v["level"] for v in out["horizons"].values() if v["level"] in RANK]
    out["level"] = min(levels, key=lambda x: RANK[x]) if levels else "BELUM CUKUP DATA"
    return out


def _p(x: float) -> str:
    return f"{x * 100:+.1f}%".replace(".", ",")


def _text(item: dict, where: str, recent_n: int, min_n: int = 10) -> str:
    s = item["recent"] if where == "terakhir" else item["all"]
    e = item["expected"]
    scope = f"{recent_n} transaksi terakhir" if where == "terakhir" else f"{s['n']} transaksi"
    if item.get("scope") == "semua versi":
        scope += f" (termasuk versi lama; versi aktif baru {item.get('n_current', 0)})"
    exp_txt = (f"perkiraan backtest {_p(e['avg_ret'])}, win rate {e['win_rate'] * 100:.0f}%"
               if e.get("avg_ret") is not None else f"pembanding win rate {e['win_rate'] * 100:.0f}% ({e['basis']})")
    base = f"{scope}: rata-rata {_p(s['avg_ret'])}, win rate {s['win_rate'] * 100:.0f}%; {exp_txt}."
    now = s.get("loss_streak_now") or 0
    if now >= 3:
        base += f" Rugi {now} kali berturut-turut sampai sekarang."
    lv = item["level"]
    if lv == "BAHAYA":
        chance = min(s["p_mean"], s["p_streak"], s.get("p_binom", 1.0))
        return (base + f" Peluang hasil seburuk ini terjadi hanya karena kebetulan sekitar {f'{max(chance, 0.001) * 100:.1f}'.replace('.', ',')}%."
                " Strategi kemungkinan sedang tidak cocok dengan pasar: kecilkan ukuran posisi horizon ini"
                " atau berhenti sementara, lalu tinjau usulan tuning.")
    if lv == "WASPADA":
        early = (f" Alarm dini (baru {s['n']} dari {min_n} transaksi)." if item.get("early") else "")
        return base + early + " Masih bisa kebetulan; pertimbangkan memperkecil ukuran posisi dan pantau terus."
    if lv == "LEBIH BAIK":
        return base + " Lebih baik dari perkiraan; jangan menaikkan ukuran posisi hanya karena ini."
    if lv == "BELUM CUKUP DATA":
        chance = min(s["p_streak"], s.get("p_binom", 1.0))
        nostd = "" if e.get("std_ret") or e.get("avg_ret") is None else \
            " Uji rata-rata return menunggu backtest berikutnya (belum ada data sebaran)."
        if chance < 0.2:
            return (base + f" Peluang hasil ini hanya kebetulan sekitar {f'{chance * 100:.1f}'.replace('.', ',')}%"
                    f" — belum melewati batas alarm 5%, tapi patut diwaspadai." + nostd)
        return base + f" Belum menyimpang jauh; penilaian penuh setelah {min_n} transaksi." + nostd
    return base + " Masih dalam rentang wajar."
