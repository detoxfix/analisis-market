"""Cek kapan bar harian terbaru BEI muncul di Yahoo (dipakai workflow riset)."""
import json
from datetime import datetime, timezone

import yfinance as yf

out = {"now_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "yfinance": yf.__version__}
for t in ["^JKSE", "BBCA.JK", "TLKM.JK"]:
    r = {}
    d = yf.download(t, period="10d", interval="1d", auto_adjust=True, progress=False)
    r["daily_single"] = [str(i) for i in d.index[-3:]]
    tk = yf.Ticker(t)
    h = tk.history(period="10d", interval="1d")
    r["history_1d"] = [str(i) for i in h.index[-3:]]
    h1 = tk.history(period="5d", interval="1h")
    r["history_1h_last"] = [str(i) for i in h1.index[-3:]]
    r["history_1h_last_close"] = [float(x) for x in h1["Close"].iloc[-3:]]
    r["daily_last_close"] = [float(x) for x in h["Close"].iloc[-3:]]
    out[t] = r
m = yf.download(["BBCA.JK", "TLKM.JK", "BBRI.JK"], period="10d", interval="1d", auto_adjust=True,
                group_by="ticker", progress=False, threads=True)
out["multi_index"] = [str(i) for i in m.index[-3:]]
out["multi_tail_close"] = {t: [None if x != x else float(x) for x in m[t]["Close"].iloc[-3:]] for t in ["BBCA.JK", "TLKM.JK"]}
print(json.dumps(out, indent=1))
open("docs/data/cek_yahoo.json", "w").write(json.dumps(out, indent=1))
