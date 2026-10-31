"""Utilitas umum: logging, fraksi harga IDX, pembulatan, JSON aman."""
from __future__ import annotations

import json
import logging
import math
import os
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

def _home() -> Path:
    """Folder kerja (data, dashboard, config, posisi).
    - IHSG_HOME (env) bila diisi
    - aplikasi .exe: folder tempat .exe berada (bila bisa ditulis), jika tidak %LOCALAPPDATA%\\PANDU
      (atau %LOCALAPPDATA%\\IHSG Signal bila folder lama itu sudah ada)
    - selain itu: folder proyek"""
    env = os.environ.get("IHSG_HOME")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        try:
            probe = base / ".write_test"
            probe.write_text("x")
            probe.unlink()
            return base
        except OSError:
            base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
            return base / "IHSG Signal" if (base / "IHSG Signal").exists() else base / "PANDU"
    return Path(__file__).resolve().parent.parent


ROOT = _home()
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))   # file bawaan (read-only)

log = logging.getLogger("ihsg")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                        datefmt="%H:%M:%S")


def now_wib() -> datetime:
    """Waktu WIB tanpa info zona. Tidak bergantung database zona waktu (Windows tidak punya bawaan)."""
    from datetime import timedelta, timezone
    return datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)


# ---------------------------------------------------------------- fraksi harga (tick size) BEI
def tick_size(price: float) -> int:
    """Fraksi harga saham BEI (papan reguler)."""
    if price < 200:
        return 1
    if price < 500:
        return 2
    if price < 2000:
        return 5
    if price < 5000:
        return 10
    return 25


def round_tick(price: float, mode: str = "nearest") -> float:
    if price is None or not np.isfinite(price) or price <= 0:
        return float("nan")
    t = tick_size(price)
    if mode == "down":
        v = math.floor(price / t) * t
    elif mode == "up":
        v = math.ceil(price / t) * t
    else:
        v = round(price / t) * t
    return float(max(v, 1))


def lot_value(price: float, lots: int) -> float:
    return price * 100 * lots          # 1 lot = 100 lembar


# ---------------------------------------------------------------- JSON
def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not math.isfinite(f) else round(f, 6)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime, date)):
        return o.strftime("%Y-%m-%d")
    if o is pd.NA or o is pd.NaT:
        return None
    return o


def dump_json(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(obj), ensure_ascii=False, indent=1), encoding="utf-8")


def to_jsonable(obj):
    return _clean(obj)


def load_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def fnum(x, default=None):
    """float aman: None / NaN -> default."""
    try:
        f = float(x)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default
