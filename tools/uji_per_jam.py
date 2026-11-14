"""Uji: buang bar harian terakhir, isi dari data per jam, bandingkan dengan bar harian resmi."""
import json
import sys

import pandas as pd

sys.path.insert(0, ".")
from src import data as D  # noqa: E402
from src.utils import now_wib  # noqa: E402

latest = json.load(open("docs/data/latest.json"))
tickers = [r["code"] + ".JK" for r in latest["all"]] + ["^JKSE"]
px = D.download_prices(tickers, period="3mo")
real = {t: df.iloc[-1] for t, df in px.items()}
last = max(df.index[-1] for df in px.values())
cut = {t: df.iloc[:-1] for t, df in px.items() if df.index[-1] == last}
res = D.fill_latest_from_hourly(cut, now_wib())
rows = []
for t, df in cut.items():
    if df.index[-1] != last:
        rows.append({"t": t, "filled": False})
        continue
    s, r = df.iloc[-1], real[t]
    rows.append({"t": t, "filled": True, **{k.lower(): float(s[k] / r[k] - 1) if r[k] else None
                                            for k in ("Open", "High", "Low", "Close", "Volume")}})
f = pd.DataFrame([x for x in rows if x["filled"]])
out = {"last": str(last.date()), "n": len(rows), "filled": int(len(f)), "fill_result": res,
       "close_exact": int((f["close"].abs() < 1e-6).sum()), "close_max_diff": float(f["close"].abs().max()),
       "open_exact": int((f["open"].abs() < 1e-6).sum()), "high_exact": int((f["high"].abs() < 1e-6).sum()),
       "low_exact": int((f["low"].abs() < 1e-6).sum()),
       "volume_median_diff": float(f["volume"].median()), "volume_p10": float(f["volume"].quantile(.1)),
       "volume_p90": float(f["volume"].quantile(.9)),
       "worst_close": f.reindex(f["close"].abs().sort_values(ascending=False).index).head(8).to_dict("records"),
       "not_filled": [x["t"] for x in rows if not x["filled"]]}
json.dump(out, open("docs/data/uji_per_jam.json", "w"), indent=1)
print(json.dumps(out, indent=1))
