"""IHSG Signal — aplikasi desktop (Windows).

    IHSG Signal.exe              buka jendela aplikasi
    IHSG Signal.exe --auto       update tanpa jendela (dipakai jadwal otomatis Windows)
    IHSG Signal.exe --selftest   uji kemasan dengan data contoh (dipakai saat build)

Semua data tersimpan di folder aplikasi (atau %LOCALAPPDATA%\\IHSG Signal bila folder itu tidak bisa ditulis):
config.yaml, positions.csv, settings.json, docs\\index.html (dashboard), data\\, logs\\.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME = "IHSG Signal"
TASK_NAME = "IHSG Signal - update harian"


# ============================================================== persiapan folder & log
def _bootstrap():
    from src.utils import BUNDLE, ROOT
    for sub in ("data", "data/cache", "docs", "logs"):
        (ROOT / sub).mkdir(parents=True, exist_ok=True)
    for rel in ("config.yaml", "data/tickers_seed.csv"):            # salin bawaan saat pertama kali
        dst, src = ROOT / rel, BUNDLE / rel
        if not dst.exists() and src.exists() and src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
    fh = RotatingFileHandler(ROOT / "logs" / "ihsg.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    logging.getLogger("ihsg").addHandler(fh)
    return ROOT


ROOT = SETTINGS = LOCK = LAST = None          # diisi oleh init()
load_json = log = None


def _exe_dir() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def init():
    """Siapkan folder & log. Dipanggil di dalam try agar error saat start tidak memunculkan dialog yang menggantung."""
    global ROOT, SETTINGS, LOCK, LAST, load_json, log
    if sys.stdout is None or sys.stderr is None:                     # .exe tanpa konsol: jangan biarkan print gagal
        f = open(_exe_dir() / "console.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f
    ROOT = _bootstrap()
    from src import utils
    load_json, log = utils.load_json, utils.log
    SETTINGS = ROOT / "settings.json"
    LOCK = ROOT / ".update.lock"
    LAST = ROOT / "logs" / "last_run.json"


def _crash(mode: str):
    """Tulis crash.log di folder aplikasi; di mode jendela tampilkan pesan (tanpa menggantung mode otomatis)."""
    tb = traceback.format_exc()
    try:
        (_exe_dir() / "crash.log").write_text(f"{datetime.now():%Y-%m-%d %H:%M:%S} mode={mode}\n{tb}", encoding="utf-8")
    except OSError:
        pass
    if mode == "gui" and sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "Aplikasi gagal dibuka. Detail di crash.log di folder aplikasi.\n\n"
                                             + tb[-900:], APP_NAME, 0x10)
        except Exception:  # noqa: BLE001
            pass


def settings() -> dict:
    s = load_json(SETTINGS, {}) or {}
    s.setdefault("telegram_token", "")
    s.setdefault("telegram_chat_id", "")
    s.setdefault("open_dashboard", True)
    return s


def save_settings(s: dict):
    SETTINGS.write_text(json.dumps(s, indent=1), encoding="utf-8")


# ============================================================== update (dipakai jendela & mode --auto)
def run_update(demo: bool = False) -> dict:
    """Jalankan seluruh proses harian. Return ringkasan hasil."""
    import yaml

    import main as M
    from src import notify

    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 3600:
        raise RuntimeError("Update lain sedang berjalan (mis. jadwal otomatis). Coba lagi beberapa menit lagi.")
    LOCK.write_text(str(os.getpid()))
    t0 = time.time()
    try:
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        cfg.setdefault("positions", {})["dashboard"] = "full"      # dashboard lokal = privat -> tampilkan lengkap
        res = M.run(cfg, demo=demo, backtest_mode="auto")
        pos_full = res.pop("_positions_full", None)
        M.write_outputs(res, demo)
        st = settings()
        if not demo and st["telegram_token"] and st["telegram_chat_id"] and cfg.get("notify", {}).get("telegram", True):
            notify.telegram(res, st["telegram_token"], st["telegram_chat_id"], None, pos_full)
        summary = {"ok": True, "when": datetime.now().strftime("%Y-%m-%d %H:%M"), "as_of": res["as_of"],
                   "seconds": round(time.time() - t0)}
    except Exception as e:  # noqa: BLE001
        log.error("Update gagal: %s\n%s", e, traceback.format_exc())
        summary = {"ok": False, "when": datetime.now().strftime("%Y-%m-%d %H:%M"), "error": str(e)}
        raise
    finally:
        LOCK.unlink(missing_ok=True)
        if not demo:
            LAST.write_text(json.dumps(summary), encoding="utf-8")
    return summary


def dashboard_path() -> Path:
    return ROOT / "docs" / "index.html"


def open_path(p: Path):
    if sys.platform.startswith("win"):
        os.startfile(str(p))  # noqa: S606  (Windows)
    else:
        webbrowser.open(p.as_uri())


# ============================================================== jadwal otomatis (Windows Task Scheduler)
def _launch_cmd() -> tuple[str, str]:
    if getattr(sys, "frozen", False):
        return sys.executable, "--auto"
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return str(pyw if pyw.exists() else exe), f'"{Path(__file__).resolve()}" --auto'


def _schtasks(*args) -> subprocess.CompletedProcess:
    flags = 0x08000000 if sys.platform.startswith("win") else 0           # CREATE_NO_WINDOW
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, creationflags=flags)


def schedule_exists() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        return _schtasks("/Query", "/TN", TASK_NAME).returncode == 0
    except OSError:
        return False


def schedule_set(enable: bool, hhmm: str = "17:30") -> str:
    if not sys.platform.startswith("win"):
        return "Jadwal otomatis hanya tersedia di Windows."
    if not enable:
        r = _schtasks("/Delete", "/TN", TASK_NAME, "/F")
        return "Jadwal otomatis dimatikan." if r.returncode == 0 else f"Gagal mematikan jadwal: {r.stderr.strip()}"
    cmd, args = _launch_cmd()
    esc = lambda x: x.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")  # noqa: E731
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>IHSG Signal: update sinyal saham setiap hari bursa</Description></RegistrationInfo>
  <Triggers><CalendarTrigger><StartBoundary>2026-01-01T{hhmm}:00</StartBoundary><Enabled>true</Enabled>
    <ScheduleByWeek><DaysOfWeek><Monday/><Tuesday/><Wednesday/><Thursday/><Friday/></DaysOfWeek>
    <WeeksInterval>1</WeeksInterval></ScheduleByWeek></CalendarTrigger></Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><StartWhenAvailable>true</StartWhenAvailable><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <Enabled>true</Enabled></Settings>
  <Actions Context="Author"><Exec><Command>{esc(cmd)}</Command><Arguments>{esc(args)}</Arguments>
    <WorkingDirectory>{esc(str(ROOT))}</WorkingDirectory></Exec></Actions>
</Task>"""
    tmp = ROOT / "logs" / "task.xml"
    tmp.write_text(xml, encoding="utf-16")
    r = _schtasks("/Create", "/TN", TASK_NAME, "/XML", str(tmp), "/F")
    tmp.unlink(missing_ok=True)
    if r.returncode == 0:
        return (f"Jadwal aktif: Senin–Jumat pukul {hhmm}. Bila laptop mati/tidur saat itu, update berjalan "
                "begitu laptop menyala kembali.")
    return f"Gagal membuat jadwal: {(r.stderr or r.stdout).strip()}"


