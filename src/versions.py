"""Versi strategi per horizon.

Setiap kombinasi parameter yang memengaruhi sinyal (blok horizon di config.yaml, ambang sinyal, biaya, dan
LOGIC_VERSION untuk perubahan rumus di kode) diberi sidik jari pendek. Sidik jari baru = versi baru
(v1, v2, ...), dicatat di docs/data/strategy_versions.json beserta tanggal mulai dan parameternya.

Setiap rekomendasi di track record menyimpan sidik jari versinya, sehingga hasil strategi lama dan baru
tidak tercampur. Rekomendasi yang dibuat sebelum pelabelan ada memakai versi "v0".
"""
from __future__ import annotations

import hashlib
import json

from .utils import ROOT, dump_json, load_json

PATH = ROOT / "docs" / "data" / "strategy_versions.json"
# Naikkan angka ini bila rumus skor/sinyal/rencana di kode berubah (tanpa perubahan config.yaml).
LOGIC_VERSION = 1
LEGACY = "v0"
LEGACY_LABEL = "v0 · sebelum label versi (s.d. 2026-11-08)"
IGNORE = {"label"}          # kunci kosmetik yang tidak memengaruhi sinyal


def params(cfg: dict, h: str) -> dict:
    hcfg = {k: v for k, v in (cfg["horizons"][h] or {}).items() if k not in IGNORE}
    return {"horizon": hcfg, "thresholds": cfg.get("thresholds"), "fees": cfg.get("fees"), "logic": LOGIC_VERSION}


def fingerprint(cfg: dict, h: str) -> str:
    raw = json.dumps(params(cfg, h), sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()[:8]


def label(entry: dict | None) -> str:
    if not entry:
        return LEGACY_LABEL
    return f"v{entry['v']} · sejak {entry['since']}"


def register(cfg: dict, as_of: str, horizons=("short", "medium", "long"), save: bool = True,
             path=PATH) -> dict:
    """Catat versi aktif tiap horizon. Hasil: {h: {"id", "v", "since", "label"}} + "_all": seluruh riwayat."""
    reg = load_json(path, {}) or {}
    cur, changed = {}, False
    for h in horizons:
        fp = fingerprint(cfg, h)
        hist = reg.setdefault(h, [])
        entry = next((e for e in hist if e["id"] == fp), None)
        if entry is None:
            entry = {"id": fp, "v": len(hist) + 1, "since": as_of, "params": params(cfg, h)}
            hist.append(entry)
            changed = True
        cur[h] = {"id": fp, "v": entry["v"], "since": entry["since"], "label": label(entry)}
    if save and changed:
        dump_json(reg, path)
    return {**cur, "_all": {h: {e["id"]: label(e) for e in hist} for h, hist in reg.items()}}


def label_of(versions: dict | None, h: str, sid) -> str:
    """Label versi dari sidik jari yang tersimpan di track record."""
    if not isinstance(sid, str) or not sid or sid == LEGACY:
        return LEGACY_LABEL
    return ((versions or {}).get("_all", {}).get(h, {}) or {}).get(sid, f"versi {sid}")
