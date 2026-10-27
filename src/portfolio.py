"""Bobot portofolio per horizon.

bobot_mentah_i = skor_i / volatilitas_i (ATR%)   -> keyakinan tinggi & volatilitas rendah dapat porsi lebih besar
lalu dinormalisasi, dibatasi `max_weight` per saham (water-filling) dan `sector_cap` per sektor.
Sisa yang tidak teralokasi = KAS. Jumlah lot juga dibatasi aturan risiko `risk_per_trade`.
"""
from __future__ import annotations

import math

import numpy as np


def _water_fill(raw: np.ndarray, cap: float) -> np.ndarray:
    w = raw / raw.sum()
    capped = np.zeros(len(w), dtype=bool)
    for _ in range(len(w) + 1):
        over = (w > cap + 1e-12) & ~capped
        if not over.any():
            break
        capped |= over
        w[capped] = cap
        free = ~capped
        remaining = 1 - cap * capped.sum()
        if not free.any() or remaining <= 0:
            break
        w[free] = remaining * raw[free] / raw[free].sum()
    return w


def allocate(picks: list[dict], hcfg: dict, capital: float, risk_per_trade: float) -> tuple[list[dict], float]:
    """picks: kandidat BUY (sudah ada score, atr_pct, sector, entry, sl). Return (picks berbobot, kas)."""
    picks = sorted(picks, key=lambda p: -p["score"])[: hcfg["max_positions"]]
    if not picks:
        return [], 1.0
    raw = np.array([max(p["score"], 1) / max(p.get("atr_pct") or 0.03, 0.005) for p in picks], dtype=float)
    w = _water_fill(raw, hcfg["max_weight"])

    # batas per sektor
    sectors: dict[str, float] = {}
    for p, wi in zip(picks, w):
        sectors[p["sector"]] = sectors.get(p["sector"], 0) + wi
    for i, p in enumerate(picks):
        tot = sectors[p["sector"]]
        if tot > hcfg["sector_cap"]:
            w[i] *= hcfg["sector_cap"] / tot

    bucket = capital * hcfg["allocation"]
    for p, wi in zip(picks, w):
        entry, sl = p["entry"], p["sl"]
        lots_w = math.floor(bucket * wi / (entry * 100))
        per_share_risk = max(entry - sl, 1e-9)
        lots_r = math.floor(capital * risk_per_trade / (per_share_risk * 100))
        lots = max(0, min(lots_w, lots_r))
        p["weight_bucket"] = float(wi)                       # bobot di dalam bucket horizon
        p["weight_total"] = float(wi * hcfg["allocation"])   # bobot terhadap total modal
        p["lots"] = int(lots)
        p["position_value"] = float(lots * 100 * entry)
        p["max_loss_value"] = float(lots * 100 * per_share_risk)
        p["lots_limited_by_risk"] = bool(lots_r < lots_w)
    cash = float(max(0.0, 1 - w.sum()))
    return picks, cash
