"""Rencana trading: area beli, take profit, cut loss, lama hold & aturan keluar."""
from __future__ import annotations

import math

from .utils import fnum, round_tick, tick_size

def _rp(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def _when_buy(h: str, hcfg: dict, entry: float, entry_high: float) -> str:
    if h == "long":
        return ("Cicil 3 tahap (mis. 40/30/30) dalam 2-4 minggu di area beli; tambah saat koreksi ke SMA50. "
                f"Jangan beli di atas {_rp(entry_high)}.")
    if hcfg.get("entry_mode") == "limit":
        return (f"Pasang antrean beli di {_rp(entry)} (koreksi ke area support), berlaku "
                f"{hcfg.get('limit_days', 3)} hari bursa. Tidak terisi = batal, jangan dikejar.")
    return (f"Beli T+1 sesi 1 di harga pembukaan, maksimal {_rp(entry_high)}. "
            "Batal bila dibuka di atas batas itu (gap up).")


def _when_sell(h: str, hcfg: dict) -> str:
    mx, tm = hcfg["hold_max_days"], int(hcfg.get("trail_ma") or 0)
    if h == "long":
        return ("Ambil sebagian di TP1, sisanya dibiarkan berjalan selama fundamental & tren primer utuh. "
                "Keluar bila close mingguan di bawah SL / SMA200, atau sinyal berubah STRONG SELL. "
                "Review tiap rilis laporan keuangan kuartalan.")
    trail = f"sisanya di TP2 atau saat close < EMA{tm}" if tm else "sisanya di TP2"
    return (f"Jual 50% di TP1 lalu naikkan cut loss ke harga beli; {trail}. "
            f"Cut loss bila harga menyentuh SL. Time-stop: jual sisa posisi setelah {mx} hari bursa.")


def hold_text(h: str, hcfg: dict) -> str:
    lo, hi = hcfg["hold_min_days"], hcfg["hold_max_days"]
    if h == "long":
        return f"{round(lo / 21)}-{round(hi / 21)} bulan"
    if h == "medium":
        return f"{lo}-{hi} hari bursa (~{max(1, round(lo / 21))}-{round(hi / 21)} bulan)"
    return f"{lo}-{hi} hari bursa"


def make_plan(row, horizon: str, hcfg: dict, fees: dict, texts: bool = True) -> dict | None:
    """row: baris indikator (Series/dict) pada tanggal sinyal."""
    close = fnum(row["Close"])
    atr = fnum(row["ATR14"])
    if not close or not atr:
        return None
    support = fnum(row["EMA20"]) if horizon in ("short", "medium") else fnum(row["SMA50"])

    # --- area beli
    low = close - hcfg["entry_atr"] * atr
    if support and low < support < close:
        low = support                                  # jangan menunggu lebih dalam dari support MA
    entry_low = min(round_tick(low, "up"), round_tick(close))
    entry_high = max(round_tick(close + hcfg.get("chase_atr", 0) * atr, "down"), round_tick(close))
    limit = hcfg.get("entry_mode") == "limit" and horizon != "long"
    entry = entry_low if limit else round_tick(close)   # harga acuan untuk SL/TP

    # --- cut loss (berbasis ATR, dibatasi persentase maksimum)
    sl_raw = max(entry * (1 - hcfg["max_sl_pct"]), entry - hcfg["sl_atr"] * atr)
    sl = round_tick(sl_raw, "down")
    if sl > entry - 2 * tick_size(entry):
        sl = round_tick(entry - 2 * tick_size(entry), "down")
    risk = entry - sl

    rr1, rr2 = hcfg["rr"]
    tp1 = round_tick(entry + rr1 * risk, "nearest")
    tp2 = round_tick(entry + rr2 * risk, "nearest")

    fb, fs = fees["buy"], fees["sell"]
    cost_in = entry * (1 + fb)

    def net_rr(tp):
        loss = cost_in - sl * (1 - fs)
        return (tp * (1 - fs) - cost_in) / loss if loss > 0 else math.nan

    plan = {
        "entry": entry, "entry_low": entry_low, "entry_high": entry if limit else entry_high,
        "tp1": tp1, "tp2": tp2, "sl": sl,
        "tp1_pct": tp1 / entry - 1, "tp2_pct": tp2 / entry - 1, "sl_pct": sl / entry - 1,
        "rr1": net_rr(tp1), "rr2": net_rr(tp2),
        "max_hold_days": hcfg["hold_max_days"],
        "entry_mode": "limit" if limit else "open",
        "limit_days": hcfg.get("limit_days", 3),
        "trail_ma": int(hcfg.get("trail_ma") or 0),
    }
    if texts:
        plan.update({"hold": hold_text(horizon, hcfg),
                     "when_buy": _when_buy(horizon, hcfg, entry, entry_high),
                     "when_sell": _when_sell(horizon, hcfg)})
    return plan


def sell_plan(row, signal: str) -> dict:
    close = fnum(row["Close"])
    atr = fnum(row["ATR14"], 0.0)
    ll20 = fnum(row.get("LL20"))
    if ll20 is None or ll20 >= close:          # sudah tembus support 20 hari -> pakai 1 ATR di bawah harga
        ll20 = close - atr
    strong = signal == "STRONG SELL"
    return {
        "action": "Jual seluruh posisi" if strong else "Kurangi 50% posisi",
        "sell_portion": 1.0 if strong else 0.5,
        "sell_zone_low": round_tick(close, "nearest"),
        "sell_zone_high": round_tick(close + 0.5 * atr, "down"),
        "breakdown_level": round_tick(ll20, "down") if ll20 else None,
        "when_sell": ("Jual saat pantulan (rebound) ke area jual pada T+1/T+2; jangan menunggu. "
                      if strong else
                      "Kurangi saat pantulan ke area jual. Sisa posisi: cut loss bila close di bawah level breakdown. ")
                     + "Jangan buka posisi beli baru selama sinyal SELL.",
    }