# ============================================================== jendela aplikasi
def gui():
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk

    import pandas as pd

    from src import positions as POS

    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("900x640")
    root.minsize(760, 520)
    try:
        ttk.Style().theme_use("vista" if sys.platform.startswith("win") else "clam")
    except tk.TclError:
        pass
    q: queue.Queue = queue.Queue()

    class QH(logging.Handler):
        def emit(self, record):
            q.put(("log", self.format(record)))

    qh = QH()
    qh.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
    logging.getLogger("ihsg").addHandler(qh)

    # ---------- header
    top = ttk.Frame(root, padding=(14, 12, 14, 4))
    top.pack(fill="x")
    ttk.Label(top, text=APP_NAME, font=("Segoe UI", 16, "bold")).pack(anchor="w")
    status = tk.StringVar()
    ttk.Label(top, textvariable=status, foreground="#555").pack(anchor="w")

    # ---------- ringkasan
    box = ttk.LabelFrame(root, text="Ringkasan terakhir", padding=10)
    box.pack(fill="x", padx=14, pady=6)
    summary = tk.StringVar()
    ttk.Label(box, textvariable=summary, justify="left", font=("Segoe UI", 10)).pack(anchor="w")

    # ---------- tombol
    bar = ttk.Frame(root, padding=(14, 4))
    bar.pack(fill="x")
    btn_update = ttk.Button(bar, text="▶  Update sekarang")
    btn_update.pack(side="left")
    ttk.Button(bar, text="Buka dashboard", command=lambda: open_dash()).pack(side="left", padx=6)
    ttk.Button(bar, text="Posisi saya", command=lambda: positions_window()).pack(side="left")
    ttk.Button(bar, text="Pengaturan", command=lambda: settings_window()).pack(side="left", padx=6)
    ttk.Button(bar, text="Folder data", command=lambda: open_path(ROOT)).pack(side="left")

    sched = tk.BooleanVar(value=schedule_exists())
    srow = ttk.Frame(root, padding=(14, 6))
    srow.pack(fill="x")
    ttk.Checkbutton(srow, text="Update otomatis setiap hari bursa (Senin–Jumat) pukul 17:30", variable=sched,
                    command=lambda: toggle_schedule()).pack(side="left")

    prog = ttk.Progressbar(root, mode="indeterminate")
    prog.pack(fill="x", padx=14, pady=(4, 0))
    logbox = scrolledtext.ScrolledText(root, height=14, font=("Consolas", 9), state="disabled", wrap="word")
    logbox.pack(fill="both", expand=True, padx=14, pady=(6, 14))

    def add_log(line: str):
        logbox.configure(state="normal")
        logbox.insert("end", line + "\n")
        logbox.see("end")
        logbox.configure(state="disabled")

    def refresh():
        d = load_json(ROOT / "docs" / "data" / "latest.json")
        last = load_json(LAST, {}) or {}
        if not d:
            status.set("Belum ada data. Klik “Update sekarang” (pertama kali sekitar 5–15 menit).")
            summary.set("—")
            return
        auto = ""
        if last:
            auto = f" · update terakhir {last.get('when')} " + ("✓" if last.get("ok") else f"✗ ({last.get('error', '')[:60]})")
        status.set(f"Data per {d['as_of']} · diperbarui {d['generated_at']}{auto}")
        m = d["market"]
        lines = [f"IHSG {m['bench']:,.0f} ({m['bench_chg'] * 100:+.2f}%) · Pasar {m['regime']} · "
                 f"{m['universe']} saham ≥ Rp 5 T".replace(",", ".")]
        for h, nm in (("short", "Pendek"), ("medium", "Menengah"), ("long", "Panjang")):
            b = d["horizons"][h]
            buys = ", ".join(p["code"] for p in b["buys"][:6]) or "tidak ada"
            extra = f" · {b['n_held']} tertahan filter" if b.get("n_held") else ""
            alert = " · ⚠ aturan keluar aktif" if b.get("market_exit_active") else ""
            lines.append(f"{nm}: beli {buys}{extra}{alert}")
        pos = d.get("positions") or []
        if pos:
            need = [f"{p['code']} {p['status']}" for p in pos if p.get("rank", 3) < 3]
            lines.append(f"Posisi Anda: {len(pos)} · " + (", ".join(need) if need else "semua TAHAN"))
        summary.set("\n".join(lines))

    def open_dash():
        p = dashboard_path()
        if not p.exists():
            messagebox.showinfo(APP_NAME, "Dashboard belum ada. Klik “Update sekarang” dulu.")
            return
        open_path(p)

    def do_update():
        btn_update.configure(state="disabled")
        prog.start(12)
        add_log("— Mulai update —")

        def work():
            try:
                r = run_update()
                q.put(("done", r))
            except Exception as e:  # noqa: BLE001
                q.put(("fail", str(e)))
        threading.Thread(target=work, daemon=True).start()

    btn_update.configure(command=do_update)

    def poll():
        try:
            while True:
                kind, val = q.get_nowait()
                if kind == "log":
                    add_log(val)
                elif kind in ("done", "fail"):
                    prog.stop()
                    btn_update.configure(state="normal")
                    refresh()
                    if kind == "done":
                        add_log(f"— Selesai dalam {val['seconds']} detik —")
                        if settings().get("open_dashboard"):
                            open_dash()
                    else:
                        add_log(f"— GAGAL: {val} —")
                        messagebox.showerror(APP_NAME, f"Update gagal:\n{val}\n\nDetail ada di logs\\ihsg.log")
        except queue.Empty:
            pass
        root.after(200, poll)

    def toggle_schedule():
        msg = schedule_set(sched.get())
        sched.set(schedule_exists())
        messagebox.showinfo(APP_NAME, msg)

    # ---------- jendela posisi
    def positions_window():
        w = tk.Toplevel(root)
        w.title("Posisi saya")
        w.geometry("980x420")
        w.transient(root)
        cols = ("code", "horizon", "buy_date", "buy_price", "lots", "tp1_done", "sl", "tp1", "tp2", "note", "status")
        heads = ("Kode", "Horizon", "Tgl beli", "Harga beli", "Lot", "Sdh jual 50%", "SL sendiri", "TP1 sendiri",
                 "TP2 sendiri", "Catatan", "Status terakhir")
        tv = ttk.Treeview(w, columns=cols, show="headings", height=12)
        for c, h_ in zip(cols, heads):
            tv.heading(c, text=h_)
            tv.column(c, width=150 if c in ("note", "status") else 95, anchor="w")
        tv.pack(fill="both", expand=True, padx=10, pady=10)
        hl = {"short": "pendek", "medium": "menengah", "long": "panjang"}
        latest = {(p["code"], p["horizon"]): p for p in ((load_json(ROOT / "docs" / "data" / "latest.json") or {})
                                                         .get("positions") or [])}
        df, errs = POS.load(ROOT / "positions.csv")
        for r in df.itertuples(index=False):
            st = latest.get((r.code, r.horizon), {})
            fmt = lambda v: "" if v is None or pd.isna(v) else f"{v:.0f}"  # noqa: E731
            tv.insert("", "end", values=(r.code, hl[r.horizon], r.buy_date.strftime("%Y-%m-%d"), f"{r.buy_price:.0f}",
                                         r.lots, "ya" if r.tp1_done else "", fmt(r.sl_user), fmt(r.tp1_user),
                                         fmt(r.tp2_user), r.note, st.get("status", "")))
        if errs:
            messagebox.showwarning(APP_NAME, "\n".join(errs), parent=w)

        def form(values=None):
            f = tk.Toplevel(w)
            f.title("Posisi")
            f.transient(w)
            f.grab_set()
            labels = [("Kode saham", "code"), ("Horizon", "horizon"), ("Tanggal beli (YYYY-MM-DD)", "buy_date"),
                      ("Harga beli", "buy_price"), ("Jumlah lot", "lots"), ("Sudah jual 50% (TP1)?", "tp1_done"),
                      ("Cut loss sendiri (opsional)", "sl"), ("TP1 sendiri (opsional)", "tp1"),
                      ("TP2 sendiri (opsional)", "tp2"), ("Catatan", "note")]
            vals = dict(zip(cols, values)) if values else {"horizon": "pendek",
                                                           "buy_date": datetime.now().strftime("%Y-%m-%d")}
            vars_ = {}
            for i, (lab, key) in enumerate(labels):
                ttk.Label(f, text=lab).grid(row=i, column=0, sticky="w", padx=10, pady=4)
                if key == "horizon":
                    v = tk.StringVar(value=vals.get(key, "pendek"))
                    ttk.Combobox(f, textvariable=v, values=("pendek", "menengah", "panjang"), state="readonly",
                                 width=18).grid(row=i, column=1, padx=10)
                elif key == "tp1_done":
                    v = tk.BooleanVar(value=vals.get(key) == "ya")
                    ttk.Checkbutton(f, variable=v).grid(row=i, column=1, sticky="w", padx=10)
                else:
                    v = tk.StringVar(value=str(vals.get(key, "") or ""))
                    ttk.Entry(f, textvariable=v, width=22).grid(row=i, column=1, padx=10)
                vars_[key] = v

            def ok():
                code = vars_["code"].get().strip().upper().replace(".JK", "")
                try:
                    pd.Timestamp(vars_["buy_date"].get().strip())
                    price = float(re.sub(r"[^\d]", "", vars_["buy_price"].get()) or "x")
                    lots = int(re.sub(r"[^\d]", "", vars_["lots"].get() or "0") or 0)
                except (ValueError, TypeError):
                    messagebox.showerror(APP_NAME, "Tanggal atau harga beli tidak valid.", parent=f)
                    return
                if not re.fullmatch(r"[A-Z]{4}", code):
                    messagebox.showerror(APP_NAME, "Kode saham harus 4 huruf, mis. BBCA.", parent=f)
                    return
                row = (code, vars_["horizon"].get(), vars_["buy_date"].get().strip(), f"{price:.0f}", lots,
                       "ya" if vars_["tp1_done"].get() else "", vars_["sl"].get().strip(),
                       vars_["tp1"].get().strip(), vars_["tp2"].get().strip(), vars_["note"].get().strip(),
                       vals.get("status", "") if values else "baru")
                if values:
                    tv.item(tv.selection()[0], values=row)
                else:
                    tv.insert("", "end", values=row)
                f.destroy()
            bf = ttk.Frame(f)
            bf.grid(row=len(labels), column=0, columnspan=2, pady=10)
            ttk.Button(bf, text="OK", command=ok).pack(side="left", padx=4)
            ttk.Button(bf, text="Batal", command=f.destroy).pack(side="left", padx=4)

        def edit():
            sel = tv.selection()
            if sel:
                form(tv.item(sel[0], "values"))

        def delete():
            for s in tv.selection():
                tv.delete(s)

        def save():
            lines = [",".join(POS.COLS)]
            for iid in tv.get_children():
                v = list(tv.item(iid, "values"))[:10]
                v[9] = str(v[9]).replace(",", ";")
                lines.append(",".join(str(x) for x in v))
            (ROOT / "positions.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
            messagebox.showinfo(APP_NAME, "Posisi tersimpan. Status dihitung ulang pada update berikutnya.", parent=w)
            w.destroy()
        bf = ttk.Frame(w)
        bf.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(bf, text="Tambah", command=form).pack(side="left")
        ttk.Button(bf, text="Ubah", command=edit).pack(side="left", padx=6)
        ttk.Button(bf, text="Hapus (sudah dijual habis)", command=delete).pack(side="left")
        ttk.Button(bf, text="Simpan", command=save).pack(side="right")
        tv.bind("<Double-1>", lambda e: edit())

    # ---------- jendela pengaturan
    def settings_window():
        st = settings()
        cfg_text = (ROOT / "config.yaml").read_text(encoding="utf-8")
        m = re.search(r"^capital:\s*([\d_]+)", cfg_text, re.M)
        w = tk.Toplevel(root)
        w.title("Pengaturan")
        w.transient(root)
        w.grab_set()
        cap = tk.StringVar(value=f"{int(m.group(1).replace('_', '')):,}".replace(",", ".") if m else "100.000.000")
        tok = tk.StringVar(value=st["telegram_token"])
        chat = tk.StringVar(value=st["telegram_chat_id"])
        od = tk.BooleanVar(value=st["open_dashboard"])
        rows = [("Modal acuan (Rp)", ttk.Entry(w, textvariable=cap, width=40)),
                ("Token bot Telegram", ttk.Entry(w, textvariable=tok, width=40, show="•")),
                ("Chat ID Telegram", ttk.Entry(w, textvariable=chat, width=40))]
        for i, (lab, wid) in enumerate(rows):
            ttk.Label(w, text=lab).grid(row=i, column=0, sticky="w", padx=10, pady=5)
            wid.grid(row=i, column=1, padx=10, pady=5)
        ttk.Checkbutton(w, text="Buka dashboard otomatis setelah update", variable=od).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=10, pady=5)
        ttk.Label(w, text="Token & chat ID disimpan di settings.json di folder aplikasi (laptop Anda).",
                  foreground="#666").grid(row=4, column=0, columnspan=2, sticky="w", padx=10)

        def test_tg():
            from src.notify import send
            ok = send(tok.get().strip(), chat.get().strip(), "✅ Tes dari aplikasi IHSG Signal di laptop berhasil.")
            messagebox.showinfo(APP_NAME, "Pesan tes terkirim." if ok else "Gagal mengirim. Cek token & chat ID.",
                                parent=w)

        def ok():
            digits = re.sub(r"[^\d]", "", cap.get())
            if not digits or int(digits) < 1_000_000:
                messagebox.showerror(APP_NAME, "Modal minimal Rp 1.000.000.", parent=w)
                return
            text = re.sub(r"^capital:\s*[\d_]+", f"capital: {int(digits)}", cfg_text, count=1, flags=re.M)
            (ROOT / "config.yaml").write_text(text, encoding="utf-8")
            save_settings({**st, "telegram_token": tok.get().strip(), "telegram_chat_id": chat.get().strip(),
                           "open_dashboard": bool(od.get())})
            w.destroy()
        bf = ttk.Frame(w)
        bf.grid(row=5, column=0, columnspan=2, pady=10)
        ttk.Button(bf, text="Tes Telegram", command=test_tg).pack(side="left", padx=4)
        ttk.Button(bf, text="Simpan", command=ok).pack(side="left", padx=4)
        ttk.Button(bf, text="Batal", command=w.destroy).pack(side="left", padx=4)

    refresh()
    add_log(f"Folder data: {ROOT}")
    root.after(200, poll)
    root.mainloop()


