"""Peringatan berita negatif per saham (hanya peringatan, tidak mengubah skor/sinyal).

Sumber (gratis, RSS publik):
- Google News RSS, satu pencarian per kode saham (mengumpulkan judul dari Kontan, CNBC Indonesia, Bisnis,
  IDX Channel, Investor.id, dll.)
- RSS portal berita pasar modal di `news.feeds` (config.yaml)

Judul berita dicocokkan ke saham lewat kode (mis. "(BBRI)", "saham BBRI") atau nama perusahaan, lalu diperiksa
dengan kata kunci risiko (right issue, PKPU, gagal bayar, suspensi, gugatan, rugi, ...). Aturannya transparan
dan bisa diubah di KEYWORDS. Berita yang cocok disimpan di data/news/YYYY-MM.jsonl untuk diuji kelak.
"""
from __future__ import annotations

import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

from .utils import ROOT, log

DIR = ROOT / "data" / "news"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
GNEWS = "https://news.google.com/rss/search?q={q}&hl=id&gl=ID&ceid=ID:id"

# (kategori, tingkat, pola) — dicocokkan ke judul (+ ringkasan) huruf kecil
KEYWORDS = [
    ("PKPU / pailit", "tinggi", r"\bpkpu\b|pailit|kepailitan|penundaan kewajiban pembayaran utang"),
    ("Gagal bayar", "tinggi", r"gagal bayar|\bdefault\b|wanprestasi|tunda bayar|penundaan pembayaran (kupon|pokok|utang)"),
    ("Suspensi / delisting", "tinggi", r"suspensi|disuspen|suspend|delisting|didepak dari bursa|"
                                       r"papan pemantauan khusus|full call auction|\bfca\b"),
    ("UMA / notasi khusus", "sedang", r"unusual market activity|\buma\b|notasi khusus"),
    ("Kasus hukum", "tinggi", r"tersangka|\bkpk\b|kejaksaan|kejagung|korupsi|penyidikan|disidik|ditahan|"
                              r"penggeledahan|digeledah"),
    ("Gugatan", "sedang", r"digugat|gugatan|menggugat|sengketa|arbitrase"),
    ("Sanksi / denda", "sedang", r"\bdenda\b|didenda|sanksi|pembekuan izin|izin dicabut|pencabutan izin"),
    ("Right issue (dilusi)", "sedang", r"right[s]? issue|\bhmetd\b|penambahan modal dengan hak memesan"),
    ("Private placement (dilusi)", "sedang", r"private placement|\bpmthmetd\b|tanpa hak memesan efek terlebih dahulu"),
    ("Kinerja memburuk", "sedang", r"rugi bersih|\bmerugi\b|berbalik rugi|menderita rugi|"
                                   r"laba[^.]{0,30}(anjlok|merosot|ambles|ambrol|terjun|tergerus|terpangkas|turun tajam|longsor)|"
                                   r"(pendapatan|penjualan)[^.]{0,30}(anjlok|merosot|ambles|ambrol|terjun)"),
    ("Peringkat turun", "sedang", r"downgrade|outlook negatif|peringkat[^.]{0,30}(turun|dipangkas|diturunkan)"),
    ("Pengendali jual saham", "sedang", r"(pengendali|pemegang saham utama|direksi|komisaris|direktur)[^.]{0,40}"
                                        r"(jual|melepas|lepas|divestasi)[^.]{0,15}saham"),
    ("PHK / operasi terganggu", "sedang", r"\bphk\b|pemutusan hubungan kerja|tutup pabrik|penghentian operasi|"
                                          r"berhenti beroperasi|ledakan|kebakaran|longsor tambang"),
]
_KW = [(c, s, re.compile(p, re.I)) for c, s, p in KEYWORDS]
# kode saham yang juga kata umum -> hanya dicocokkan bila ditulis "(KODE)" / "saham KODE" / "emiten KODE"
COMMON_WORDS = {"CUAN", "EMAS", "DEWA", "GOTO", "MAPA", "BUMI", "BUKA", "AKRA", "INDY", "PANI", "BRIS", "SIDO",
                "BREN", "TINS", "JAWA", "ARTO", "INET", "RAJA", "HERO", "MAIN", "BOLA", "BALI", "POLA", "ENAK",
                "KAEF", "AUTO", "SMRA", "BANK", "AGRO", "TOTL", "NICL", "OASA", "SINI", "MEGA", "SOHO", "DATA"}
