"""Notifikasi Telegram (opsional, gratis). Set env TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID."""
from __future__ import annotations

from .utils import log

H_NAME = {"short": "PENDEK", "medium": "MENENGAH", "long": "PANJANG"}


def build_message(res: dict, max_per_h: int = 5) -> str:
    m = res["market"]
    lines = [f"📊 *Sinyal IHSG {res['as_of']}*",
             f"IHSG {m['bench']:,.0f} ({m['bench_chg']:+.2%}) · Pasar: *{m['regime']}* · Universe {m['universe']} saham", ""]
    for h, blk in res["horizons"].items():
        lines.append(f"*{H_NAME[h]}* — kas {blk['cash_weight']:.0%}")
        if not blk["buys"]:
            lines.append("  (tidak ada sinyal beli)")
        for p in blk["buys"][:max_per_h]:
            lines.append(f"  🟢 {p['code']} {p['signal']} skor {p['score']:.0f} · bobot {p['weight_total']:.1%} · "
                         f"beli {p['entry_low']:,.0f}-{p['entry_high']:,.0f} · TP {p['tp1']:,.0f}/{p['tp2']:,.0f} · "
                         f"SL {p['sl']:,.0f} · hold {p['hold']}")
        for s in blk["sells"][:3]:
            lines.append(f"  🔴 {s['code']} {s['signal']} skor {s['score']:.0f} · {s['action']}")
        lines.append("")
    lines.append("_Bukan ajakan jual/beli. Keputusan & risiko di tangan Anda._")
    return "\n".join(lines).replace(",", ".")


def telegram(res: dict, token: str | None, chat_id: str | None):
    if not token or not chat_id:
        return
    import requests
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat_id, "text": build_message(res), "parse_mode": "Markdown"},
                          timeout=20)
        r.raise_for_status()
        log.info("Notifikasi Telegram terkirim")
    except Exception as e:  # noqa: BLE001
        log.warning("Telegram gagal: %s", e)
