"""Dashboard HTML statis (satu file, data tertanam) — bisa dibuka lokal atau di-host via GitHub Pages."""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = r"""<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IHSG Signal</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#14171c;--mute:#5f6b7a;--line:#e3e7ec;--chip:#eef1f5;
--buy:#0a8f5a;--buy-bg:#e3f6ee;--sbuy:#06703f;--sell:#c8323b;--sell-bg:#fde9ea;--hold:#7a6400;--hold-bg:#fbf4d9;--accent:#1f5eff}
@media (prefers-color-scheme:dark){:root{--bg:#0e1116;--card:#161b22;--ink:#e6edf3;--mute:#8b98a8;--line:#28303b;--chip:#1f2630;
--buy:#3fcf8e;--buy-bg:#123826;--sbuy:#5fe3a6;--sell:#ff6b73;--sell-bg:#3b1519;--hold:#e3c55b;--hold-bg:#332b0c;--accent:#6c9bff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{padding:18px 16px 8px;max-width:1180px;margin:auto}
h1{font-size:20px;margin:0 0 4px;letter-spacing:-.2px}.sub{color:var(--mute);font-size:13px}
.wrap{max-width:1180px;margin:auto;padding:0 16px 40px}
.demo{background:var(--sell-bg);color:var(--sell);padding:8px 12px;border-radius:8px;margin:8px 0;font-weight:600}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.kpi b{display:block;font-size:18px}.kpi span{color:var(--mute);font-size:12px}
.tabs,.seg{display:flex;gap:6px;overflow-x:auto;padding:4px 0;margin:6px 0}
.tabs button,.seg button{border:1px solid var(--line);background:var(--card);color:var(--ink);padding:7px 12px;border-radius:999px;cursor:pointer;white-space:nowrap;font:inherit}
.tabs button.on,.seg button.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.panel{display:none}.panel.on{display:block}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.code{font-size:18px;font-weight:700}.name{color:var(--mute);font-size:12px}
.badge{font-size:11px;font-weight:700;padding:3px 8px;border-radius:6px;white-space:nowrap}
.b-sb{background:var(--sbuy);color:#fff}.b-buy{background:var(--buy-bg);color:var(--buy)}
.b-sell{background:var(--sell-bg);color:var(--sell)}.b-ss{background:var(--sell);color:#fff}.b-hold{background:var(--hold-bg);color:var(--hold)}.b-na{background:var(--chip);color:var(--mute)}
.bar{height:6px;background:var(--chip);border-radius:4px;margin:10px 0 4px;overflow:hidden}.bar i{display:block;height:100%}
.meta{display:flex;justify-content:space-between;color:var(--mute);font-size:12px}
.lv{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0}
.lv div{background:var(--chip);border-radius:8px;padding:7px 8px}.lv span{display:block;color:var(--mute);font-size:11px}.lv b{font-size:14px}
.pos{color:var(--buy)}.neg{color:var(--sell)}
.note{font-size:12.5px;margin:6px 0}.note strong{display:block;font-size:11px;color:var(--mute);text-transform:uppercase;letter-spacing:.4px}
ul{margin:4px 0 0;padding-left:18px}li{margin:2px 0}
.tbl{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{position:sticky;top:0;background:var(--card);color:var(--mute);font-weight:600;cursor:pointer}th:first-child,td:first-child{text-align:left}
input[type=search]{width:100%;max-width:320px;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);font:inherit;margin:6px 0 10px}
h2{font-size:16px;margin:18px 0 8px}h3{font-size:14px;margin:14px 0 6px}
.muted{color:var(--mute)}.empty{padding:20px;text-align:center;color:var(--mute);background:var(--card);border:1px dashed var(--line);border-radius:12px}
.method p,.method li{max-width:860px}
footer{color:var(--mute);font-size:12px;margin-top:24px}
</style>
</head>
<body>
<header>
  <h1>IHSG Signal</h1>
  <div class="sub" id="sub"></div>
</header>
<div class="wrap">
  <div id="demo"></div>
  <div class="kpis" id="kpis"></div>
  <nav class="tabs" id="tabs">
    <button data-p="buy" class="on">Sinyal Beli</button><button data-p="sell">Sinyal Jual</button>
    <button data-p="all">Semua Saham</button><button data-p="track">Track Record</button>
    <button data-p="bt">Backtest</button><button data-p="method">Metodologi</button>
  </nav>
  <section class="panel on" id="p-buy"><div class="seg" id="seg-buy"></div><div id="buy-body"></div></section>
  <section class="panel" id="p-sell"><div class="seg" id="seg-sell"></div><div id="sell-body"></div></section>
  <section class="panel" id="p-all"><input type="search" id="q" placeholder="Cari kode / nama / sektor..."><div class="tbl"><table id="all-t"></table></div></section>
  <section class="panel" id="p-track"></section>
  <section class="panel" id="p-bt"></section>
  <section class="panel method" id="p-method"></section>
  <footer id="foot"></footer>
</div>
<script>
const D = /*__DATA__*/null;
const H = {short:"Pendek",medium:"Menengah",long:"Panjang"};
const nf = new Intl.NumberFormat("id-ID",{maximumFractionDigits:0});
const n = v => v==null?"-":nf.format(v);
const pct = (v,d=1) => v==null?"-":(v>0?"+":"")+(100*v).toFixed(d).replace(".",",")+"%";
const dec = (v,d=1) => v==null?"-":v.toFixed(d).replace(".",",");
const pctp = (v,d=1) => v==null?"-":(100*v).toFixed(d).replace(".",",")+"%";
const tri = v => v==null?"-":"Rp "+(v/1e12).toFixed(1).replace(".",",")+" T";
const cls = s => ({"STRONG BUY":"b-sb","BUY":"b-buy","SELL":"b-sell","STRONG SELL":"b-ss","HOLD":"b-hold"}[s]||"b-na");
const badge = (s,sc) => `<span class="badge ${cls(s)}">${s}${sc!=null?" · "+sc.toFixed(0):""}</span>`;
const esc = s => String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const $ = id => document.getElementById(id);

function header(){
  const m=D.market;
  $("sub").textContent=`Data per ${D.as_of} · diperbarui ${D.generated_at} WIB · IHSG ${n(m.bench)} (${pct(m.bench_chg,2)}) · Pasar ${m.regime}`;
  if(D.demo) $("demo").innerHTML='<div class="demo">MODE DEMO — data sintetis untuk uji coba, bukan data pasar asli.</div>';
  const k=[[m.universe,"saham lolos filter (≥ "+tri(D.params.min_market_cap)+")"],[m.regime,"kondisi pasar (IHSG vs EMA20/SMA200)"]];
  for(const h of ["short","medium","long"]){const b=D.horizons[h];k.push([b.buys.length+" beli · "+b.sells.length+" jual",`${H[h]} · kas ${pctp(b.cash_weight,0)}`]);}
  $("kpis").innerHTML=k.map(([a,b])=>`<div class="kpi"><b>${esc(a)}</b><span>${esc(b)}</span></div>`).join("");
}
function seg(id,cb){
  const el=$(id);el.innerHTML=["short","medium","long"].map((h,i)=>`<button data-h="${h}" class="${i?"":"on"}">${H[h]}</button>`).join("");
  el.onclick=e=>{const b=e.target.closest("button");if(!b)return;[...el.children].forEach(x=>x.classList.toggle("on",x===b));cb(b.dataset.h);};
  cb("short");
}
function scorebar(s){const w=Math.min(100,Math.abs(s));const col=s>=0?"var(--buy)":"var(--sell)";return `<div class="bar"><i style="width:${w}%;background:${col}"></i></div>`;}
function buyCard(p){
  return `<div class="card"><div class="top"><div><div class="code">${p.code}</div><div class="name">${esc(p.name)} · ${esc(p.sector)}</div></div>${badge(p.signal,p.score)}</div>
  ${scorebar(p.score)}<div class="meta"><span>Bobot ${pctp(p.weight_total)} dari modal (${pctp(p.weight_bucket,0)} bucket)</span><span>Keyakinan ${pctp(p.confidence,0)}</span></div>
  <div class="lv">
   <div><span>Harga</span><b>${n(p.price)}</b> <small class="${p.chg_1d>=0?"pos":"neg"}">${pct(p.chg_1d)}</small></div>
   <div><span>Area beli</span><b>${n(p.entry_low)}–${n(p.entry_high)}</b></div>
   <div><span>Lot (modal acuan)</span><b>${n(p.lots)}</b></div>
   <div><span>TP1</span><b class="pos">${n(p.tp1)}</b> <small>${pct(p.tp1_pct)}</small></div>
   <div><span>TP2</span><b class="pos">${n(p.tp2)}</b> <small>${pct(p.tp2_pct)}</small></div>
   <div><span>Cut loss</span><b class="neg">${n(p.sl)}</b> <small>${pct(p.sl_pct)}</small></div>
   <div><span>R:R bersih</span><b>${dec(p.rr1)} / ${dec(p.rr2)}</b></div>
   <div><span>Lama hold</span><b>${esc(p.hold)}</b></div>
   <div><span>Mcap</span><b>${tri(p.mcap)}</b></div>
  </div>
  <div class="note"><strong>Kapan beli</strong>${esc(p.when_buy)}</div>
  <div class="note"><strong>Kapan jual</strong>${esc(p.when_sell)}</div>
  <div class="note"><strong>Alasan</strong><ul>${p.reasons.map(r=>`<li>${esc(r)}</li>`).join("")}</ul></div>
  ${p.risks.length?`<div class="note"><strong>Risiko</strong><ul>${p.risks.map(r=>`<li>${esc(r)}</li>`).join("")}</ul></div>`:""}
  ${p.lots_limited_by_risk?'<div class="note muted">Lot dibatasi aturan risiko '+pctp(D.params.risk_per_trade,0)+' modal per posisi.</div>':""}
  </div>`;
}
function renderBuy(h){
  const b=D.horizons[h];
  let html=`<p class="muted">${esc(b.label)} · alokasi ${pctp(b.allocation,0)} modal · ${b.buys.length} posisi · kas ${pctp(b.cash_weight,0)} dari bucket</p>`;
  if(b.regime_text) html+=`<p class="muted"><b>Porsi dikurangi menjadi ${pctp(b.regime_scale,0)}</b> karena ${esc(b.regime_text)}. Sisanya ditahan sebagai kas.</p>`;
  html+=b.buys.length?`<div class="grid">${b.buys.map(buyCard).join("")}</div>`:`<div class="empty">Belum ada sinyal beli yang lolos syarat masuk untuk horizon ini. Tetap di kas.${b.n_held?" ("+b.n_held+" sinyal beli tertahan filter — lihat watchlist)":""}</div>`;
  if(b.watchlist.length){html+=`<h3>Watchlist (sinyal beli yang belum dieksekusi)</h3><div class="tbl"><table><tr><th>Kode</th><th>Sinyal</th><th>Harga</th><th>Area beli</th><th>TP1</th><th>SL</th><th>Keterangan</th></tr>${b.watchlist.map(w=>`<tr><td><b>${w.code}</b></td><td>${badge(w.signal,w.score)}</td><td>${n(w.price)}</td><td>${n(w.entry_low)}–${n(w.entry_high)}</td><td>${n(w.tp1)}</td><td>${n(w.sl)}</td><td style="text-align:left">${esc(w.held||"")}</td></tr>`).join("")}</table></div>`;}
  if(b.rules){const r=b.rules;html+=`<p class="muted">Aturan masuk: skor ≥ ${r.min_score??30}${r.market_filter&&r.market_filter!=="none"?" · IHSG di atas "+r.market_filter.toUpperCase():""}${r.trend_filter&&r.trend_filter!=="none"?" · harga di atas "+r.trend_filter.toUpperCase():""}${r.entry_mode==="limit"?" · antre di area bawah "+r.limit_days+" hari":" · beli di pembukaan T+1"}${r.trail_ma?" · trailing EMA"+r.trail_ma+" setelah TP1":""}</p>`;}
  $("buy-body").innerHTML=html;
}
function renderSell(h){
  const s=D.horizons[h].sells;
  $("sell-body").innerHTML=s.length?`<p class="muted">Untuk pemegang saham. Tidak ada short selling — sinyal jual berarti keluar/kurangi posisi & hindari beli.</p><div class="grid">${s.map(p=>`<div class="card"><div class="top"><div><div class="code">${p.code}</div><div class="name">${esc(p.name)} · ${esc(p.sector)}</div></div>${badge(p.signal,p.score)}</div>${scorebar(p.score)}
  <div class="lv"><div><span>Harga</span><b>${n(p.price)}</b> <small class="${p.chg_1d>=0?"pos":"neg"}">${pct(p.chg_1d)}</small></div><div><span>Tindakan</span><b>${esc(p.action)}</b></div><div><span>Porsi jual</span><b>${pctp(p.sell_portion,0)}</b></div>
  <div><span>Area jual</span><b>${n(p.sell_zone_low)}–${n(p.sell_zone_high)}</b></div><div><span>Level breakdown</span><b class="neg">${n(p.breakdown_level)}</b></div><div><span>Mcap</span><b>${tri(p.mcap)}</b></div></div>
  <div class="note"><strong>Kapan jual</strong>${esc(p.when_sell)}</div><div class="note"><strong>Alasan</strong><ul>${p.reasons.map(r=>`<li>${esc(r)}</li>`).join("")}</ul></div></div>`).join("")}</div>`:`<div class="empty">Tidak ada sinyal jual untuk horizon ini.</div>`;
}
let sortK="mcap",sortD=-1;
function renderAll(){
  const q=$("q").value.toLowerCase();
  const rows=D.all.filter(r=>!q||(r.code+" "+r.name+" "+r.sector).toLowerCase().includes(q));
  const key=r=>["short","medium","long"].includes(sortK)?(r[sortK].score??-999):(r[sortK]??-1e18);
  rows.sort((a,b)=>sortK==="code"?sortD*a.code.localeCompare(b.code):sortD*(key(a)-key(b)));
  const th=[["code","Kode"],["price","Harga"],["chg_1d","Chg"],["mcap","Mcap"],["short","Pendek"],["medium","Menengah"],["long","Panjang"],["pe","PER"],["pb","PBV"],["roe","ROE"],["div_yield","Yield"]];
  $("all-t").innerHTML=`<tr>${th.map(([k,l])=>`<th data-k="${k}">${l}${k===sortK?(sortD>0?" ▲":" ▼"):""}</th>`).join("")}</tr>`+rows.map(r=>`<tr><td><b>${r.code}</b><div class="name">${esc(r.name)}</div></td><td>${n(r.price)}</td><td class="${r.chg_1d>=0?"pos":"neg"}">${pct(r.chg_1d)}</td><td>${tri(r.mcap)}</td>
  <td>${badge(r.short.signal,r.short.score)}</td><td>${badge(r.medium.signal,r.medium.score)}</td><td>${badge(r.long.signal,r.long.score)}</td>
  <td>${dec(r.pe)}</td><td>${dec(r.pb,2)}</td><td>${pctp(r.roe)}</td><td>${pctp(r.div_yield)}</td></tr>`).join("");
  $("all-t").querySelectorAll("th").forEach(t=>t.onclick=()=>{const k=t.dataset.k;sortD=k===sortK?-sortD:-1;sortK=k;renderAll();});
}
function statRow(lbl,s){if(!s||!s.n)return `<tr><td>${lbl}</td><td colspan="5" class="muted">belum ada transaksi selesai</td></tr>`;
  return `<tr><td>${lbl}</td><td>${s.n}</td><td>${pctp(s.win_rate,0)}</td><td class="${s.avg_ret>=0?"pos":"neg"}">${pct(s.avg_ret)}</td><td>${dec(s.profit_factor,2)}</td><td>${s.avg_days==null?pct(s.median_ret):dec(s.avg_days)}</td></tr>`;}
function renderTrack(){
  const t=D.track||{by_horizon:{},open:[],recent_closed:[]};
  let h=`<h2>Kinerja rekomendasi riil</h2><p class="muted">Setiap rekomendasi beli dicatat lalu dievaluasi otomatis dengan harga berikutnya (masuk T+1 open, TP/SL/time-stop, termasuk biaya). ${t.cancelled||0} rekomendasi batal karena gap up melewati batas kejar.</p>
  <div class="tbl"><table><tr><th>Horizon</th><th>Transaksi</th><th>Win rate</th><th>Rata-rata</th><th>Profit factor</th><th>Median</th></tr>
  ${["short","medium","long"].map(k=>statRow(H[k],t.by_horizon[k])).join("")}${statRow("Total",t.all)}</table></div>`;
  const tb=(rows,cl)=>rows.length?`<div class="tbl"><table><tr><th>Tgl sinyal</th><th>Kode</th><th>Horizon</th><th>Entry</th><th>TP1</th><th>SL</th><th>Status</th><th>Hasil</th><th>Hari</th></tr>${rows.map(r=>`<tr><td>${r.date}</td><td><b>${r.code}</b></td><td>${H[r.horizon]}</td><td>${n(r.entry_px??r.entry)}</td><td>${n(r.tp1)}</td><td>${n(r.sl)}</td><td>${esc(r.outcome)}</td><td class="${(r.ret||0)>=0?"pos":"neg"}">${r.ret==null?"-":pct(r.ret)}</td><td>${r.days??"-"}</td></tr>`).join("")}</table></div>`:`<div class="empty">${cl}</div>`;
  h+=`<h3>Posisi terbuka</h3>`+tb(t.open,"Belum ada posisi terbuka.")+`<h3>Selesai terakhir</h3>`+tb(t.recent_closed,"Belum ada rekomendasi yang selesai. Track record terisi seiring waktu.");
  $("p-track").innerHTML=h;
}
function renderBt(){
  const b=D.backtest;
  if(!b||!b.results){$("p-bt").innerHTML='<div class="empty">Backtest belum dijalankan.</div>';return;}
  let h=`<h2>Backtest aturan sinyal</h2><p class="muted">Dijalankan ${esc(b.generated_at)}. Masuk saat skor menembus ambang BUY, keluar via TP/SL/time-stop, biaya termasuk. Universe memakai market cap saat ini (bias survivorship) — anggap sebagai batas atas, bukan janji hasil.</p>
  <div class="tbl"><table><tr><th>Horizon</th><th>Transaksi</th><th>Win rate</th><th>Rata-rata</th><th>Profit factor</th><th>Rata hari</th></tr>`;
  for(const [k,s] of Object.entries(b.results)){h+=statRow(H[k]+" (semua)",s);if(s.in_sample)h+=statRow(H[k]+" · in-sample",s.in_sample);if(s.out_sample)h+=statRow(H[k]+" · out-of-sample",s.out_sample);if(s.strong_only)h+=statRow(H[k]+" (STRONG BUY saja)",s.strong_only);}
  h+=`</table></div>`;
  for(const [k,s] of Object.entries(b.results)) if(s.by_year) h+=`<p class="muted">${H[k]} per tahun: ${Object.entries(s.by_year).map(([y,v])=>y+": "+(v.n?v.n+" trx, rata "+pct(v.avg_ret)+", PF "+dec(v.profit_factor,2):"-")).join(" · ")}</p>`;
  for(const [k,s] of Object.entries(b.results)) if(s.outcomes) h+=`<p class="muted">${H[k]}: periode ${s.period?s.period.join(" s/d "):"-"} · hasil keluar: ${Object.entries(s.outcomes).map(([a,c])=>a+" "+c).join(", ")}</p>`;
  $("p-bt").innerHTML=h;
}
function renderMethod(){
  const p=D.params;
  $("p-method").innerHTML=`<h2>Cara kerja</h2>
  <p><b>Universe.</b> Hanya saham BEI dengan kapitalisasi pasar ≥ ${tri(p.min_market_cap)} (jumlah saham × harga penutupan terakhir), rata-rata nilai transaksi 20 hari ≥ Rp ${n(p.min_avg_value_20d/1e9)} M, masih aktif diperdagangkan, dan bukan papan pemantauan khusus.</p>
  <p><b>Skor −100…+100</b> dari komponen berbobot. ≥ ${p.thresholds.strong_buy} STRONG BUY, ≥ ${p.thresholds.buy} BUY, ≤ ${p.thresholds.sell} SELL, ≤ ${p.thresholds.strong_sell} STRONG SELL, selain itu HOLD.</p>
  <ul><li><b>Pendek (3–10 hari):</b> harga vs EMA20, EMA9/EMA20, momentum MACD, zona RSI, lonjakan volume, breakout 20 hari, kondisi IHSG.</li>
  <li><b>Menengah (1–3 bulan):</b> harga vs SMA50, struktur SMA50/100, ADX/DMI, momentum 3 bulan, kekuatan relatif vs IHSG, rezim RSI, tren MACD.</li>
  <li><b>Panjang (6–24 bulan):</b> 40% teknikal (SMA200, kemiringan SMA200, momentum 12-1 bulan) + 60% fundamental (ROE, PER & PBV relatif sektor, DER, dividend yield, pertumbuhan laba).</li></ul>
  <p><b>Rencana trading.</b> Area beli = harga penutupan s/d koreksi ke support (EMA20/SMA50 atau sebagian ATR). Cut loss berbasis ATR dengan batas persentase maksimum per horizon. TP1/TP2 = kelipatan risiko (R). Semua harga dibulatkan ke fraksi harga BEI. R:R dihitung bersih biaya beli ${pctp(p.fees.buy,2)} & jual ${pctp(p.fees.sell,2)}.</p>
  <p><b>Bobot.</b> Di tiap horizon, bobot ∝ skor ÷ volatilitas (ATR%), dibatasi bobot maksimum per saham dan per sektor; sisanya kas. Jumlah lot dihitung dari modal acuan Rp ${n(p.capital)} dan dibatasi agar rugi maksimal per posisi ≤ ${pctp(p.risk_per_trade,0)} modal.</p>
  <h3>Sumber data</h3><ul>${D.sources.map(s=>`<li>${esc(s)}</li>`).join("")}</ul>
  <h3>Disclaimer</h3><p>Aplikasi ini alat bantu analisis kuantitatif, bukan nasihat investasi dan bukan ajakan membeli/menjual efek. Data gratis dapat terlambat atau keliru — cek ulang harga di aplikasi sekuritas sebelum bertransaksi. Kinerja masa lalu tidak menjamin hasil di masa depan.</p>`;
}
$("tabs").onclick=e=>{const b=e.target.closest("button");if(!b)return;document.querySelectorAll("#tabs button").forEach(x=>x.classList.toggle("on",x===b));document.querySelectorAll(".panel").forEach(p=>p.classList.toggle("on",p.id==="p-"+b.dataset.p));};
header();seg("seg-buy",renderBuy);seg("seg-sell",renderSell);$("q").oninput=renderAll;renderAll();renderTrack();renderBt();renderMethod();
$("foot").textContent="IHSG Signal · alat bantu analisis, bukan nasihat investasi · "+D.generated_at;
</script>
</body>
</html>
"""


def write_html(data: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    path.write_text(TEMPLATE.replace("/*__DATA__*/null", payload), encoding="utf-8")
