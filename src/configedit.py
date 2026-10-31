"""Ubah satu nilai di config.yaml tanpa merusak komentar & susunan (dipakai tombol "Terapkan usulan")."""
from __future__ import annotations

import re


def fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(fmt(x) for x in v) + "]"
    return str(v)


def set_horizon_param(text: str, horizon: str, key: str, value, note: str | None = None) -> str:
    """Ganti `key:` di dalam blok `horizons: -> <horizon>:`; bila belum ada, tambahkan di akhir blok."""
    lines = text.split("\n")
    try:
        hi = next(i for i, ln in enumerate(lines) if re.match(r"^horizons:\s*(#.*)?$", ln))
        bi = next(i for i in range(hi + 1, len(lines)) if re.match(rf"^  {re.escape(horizon)}:\s*(#.*)?$", lines[i]))
    except StopIteration:
        raise ValueError(f"Blok horizons.{horizon} tidak ditemukan di config.yaml") from None
    end = bi + 1
    while end < len(lines) and (lines[end].startswith("    ") or not lines[end].strip()):
        end += 1
    while end > bi + 1 and not lines[end - 1].strip():
        end -= 1
    pat = re.compile(rf"^(    {re.escape(key)}:\s*)([^#\n]*?)(\s*#.*)?$")
    for i in range(bi + 1, end):
        m = pat.match(lines[i])
        if m:
            body = f"{m.group(1)}{fmt(value)}"
            comment = f"   # {note}" if note else (m.group(3) or "")
            lines[i] = body + comment
            return "\n".join(lines)
    lines.insert(end, f"    {key}: {fmt(value)}" + (f"   # {note}" if note else ""))
    return "\n".join(lines)