STOP_NAME = {"pt", "tbk", "tbk.", "persero", "(persero)", "perusahaan", "perseroan", "indonesia"}


def classify(text: str) -> list[tuple[str, str]]:
    return [(c, s) for c, s, rx in _KW if rx.search(text)]


def _name_alias(name: str | None) -> str | None:
    """'PT Bank Rakyat Indonesia (Persero) Tbk' -> 'bank rakyat indonesia' (minimal 2 kata bermakna)."""
    if not name:
        return None
    words = [w for w in re.sub(r"[().,]", " ", name).split() if w]
    core = [w for w in words if w.lower() not in {"pt", "tbk", "persero", "perusahaan", "perseroan"}]
    if len([w for w in core if w.lower() not in STOP_NAME]) < 2:
        return None
    return " ".join(core).lower()


def mentions(text: str, code: str, alias: str | None, others: dict | None = None) -> bool:
    """Apakah teks menyebut saham ini? `others` = alias saham lain, supaya "Bumi Resources" tidak
    dianggap BUMI bila yang tertulis "Bumi Resources Minerals" (BRMS)."""
    t = text
    if re.search(rf"\(\s*{code}\s*\)|(?i:saham|emiten|kode)\s+{code}\b", t):      # kode huruf besar
        return True
    if code not in COMMON_WORDS and re.search(rf"\b{code}\b", t):          # huruf besar persis
        return True
    if not alias:
        return False
    low = t.lower()
    for m in re.finditer(rf"\b{re.escape(alias)}\b", low):
        longer = [a for c, a in (others or {}).items() if a and c != code and len(a) > len(alias) and alias in a]
        if any(low.find(a, max(0, m.start() - len(a)), m.end() + len(a)) != -1 for a in longer):
            continue
        after = re.match(r"\s*\(\s*([a-z]{4})\s*\)", low[m.end():])        # "nama (KODE)" milik saham lain
        if after and after.group(1).upper() != code:
            continue
        return True
    return False


def clauses(text: str) -> list[str]:
    """Pecah judul/ringkasan menjadi klausa, supaya kata kunci hanya berlaku untuk saham di klausa yang sama."""
    return [c.strip() for c in re.split(r"[:;,|.!?]\s+|\s[-–—]\s", text) if c.strip()]


def _clean(s: str | None) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def parse_rss(xml_text: str) -> list[dict]:
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for it in root.iter("item"):
        title = _clean(it.findtext("title"))
        if not title:
            continue
        src = it.find("source")
        when = it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")
        try:
            dt = parsedate_to_datetime(when) if when else None
        except (TypeError, ValueError):
            dt = None
        if dt is None and when:
            try:
                dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
            except ValueError:
                dt = None
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        source = (src.text if src is not None else None) or ""
        if not source and " - " in title:                    # Google News: "Judul - Sumber"
            title, source = title.rsplit(" - ", 1)
        elif source and title.endswith(" - " + source):
            title = title[: -len(source) - 3]
        out.append({"title": title.strip(), "link": (it.findtext("link") or "").strip(), "source": source.strip(),
                    "published": dt, "summary": _clean(it.findtext("description"))[:400]})
    return out


