"""Notifikasi Telegram (gratis). Butuh env TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID (GitHub Secrets).

Isi pesan harian:
  - kondisi IHSG & jumlah saham yang dipantau
  - per horizon: rekomendasi BELI (area beli, TP, SL, bobot, lot, lama hold), sinyal tertahan, sinyal JUAL teratas
  - rekomendasi lama yang hari ini kena TP / SL / time-stop
  - link dashboard
Pesan dipecah otomatis bila melebihi batas 4.096 karakter Telegram.
CHAT_ID boleh berisi beberapa id dipisah koma (mis. pribadi + grup).
"""
from __future__ import annotations

import html
import time

from .utils import log

H_NAME = {"short": "PENDEK (swing)", "medium": "MENENGAH (1-3 bln)", "long": "PANJANG (6-24 bln)"}
OUTCOME = {"TP2": "TP2 ✅", "SL": "Cut loss ❌", "BE": "impas", "TIME": "time-stop", "TRAIL": "trailing stop",
           "BATAL": "Batal (tidak terisi)"}
LIMIT = 3900


def rp(x) -> str:
    try:
        return f"{float(x):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "-"


def pct(x, d=1, sign=True) -> str:
    try:
        s = f"{100 * float(x):{'+' if sign else ''}.{d}f}%"
        return s.replace(".", ",")
    except (TypeError, ValueError):
        return "-"


def e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _outcome(o: str) -> str:
    if o and o.startswith("TP1+"):
        return "TP1 lalu " + OUTCOME.get(o[4:], o[4:])
    return OUTCOME.get(o, o or "-")


def build_messages(res: dict, dashboard_url: str | None = None, max_buys: int = 6, max_sells: int = 5) -> list[str]:
    m = res["market"]
    head = [f"📊 <b>Sinyal IHSG — {e(res['as_of'])}</b>",
            f"IHSG <b>{rp(m['bench'])}</b> ({pct(m['bench_chg'], 2)}) · Pasar <b>{e(m['regime'])}</b>",
            f"Dipantau {m['universe']} saham (market cap ≥ Rp 5 T)"]
    blocks = ["\n".join(head)]

    for h, blk in res["horizons"].items():
        lines = [f"<b>━ {H_NAME.get(h, h)}</b> · kas {pct(blk['cash_weight'], 0, False)} dari bucket"]
        if blk.get("regime_text"):
            lines.append(f"⚠️ Porsi dikurangi ke {pct(blk['regime_scale'], 0, False)} ({e(blk['regime_text'])})")
        if blk["buys"]:
            for p in blk["buys"][:max_buys]:
                lot = f" · {p['lots']} lot" if p.get("lots") else ""
                buy = (f"Antre beli {rp(p['entry'])} ({p.get('limit_days', 3)} hari)" if p.get("entry_mode") == "limit"
                       else f"Beli {rp(p['entry_low'])}–{rp(p['entry_high'])}")
                lines.append(
                    f"🟢 <b>{e(p['code'])}</b> {e(p['signal'])} ({p['score']:.0f}) · bobot {pct(p['weight_total'], 1, False)}{lot}\n"
                    f"   {buy} · TP {rp(p['tp1'])}/{rp(p['tp2'])} · "
                    f"SL {rp(p['sl'])} ({pct(p['sl_pct'])}) · hold {e(p['hold'])}")
            if len(blk["buys"]) > max_buys:
                lines.append(f"   …dan {len(blk['buys']) - max_buys} lainnya di dashboard")
        else:
            held = blk.get("n_held") or 0
            lines.append("Tidak ada rekomendasi beli." + (f" {held} sinyal BUY tertahan filter." if held else ""))
            top = [w for w in blk.get("watchlist", []) if w.get("held") and "kuota" not in w["held"]][:3]
            if top:
                lines.append("   Kandidat bila filter lolos: " + ", ".join(f"{e(w['code'])} ({w['score']:.0f})" for w in top))
        sells = blk.get("sells", [])[:max_sells]
        if sells:
            lines.append("🔴 Jual/kurangi: " + ", ".join(
                f"{e(s['code'])}{' (semua)' if s['signal'] == 'STRONG SELL' else ' (50%)'}" for s in sells)
                + (f" +{len(blk['sells']) - max_sells} lainnya" if len(blk["sells"]) > max_sells else ""))
        blocks.append("\n".join(lines))

    done = [r for r in (res.get("track") or {}).get("recent_closed", []) if r.get("exit_date") == res["as_of"]]
    if done:
        lines = ["<b>━ Rekomendasi selesai hari ini</b>"]
        for r in done[:10]:
            lines.append(f"• {e(r['code'])} ({H_NAME.get(r['horizon'], r['horizon']).split()[0].lower()}): "
                         f"{_outcome(r['outcome'])} {pct(r.get('ret'))}")
        blocks.append("\n".join(lines))

    tail = []
    if dashboard_url:
        tail.append(f'🔗 <a href="{e(dashboard_url)}">Buka dashboard</a>')
    tail.append("<i>Alat bantu analisis, bukan ajakan jual/beli. Cek ulang harga sebelum transaksi.</i>")
    blocks.append("\n".join(tail))

    msgs, cur = [], ""
    for b in blocks:
        if len(cur) + len(b) + 2 > LIMIT and cur:
            msgs.append(cur)
            cur = ""
        cur = f"{cur}\n\n{b}" if cur else b
    if cur:
        msgs.append(cur)
    return msgs


def send(token: str, chat_id: str, text: str) -> bool:
    import requests
    for attempt in range(3):
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                    "disable_web_page_preview": True}, timeout=20)
            if r.status_code == 429:                       # terlalu sering -> tunggu sesuai saran Telegram
                time.sleep(int(r.json().get("parameters", {}).get("retry_after", 5)) + 1)
                continue
            if not r.ok:
                log.warning("Telegram menolak pesan (%s): %s", r.status_code, r.text[:200])
                return False
            return True
        except Exception as ex:  # noqa: BLE001
            log.warning("Telegram gagal (percobaan %d): %s", attempt + 1, ex.__class__.__name__)
            time.sleep(3)
    return False


def telegram(res: dict, token: str | None, chat_ids: str | None, dashboard_url: str | None = None):
    if not token or not chat_ids:
        log.info("Telegram dilewati (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID belum diisi)")
        return
    msgs = build_messages(res, dashboard_url)
    for cid in [c.strip() for c in str(chat_ids).split(",") if c.strip()]:
        ok = all(send(token, cid, m) for m in msgs)
        log.info("Telegram ke chat %s…: %s (%d pesan)", cid[:4], "terkirim" if ok else "GAGAL", len(msgs))