# ============================================================== uji kemasan
def selftest() -> int:
    import faulthandler

    logs = ROOT / "logs"
    hang = open(logs / "selftest_hang.log", "w", encoding="utf-8")
    faulthandler.dump_traceback_later(240, exit=True, file=hang)   # pengaman: bila macet, cetak posisi & keluar
    out = open(logs / "selftest.log", "w", encoding="utf-8", buffering=1)
    ok = True

    def say(x):
        out.write(x + "\n")
        print(x, flush=True)

    say(f"python {sys.version.split()[0]} · frozen={getattr(sys, 'frozen', False)} · folder={ROOT}")
    for mod in ("pandas", "numpy", "yaml", "requests", "yfinance", "curl_cffi", "cloudscraper", "tkinter"):
        try:
            __import__(mod)
            say(f"import {mod}: OK")
        except Exception as e:  # noqa: BLE001
            fatal = mod != "tkinter" or sys.platform.startswith("win")
            ok &= not fatal
            say(f"import {mod}: {'GAGAL' if fatal else 'gagal (abaikan di non-Windows)'} {e!r}")
    try:
        r = run_update(demo=True)
        exists = (ROOT / "output" / "demo" / "index.html").exists()
        ok &= exists
        say(f"demo pipeline: OK ({r['seconds']} dtk, dashboard {'ada' if exists else 'TIDAK ADA'})")
    except Exception as e:  # noqa: BLE001
        ok = False
        say(f"demo pipeline: GAGAL {e!r}\n{traceback.format_exc()}")

    def timed(label, fn, secs=60):                              # cek jaringan: info saja, dibatasi waktu
        box = {}
        th = threading.Thread(target=lambda: box.update(r=fn()), daemon=True)
        th.start()
        th.join(secs)
        say(f"{label}: " + (box["r"] if "r" in box else f"tidak selesai dalam {secs} dtk (info)"))

    def yahoo():
        try:
            import yfinance as yf
            df = yf.download("BBCA.JK", period="5d", progress=False, auto_adjust=True, threads=False)
            return f"{len(df)} baris"
        except Exception as e:  # noqa: BLE001
            return f"gagal (info) {e!r}"

    def idx_check():
        try:
            from src import idx
            js = idx.get_json("/primary/StockData/GetSecuritiesStock", {"start": 0, "length": 5}, "/", timeout=15)
            return "OK" if js else "diblokir (wajar di server cloud)"
        except Exception as e:  # noqa: BLE001
            return f"gagal (info) {e!r}"

    timed("unduh Yahoo BBCA.JK", yahoo)
    timed("akses idx.co.id", idx_check)
    say("HASIL: " + ("LULUS" if ok else "GAGAL"))
    faulthandler.cancel_dump_traceback_later()
    out.close()
    return 0 if ok else 1


if __name__ == "__main__":
    mode = "selftest" if "--selftest" in sys.argv else "auto" if "--auto" in sys.argv else "gui"
    try:
        init()
        if mode == "selftest":
            code = selftest()
        elif mode == "auto":
            try:
                run_update()
                code = 0
            except Exception:  # noqa: BLE001
                code = 1
        else:
            gui()
            code = 0
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        _crash(mode)
        code = 3
    sys.stdout.flush() if sys.stdout else None
    os._exit(code)                      # keluar tuntas (thread jaringan yang tersisa tidak menahan proses)