def _get(session: requests.Session, url: str, timeout: float = 15) -> tuple[str | None, str]:
    try:
        r = session.get(url, timeout=timeout, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return r.text, "OK"
    except requests.RequestException as e:
        return None, type(e).__name__


def collect(stocks: list[dict], cfg: dict, now: datetime | None = None) -> dict:
    """stocks: [{"code", "name"}]. Return {"items": {code: [peringatan]}, "stats": {...}}."""
    ncfg = cfg.get("news", {}) or {}
    days = int(ncfg.get("days", 7))
    budget = float(ncfg.get("time_budget_sec", 240))
    delay = float(ncfg.get("delay_sec", 0.4))
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:                                  # now_wib() tanpa zona = WIB
        now = now.replace(tzinfo=timezone(timedelta(hours=7)))
    since = now - timedelta(days=days)
    aliases = {s["code"]: _name_alias(s.get("name")) for s in stocks}
    t0, sess = time.time(), requests.Session()
    raw: list[tuple[str | None, dict]] = []                 # (kode hasil pencarian, item)
    stats = {"feeds": {}, "google": {"ok": 0, "fail": 0, "items": 0}, "skipped_budget": 0}
    for url in ncfg.get("feeds", []) or []:
        txt, st = _get(sess, url)
        its = parse_rss(txt) if txt else []
        stats["feeds"][url] = {"status": st, "items": len(its)}
        raw += [(None, it) for it in its]
    if ncfg.get("google_news", True):
        for s in stocks:
            if time.time() - t0 > budget:
                stats["skipped_budget"] += 1
                continue
            q = f'"{s["code"]}" saham'
            txt, st = _get(sess, GNEWS.format(q=quote_plus(q)))
            if txt:
                its = parse_rss(txt)
                stats["google"]["ok"] += 1
                stats["google"]["items"] += len(its)
                raw += [(s["code"], it) for it in its]
            else:
                stats["google"]["fail"] += 1
                stats["google"].setdefault("errors", {}).setdefault(st, 0)
                stats["google"]["errors"][st] += 1
            time.sleep(delay)
    items: dict[str, list[dict]] = {}
    seen = set()
    n_recent = 0
    for hint, it in raw:
        if it["published"] is not None and it["published"] < since:
            continue
        n_recent += 1
        text = f"{it['title']}. {it['summary']}"
        cats = classify(text)
        if not cats:
            continue
        cands = [hint] if hint else list(aliases)
        parts = clauses(it["title"] if hint else text)
        for code in cands:
            hit = [c for c in parts if mentions(c, code, aliases.get(code), aliases) and classify(c)]
            if not hit:
                continue
            cats = [x for c in hit for x in classify(c)]
            cats = list(dict.fromkeys(cats))
            key = (code, re.sub(r"\W+", "", it["title"].lower())[:80])
            if key in seen:
                continue
            seen.add(key)
            sev = "tinggi" if any(s == "tinggi" for _, s in cats) else "sedang"
            items.setdefault(code, []).append({
                "date": it["published"].astimezone(timezone(timedelta(hours=7))).strftime("%Y-%m-%d") if it["published"] else None,
                "title": it["title"], "source": it["source"], "link": it["link"],
                "categories": [c for c, _ in cats], "severity": sev})
    for code in items:
        items[code].sort(key=lambda x: x["date"] or "", reverse=True)
    stats.update({"recent_items": n_recent, "stocks_flagged": len(items), "seconds": round(time.time() - t0)})
    return {"items": items, "stats": stats, "days": days}


def archive(result: dict, as_of: str) -> int:
    """Simpan peringatan baru ke data/news/YYYY-MM.jsonl (tanpa duplikat)."""
    DIR.mkdir(parents=True, exist_ok=True)
    path = DIR / f"{as_of[:7]}.jsonl"
    have = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                have.add((r["code"], r["title"]))
            except (ValueError, KeyError):
                continue
    new = []
    for code, lst in (result.get("items") or {}).items():
        for w in lst:
            if (code, w["title"]) not in have:
                new.append(json.dumps({"seen": as_of, "code": code, **w}, ensure_ascii=False))
    if new:
        with path.open("a", encoding="utf-8") as f:
            f.write("\n".join(new) + "\n")
    return len(new)


def probe(codes_names: list[dict], cfg: dict) -> dict:
    """Uji coba sumber berita (dipakai workflow riset): status tiap sumber + contoh hasil."""
    res = collect(codes_names, cfg)
    sample = {c: v[:3] for c, v in list(res["items"].items())[:25]}
    return {"stats": res["stats"], "flagged": {c: len(v) for c, v in res["items"].items()}, "sample": sample}


if __name__ == "__main__":
    import sys

    import yaml

    from .utils import dump_json
    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    latest = json.load(open(ROOT / "docs" / "data" / "latest.json", encoding="utf-8"))
    stocks = [{"code": r["code"], "name": r["name"]} for r in latest["all"]]
    if "--probe" in sys.argv:
        out = probe(stocks, cfg)
        dump_json(out, ROOT / "docs" / "data" / "news_probe.json")
        print(json.dumps(out["stats"], indent=1, ensure_ascii=False))
