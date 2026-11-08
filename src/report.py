"""Dashboard HTML statis (satu file, data tertanam) — bisa dibuka lokal atau di-host via GitHub Pages."""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = r"""<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>PANDU · Sinyal Saham IHSG</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Condensed:wght@500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0F1B24; --panel:#15232E; --panel2:#1A2B38; --line:#243848; --line2:#2E4558;
  --ink:#E4ECF1; --mute:#8299AA; --dim:#5D7383;
  --brass:#E8B04B; --brass-dim:rgba(232,176,75,.16);
  --buy:#3CCB9B; --buy-dim:rgba(60,203,155,.16); --sell:#F0656B; --sell-dim:rgba(240,101,107,.16);
  --hold:#9FB3C2; --hold-dim:rgba(159,179,194,.13);
  --accent:var(--brass); --cond:"Barlow Condensed","Segoe UI Semibold","Arial Narrow",sans-serif; --sans:Barlow,"Segoe UI",system-ui,sans-serif;
}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Barlow,"Segoe UI",system-ui,sans-serif;font-variant-numeric:tabular-nums}
a{color:var(--brass)}
:focus-visible{outline:2px solid var(--brass);outline-offset:2px}
.wrap{max-width:1220px;margin:0 auto;padding:0 20px 56px}
.pos{color:var(--buy)}.neg{color:var(--sell)}.muted{color:var(--mute)}

/* ---------- kepala */
.top{display:flex;justify-content:space-between;align-items:baseline;gap:16px;flex-wrap:wrap;padding:18px 0 10px}
.brand{font:700 26px/1 var(--cond);letter-spacing:.3px;margin:0}
.brand{color:var(--brass);letter-spacing:1.5px}
.brand small{font:500 14px var(--sans);color:var(--mute);letter-spacing:0;margin-left:10px}
.brand abbr{text-decoration:none;cursor:help}
.alarm{display:flex;gap:10px;align-items:baseline;margin:0 0 12px;padding:9px 12px;border-radius:7px;font-size:14px;background:var(--panel2);border-left:3px solid var(--brass)}
.alarm.bad{border-left-color:var(--sell)}.alarm b{white-space:nowrap}
.mon{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin:14px 0 6px}
.mon .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.mon .lv{font:700 18px/1.1 var(--cond);letter-spacing:.4px;margin:2px 0 6px}
.lv.ok{color:var(--buy)}.lv.warn{color:var(--brass)}.lv.bad{color:var(--sell)}.lv.na{color:var(--mute)}
.mon .card p{margin:0;font-size:14px;color:var(--mute)}
.mon .card h4{margin:0;font:600 15px var(--cond);color:var(--ink)}
.prop{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.prop code{background:var(--panel2);padding:1px 6px;border-radius:4px;color:var(--brass)}
.stamp{color:var(--mute);font-size:13px}
.stamp b{color:var(--ink);font-weight:500}
.demo{border:1px solid var(--sell);color:var(--sell);background:var(--sell-dim);padding:9px 14px;border-radius:6px;margin:6px 0 10px;font-weight:600}

/* ---------- status pasar (pembuka) */
.hero{display:grid;grid-template-columns:minmax(200px,250px) minmax(0,1fr) minmax(260px,360px);gap:0;border:1px solid var(--line);border-radius:10px;background:var(--panel);overflow:hidden}
.hero>div{padding:18px 20px}
.hero .idx{border-right:1px solid var(--line)}
.idx .lbl{color:var(--mute);font-size:13px}
.idx .big{display:block;font:600 46px/1.05 var(--cond);letter-spacing:.5px;margin:2px 0}
.idx .chg{font:600 20px/1 var(--cond)}
.idx .ma{margin-top:14px;display:grid;gap:4px;font-size:13px;color:var(--mute)}
.idx .ma b{font-weight:500;color:var(--ink)}
.hchart{padding:10px 8px 4px!important}
.hchart svg{width:100%;height:150px;display:block}
.verdict{border-left:1px solid var(--line);background:var(--panel2)}
.verdict .regime{font:700 30px/1 var(--cond);margin:0 0 6px}
.regime.bear{color:var(--sell)}.regime.bull{color:var(--buy)}.regime.side{color:var(--brass)}
.verdict p{margin:0 0 12px;color:var(--mute);font-size:14px}
.plan{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.plan li{display:grid;grid-template-columns:78px 1fr;gap:8px;font-size:14px;align-items:baseline}
.plan .h{font:600 16px var(--cond);color:var(--ink)}
.plan .act{color:var(--ink)}.plan .act.go{color:var(--buy)}.plan .act.stop{color:var(--sell)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--mute);padding:0 12px 6px}
.legend i{display:inline-block;width:14px;height:2px;margin-right:6px;vertical-align:middle}

/* ---------- navigasi */
.tabs{display:flex;gap:4px;overflow-x:auto;margin:22px 0 0;border-bottom:1px solid var(--line);scrollbar-width:none}
.tabs button{background:none;border:0;border-bottom:2px solid transparent;color:var(--mute);font:600 17px var(--cond);padding:10px 14px 9px;cursor:pointer;white-space:nowrap;letter-spacing:.2px}
.tabs button:hover{color:var(--ink)}
.tabs button.on{color:var(--ink);border-bottom-color:var(--brass)}
.tabs .n{font:500 13px var(--sans);color:var(--dim);margin-left:5px}
.seg{display:inline-flex;margin:16px 0 4px;border:1px solid var(--line);border-radius:7px;overflow:hidden}
.seg button{background:none;border:0;border-right:1px solid var(--line);color:var(--mute);font:500 14px var(--sans);padding:7px 14px;cursor:pointer}
.seg button:last-child{border-right:0}
.seg button.on{background:var(--brass-dim);color:var(--brass)}
.seg .n{color:inherit;opacity:.7;margin-left:4px}
.panel{display:none}.panel.on{display:block}
.intro{color:var(--mute);font-size:14px;margin:12px 0 12px;max-width:78ch}
.nflag{display:inline-block;margin-top:6px;padding:2px 8px;border-radius:4px;font:600 12px var(--sans);background:var(--sell-dim);color:var(--sell);border:1px solid var(--sell)}
.nflag.mid{background:transparent;color:var(--brass);border-color:var(--brass)}
.news{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.news li{font-size:14px;line-height:1.4}.news .cat{color:var(--brass);font-weight:600}.news .cat.hi{color:var(--sell)}
.news a{color:var(--ink)}.news small{color:var(--dim);display:block}
.ncard{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.ncard h4{margin:0 0 8px;font:600 17px var(--cond)}.ncard h4 span{color:var(--mute);font:400 13px var(--sans);margin-left:8px}
.alert{border-left:3px solid var(--sell);background:var(--sell-dim);padding:10px 14px;border-radius:0 6px 6px 0;margin:10px 0;font-size:14px}
.alert b{color:var(--sell)}
.note-cut{border-left:3px solid var(--brass);background:var(--brass-dim);padding:10px 14px;border-radius:0 6px 6px 0;margin:10px 0;font-size:14px}

/* ---------- baris sinyal */
.list{border:1px solid var(--line);border-radius:10px;background:var(--panel);overflow:hidden}
.sig{display:grid;grid-template-columns:170px 150px minmax(260px,1fr) 104px 140px;gap:18px;align-items:center;padding:14px 18px;border-top:1px solid var(--line)}
.sig:first-child{border-top:0}
.tk{font:700 24px/1 var(--cond);letter-spacing:.6px;display:block}
.nm{display:block;color:var(--mute);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sp svg{display:block;width:150px;height:38px}
.px{font:600 18px/1.1 var(--cond);margin-top:2px}.px em{font:500 13px var(--sans);font-style:normal;margin-left:6px}
.alloc b{display:block;font:600 20px/1.1 var(--cond)}.alloc span{color:var(--mute);font-size:12px}
.tag{text-align:right}
.pill{display:inline-block;font:600 14px/1 var(--cond);letter-spacing:.4px;padding:6px 9px 5px;border-radius:5px;white-space:nowrap}
.pill small{font:500 12px var(--sans);margin-left:6px;opacity:.85}
.p-sb{background:var(--buy);color:#06261B}.p-b{background:var(--buy-dim);color:var(--buy)}
.p-s{background:var(--sell-dim);color:var(--sell)}.p-ss{background:var(--sell);color:#2A0709}
.p-h{background:var(--hold-dim);color:var(--hold)}.p-x{background:var(--panel2);color:var(--mute)}
.meter{height:3px;background:var(--line);border-radius:2px;margin-top:8px;overflow:hidden}.meter i{display:block;height:100%}
.sig details{grid-column:1/-1;margin-top:-4px}
.sig summary{cursor:pointer;color:var(--mute);font-size:13px;list-style:none;display:inline-block}
.sig summary::-webkit-details-marker{display:none}
.sig summary::before{content:"▸ ";color:var(--brass)}
.sig details[open] summary::before{content:"▾ "}
.more{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px 26px;padding:12px 0 2px;font-size:14px}
.more h4{margin:0 0 4px;font:600 15px var(--cond);color:var(--brass);letter-spacing:.3px}
.more p{margin:0}.more ul{margin:0;padding-left:18px}.more li{margin:2px 0}
.note{border-left:3px solid var(--brass);background:var(--panel);padding:10px 14px;border-radius:0 6px 6px 0;color:var(--ink);font-size:14px;margin:10px 0 14px}
.kv{display:grid;grid-template-columns:auto auto;gap:2px 14px;justify-content:start}.kv span{color:var(--mute)}

/* ---------- tangga harga */
.lad{position:relative;height:66px}
.lad .track{position:absolute;left:0;right:0;top:26px;height:6px;border-radius:3px;background:var(--line)}
.lad .seg-r{position:absolute;top:26px;height:6px;background:var(--sell-dim);border:1px solid rgba(240,101,107,.45);border-radius:3px 0 0 3px}
.lad .seg-g{position:absolute;top:26px;height:6px;background:var(--buy-dim);border:1px solid rgba(60,203,155,.45);border-radius:0 3px 3px 0}
.lad .zone{position:absolute;top:21px;height:16px;background:var(--brass-dim);border:1px solid var(--brass);border-radius:3px}
.lad .tick{position:absolute;top:22px;width:2px;height:14px;margin-left:-1px}
.lad .lab{position:absolute;top:42px;transform:translateX(-50%);font-size:12px;line-height:1.2;text-align:center;white-space:nowrap}
.lad .lab b{display:block;font:600 14px var(--cond);color:var(--ink)}
.lad .lab.l0{transform:none}.lad .lab.l1{transform:translateX(-100%)}
.lad .now{position:absolute;top:0;transform:translateX(-50%);font:600 13px var(--cond);color:var(--ink);white-space:nowrap}
.lad .now::after{content:"";position:absolute;left:50%;top:15px;margin-left:-5px;border:5px solid transparent;border-top-color:var(--ink)}

/* ---------- tabel */
.tbl{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:9px 12px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
tr:last-child td{border-bottom:0}
th{position:sticky;top:0;background:var(--panel2);color:var(--mute);font:600 14px var(--cond);letter-spacing:.3px;cursor:pointer}
th:first-child,td:first-child{text-align:left}
td .name{color:var(--mute);font-size:12px}
tbody tr:hover td{background:rgba(255,255,255,.02)}
input[type=search]{width:100%;max-width:340px;padding:9px 12px;border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--ink);font:inherit;margin:16px 0 12px}
h2{font:600 24px/1.1 var(--cond);margin:26px 0 8px;letter-spacing:.3px}
h3{font:600 18px var(--cond);margin:22px 0 8px;color:var(--ink)}
.empty{padding:22px;color:var(--mute);background:var(--panel);border:1px dashed var(--line2);border-radius:10px}
.empty b{color:var(--ink)}
.chart{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:10px 0}
.chart svg{width:100%;height:auto;display:block}.chart text{fill:var(--mute);font-size:11px;font-family:var(--sans)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:10px;overflow:hidden;margin:12px 0}
.kpi{background:var(--panel);padding:12px 16px}.kpi b{display:block;font:600 24px/1.1 var(--cond)}.kpi span{color:var(--mute);font-size:13px}
.method p,.method li{max-width:80ch}
footer{color:var(--dim);font-size:13px;margin-top:36px;border-top:1px solid var(--line);padding-top:14px}

@media (max-width:980px){
  .hero{grid-template-columns:1fr 1fr}.hero .hchart{grid-column:1/-1;order:3;border-top:1px solid var(--line)}
  .verdict{border-left:1px solid var(--line)}
  .sig{grid-template-columns:150px 1fr 100px;gap:12px 16px}
  .sig .lad,.sig>.kv{grid-column:1/-1;order:5}.sig .sp{display:none}.sig details{order:6}
}
@media (max-width:620px){
  .wrap{padding:0 16px 48px}
  .hero{grid-template-columns:1fr}.hero .idx,.verdict{border:0;border-bottom:1px solid var(--line)}
  .idx .big{font-size:40px}
  .sig{grid-template-columns:1fr auto;padding:14px;gap:10px 12px}
  .sig .id{order:1}.sig .tag{order:2}
  .sig .alloc{order:3;grid-column:1/-1;display:flex;gap:6px 14px;align-items:baseline;flex-wrap:wrap}
  .sig .alloc b{display:inline;margin:0!important}
  .sig .lad,.sig>.kv{order:4;grid-column:1/-1}
  .sig details{order:5;margin-top:0}
  .lad .lab{font-size:11px}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1 class="brand"><abbr title="Portofolio · Analisis · Notifikasi · Disiplin risiko · Uji balik">PANDU</abbr><small>sinyal saham IHSG</small></h1>
    <div class="stamp" id="stamp"></div>
  </header>
  <div id="demo"></div>
  <section class="hero" id="hero"></section>
  <nav class="tabs" id="tabs">
    <button data-p="buy" class="on">Sinyal beli<span class="n" id="n-buy"></span></button>
    <button data-p="sell">Sinyal jual<span class="n" id="n-sell"></span></button>
    <button data-p="pos" id="tab-pos">Posisi saya<span class="n" id="n-pos"></span></button>
    <button data-p="all">Semua saham<span class="n" id="n-all"></span></button>
    <button data-p="news" id="tab-news">Berita<span class="n" id="n-news"></span></button>
    <button data-p="track">Track record</button>
    <button data-p="bt">Backtest</button>
    <button data-p="method">Cara kerja</button>
  </nav>
  <section class="panel on" id="p-buy"><div class="seg" id="seg-buy"></div><div id="buy-body"></div></section>
  <section class="panel" id="p-sell"><div class="seg" id="seg-sell"></div><div id="sell-body"></div></section>
  <section class="panel" id="p-pos"></section>
  <section class="panel" id="p-all"><input type="search" id="q" placeholder="Cari kode, nama, atau sektor"><div class="tbl"><table id="all-t"></table></div></section>
  <section class="panel" id="p-news"></section>
  <section class="panel" id="p-track"></section>
  <section class="panel" id="p-bt"></section>
  <section class="panel method" id="p-method"></section>
  <footer id="foot"></footer>
</div>
<script>
const D = /*__DATA__*/null;
const H = {short:"Pendek",medium:"Menengah",long:"Panjang"};
const HL = H;
const nf = new Intl.NumberFormat("id-ID",{maximumFractionDigits:0});
const n = v => v==null?"-":nf.format(v);
const pct = (v,d=1) => v==null?"-":(v>0?"+":"")+(100*v).toFixed(d).replace(".",",")+"%";
const dec = (v,d=1) => v==null?"-":v.toFixed(d).replace(".",",");
const pctp = (v,d=1) => v==null?"-":(100*v).toFixed(d).replace(".",",")+"%";
const tri = v => v==null?"-":"Rp "+(v/1e12).toFixed(1).replace(".",",")+" T";
const rpM = v => {if(v==null)return "-";const a=Math.abs(v),s=v<0?"−":"+";return a>=1e12?s+"Rp "+(a/1e12).toFixed(2).replace(".",",")+" T":s+"Rp "+(a/1e9).toFixed(1).replace(".",",")+" M";};
const BL=["Jan","Feb","Mar","Apr","Mei","Jun","Jul","Agu","Sep","Okt","Nov","Des"];
const tgl = s => {if(!s)return "-";const [y,m,d]=s.slice(0,10).split("-");return `${+d} ${BL[+m-1]} ${y}`;};
const esc = s => String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const $ = id => document.getElementById(id);
const PILL={"STRONG BUY":"p-sb","BUY":"p-b","SELL":"p-s","STRONG SELL":"p-ss","HOLD":"p-h"};
const badge = (s,sc) => `<span class="pill ${PILL[s]||"p-x"}">${s==="N/A"?"–":s}${sc!=null?`<small>${sc.toFixed(0)}</small>`:""}</span>`;
const PCLS={"JUAL SEMUA":"p-ss","JUAL 50%":"p-s","WASPADA":"p-h","TAHAN":"p-x","DATA":"p-x"};

function spark(a,col,w=150,h=38){
  if(!a||a.length<2)return "";
  const lo=Math.min(...a),hi=Math.max(...a),r=hi-lo||1;
  const pts=a.map((v,i)=>`${(i*(w-4)/(a.length-1)+2).toFixed(1)},${(h-3-(v-lo)/r*(h-6)).toFixed(1)}`);
  const last=pts[pts.length-1].split(",");
  return `<svg viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts.join(" ")}" fill="none" stroke="${col}" stroke-width="1.6" stroke-linejoin="round"/><circle cx="${last[0]}" cy="${last[1]}" r="2.6" fill="${col}"/></svg>`;
}
const trendCol = a => !a||a.length<2?"var(--mute)":a[a.length-1]>=a[0]?"var(--buy)":"var(--sell)";

/* tangga harga: cut loss -> area beli -> TP1 -> TP2, dengan penanda harga sekarang */
function ladder(p){
  const vals=[p.sl,p.entry_low,p.entry_high,p.tp1,p.tp2,p.price].filter(v=>v!=null);
  if(vals.length<5)return "";
  const lo=Math.min(...vals),hi=Math.max(...vals),pad=(hi-lo)*.04||1,a=lo-pad,b=hi+pad;
  const x=v=>((v-a)/(b-a)*100).toFixed(2);
  const lab=(v,pos,t,cls,al)=>`<div class="lab ${al||""}" style="left:${pos.toFixed(2)}%"><b class="${cls}">${n(v)}</b><span class="muted">${t}</span></div>`;
  /* label tidak boleh bertumpuk: geser posisi tulisan (garis tetap di posisi asli) */
  const mid=(p.entry_low+p.entry_high)/2, G=15;
  let L=[+x(p.sl),+x(mid),+x(p.tp1),+x(p.tp2)];
  L[1]=Math.max(L[1],L[0]+G); L[2]=Math.max(L[2],L[1]+G);
  L[2]=Math.min(L[2],L[3]-G); L[1]=Math.min(L[1],L[2]-G); L[0]=Math.min(L[0],L[1]-G);
  const labs=lab(p.sl,L[0],"cut loss","neg","l0")+lab(mid,L[1],p.entry_low===p.entry_high?"antre beli":"area beli","")+lab(p.tp1,L[2],"TP1","pos")+lab(p.tp2,L[3],"TP2","pos","l1");
  return `<div class="lad" role="img" aria-label="Cut loss ${n(p.sl)}, area beli ${n(p.entry_low)} sampai ${n(p.entry_high)}, TP1 ${n(p.tp1)}, TP2 ${n(p.tp2)}, harga ${n(p.price)}">
    <div class="track"></div>
    <div class="seg-r" style="left:${x(p.sl)}%;width:${(x(p.entry_low)-x(p.sl)).toFixed(2)}%"></div>
    <div class="seg-g" style="left:${x(p.entry_high)}%;width:${(x(p.tp2)-x(p.entry_high)).toFixed(2)}%"></div>
    <div class="zone" style="left:${x(p.entry_low)}%;width:${Math.max(.8,x(p.entry_high)-x(p.entry_low)).toFixed(2)}%"></div>
    <div class="tick" style="left:${x(p.tp1)}%;background:var(--buy)"></div>
    <div class="now" style="left:${x(p.price)}%">${n(p.price)}</div>
    ${labs}
  </div>`;
}
const fxLine = p => p.foreign_20d==null?"":`<div><h4>Transaksi asing</h4><div class="kv"><span>5 hari</span><b class="${p.foreign_5d>=0?"pos":"neg"}">${rpM(p.foreign_5d)}</b><span>20 hari</span><b class="${p.foreign_20d>=0?"pos":"neg"}">${rpM(p.foreign_20d)}</b>${p.foreign_20d_pct!=null?`<span>porsi nilai transaksi</span><b>${pct(p.foreign_20d_pct)}</b>`:""}</div></div>`;
const meter = s => `<div class="meter"><i style="width:${Math.min(100,Math.abs(s||0))}%;background:${(s||0)>=0?"var(--buy)":"var(--sell)"}"></i></div>`;
const idCell = p => `<div class="id"><span class="tk">${esc(p.code)}</span><span class="nm" title="${esc(p.name)}">${esc(p.name)}</span><span class="nm">${esc(p.sector)}</span></div>`;
const pxCell = p => `<div class="sp">${spark(p.spark,trendCol(p.spark))}<div class="px">${n(p.price)}<em class="${(p.chg_1d||0)>=0?"pos":"neg"}">${pct(p.chg_1d)}</em></div></div>`;

const NEWS_DAYS=()=>((D.news||{}).days||7);
function newsChip(x){if(!x.news||!x.news.length)return "";const hi=x.news.some(w=>w.severity==="tinggi");
  return `<span class="nflag ${hi?"":"mid"}" title="${esc(x.news[0].title)}">⚠ Berita: ${esc(x.news[0].categories[0])}${x.news.length>1?` +${x.news.length-1}`:""}</span>`;}
function newsList(items){return `<ul class="news">${items.map(w=>`<li><span class="cat ${w.severity==="tinggi"?"hi":""}">${esc(w.categories.join(", "))}</span> — ${w.link?`<a href="${esc(w.link)}" target="_blank" rel="noopener">${esc(w.title)}</a>`:esc(w.title)}<small>${[w.source,w.date?tgl(w.date):""].filter(Boolean).map(esc).join(" · ")}</small></li>`).join("")}</ul>`;}
const newsBlock = x => x.news&&x.news.length?`<div><h4>Berita negatif ${NEWS_DAYS()} hari</h4>${newsList(x.news)}<p class="muted" style="margin-top:6px">Peringatan otomatis dari judul berita; baca beritanya sebelum memutuskan.</p></div>`:"";
function buyRow(p){
  return `<article class="sig">${idCell(p)}${pxCell(p)}${ladder(p)}
   <div class="alloc"><b>${pctp(p.weight_total)}</b><span>dari modal</span><b style="margin-top:6px">${n(p.lots)} lot</b><span>modal acuan</span></div>
   <div class="tag">${badge(p.signal,p.score)}${meter(p.score)}${newsChip(p)}</div>
   <details><summary>Rencana, alasan & risiko</summary><div class="more">${newsBlock(p)}
     <div><h4>Kapan beli</h4><p>${esc(p.when_buy)}</p></div>
     <div><h4>Kapan jual</h4><p>${esc(p.when_sell)}</p></div>
     <div><h4>Angka kunci</h4><div class="kv"><span>Cut loss</span><b class="neg">${n(p.sl)} (${pct(p.sl_pct)})</b><span>TP1 / TP2</span><b class="pos">${pct(p.tp1_pct)} / ${pct(p.tp2_pct)}</b><span>R:R bersih</span><b>${dec(p.rr1)} / ${dec(p.rr2)}</b><span>Lama hold</span><b>${esc(p.hold)}</b><span>Kapitalisasi</span><b>${tri(p.mcap)}</b></div>${p.lots_limited_by_risk?`<p class="muted" style="margin-top:6px">Lot dibatasi agar rugi maks. ${pctp(D.params.risk_per_trade,0)} modal per posisi.</p>`:""}</div>
     <div><h4>Alasan</h4><ul>${p.reasons.map(r=>`<li>${esc(r)}</li>`).join("")}</ul></div>
     ${p.risks.length?`<div><h4>Risiko</h4><ul>${p.risks.map(r=>`<li>${esc(r)}</li>`).join("")}</ul></div>`:""}
     ${fxLine(p)}
   </div></details></article>`;
}
function sellRow(p){
  return `<article class="sig">${idCell(p)}${pxCell(p)}
   <div class="kv" style="font-size:14px"><span>Tindakan</span><b>${esc(p.action)}</b><span>Area jual</span><b>${n(p.sell_zone_low)}–${n(p.sell_zone_high)}</b><span>Batas breakdown</span><b class="neg">${n(p.breakdown_level)}</b></div>
   <div class="alloc"><b>${pctp(p.sell_portion,0)}</b><span>porsi dijual</span></div>
   <div class="tag">${badge(p.signal,p.score)}${meter(p.score)}${newsChip(p)}</div>
   <details><summary>Alasan</summary><div class="more">${newsBlock(p)}<div><h4>Kapan jual</h4><p>${esc(p.when_sell)}</p></div><div><h4>Alasan</h4><ul>${p.reasons.map(r=>`<li>${esc(r)}</li>`).join("")}</ul></div>${fxLine(p)}</div></details></article>`;
}

/* ---------- pembuka: IHSG + keputusan hari ini */
function heroChart(S){
  if(!S||S.length<5)return "";
  const W=640,Ht=150,L=4,R=8,T=8,B=8,N=S.length;
  const vals=S.flatMap(r=>[r[1],r[2],r[3]]).filter(v=>v!=null);
  const lo=Math.min(...vals),hi=Math.max(...vals),pad=(hi-lo)*.06;
  const x=i=>L+(W-L-R)*i/(N-1),y=v=>T+(Ht-T-B)*(hi+pad-v)/(hi-lo+2*pad);
  const line=(k,col,w,dash)=>{const pts=S.map((r,i)=>r[k]==null?null:`${x(i).toFixed(1)},${y(r[k]).toFixed(1)}`).filter(Boolean);return pts.length?`<polyline points="${pts.join(" ")}" fill="none" stroke="${col}" stroke-width="${w}" ${dash?'stroke-dasharray="4 4"':""}/>`:"";};
  const last=S[N-1];
  const area=`<path d="M${x(0)},${Ht} L${S.map((r,i)=>`${x(i).toFixed(1)},${y(r[1]).toFixed(1)}`).join(" L")} L${x(N-1)},${Ht} Z" fill="rgba(232,176,75,.07)"/>`;
  return `<svg viewBox="0 0 ${W} ${Ht}" preserveAspectRatio="none" role="img" aria-label="IHSG 6 bulan dengan SMA50 dan SMA200">${area}${line(3,"var(--dim)",1.4,1)}${line(2,"var(--hold)",1.4)}${line(1,"var(--brass)",2)}
   <circle cx="${x(N-1)}" cy="${y(last[1])}" r="3.5" fill="var(--brass)"/></svg>`;
}
function verdictFor(h){
  const b=D.horizons[h];
  if(b.buys.length){const codes=b.buys.slice(0,4).map(p=>p.code).join(", ")+(b.buys.length>4?" …":"");
    return [`Beli ${b.buys.length} saham: ${codes}${b.regime_scale<1?` (porsi ${pctp(b.regime_scale,0)})`:""}`,"go"];}
  if(b.market_exit_active)return ["Tidak beli. Jual posisi yang masih dipegang","stop"];
  return [b.n_held?`Tidak beli, ${b.n_held} sinyal tertahan filter`:"Tidak ada sinyal beli",""];
}
function hero(){
  const m=D.market,S=m.series||[],last=S[S.length-1]||[];
  const reg=m.regime==="Bearish"?"bear":m.regime==="Bullish"?"bull":"side";
  const why=m.above_sma50==null?"":`IHSG ${m.above_sma50?"di atas":"di bawah"} SMA50 dan ${m.above_sma200?"di atas":"di bawah"} SMA200.`;
  $("hero").innerHTML=`
   <div class="idx"><span class="lbl">IHSG, penutupan ${tgl(D.as_of)}</span><b class="big">${n(m.bench)}</b><span class="chg ${m.bench_chg>=0?"pos":"neg"}">${pct(m.bench_chg,2)}</span>
     <div class="ma"><span>SMA50 <b>${n(last[2])}</b></span><span>SMA200 <b>${n(last[3])}</b></span><span>${m.universe} saham dipantau (≥ ${tri(D.params.min_market_cap)})</span></div></div>
   <div class="hchart">${heroChart(S)}<div class="legend"><span><i style="background:var(--brass)"></i>IHSG</span><span><i style="background:var(--hold)"></i>SMA50</span><span><i style="background:var(--dim)"></i>SMA200</span><span>6 bulan terakhir</span></div></div>
   <div class="verdict"><p class="regime ${reg}">${esc(m.regime)}</p><p>${why}</p>${heroAlarm()}
     <ul class="plan">${["short","medium","long"].map(h=>{const [t,c]=verdictFor(h);return `<li><span class="h">${H[h]}</span><span class="act ${c}">${esc(t)}</span></li>`;}).join("")}</ul></div>`;
}
const LV={"NORMAL":"ok","LEBIH BAIK":"ok","WASPADA":"warn","BAHAYA":"bad"};
function heroAlarm(){
  const M=(D.monitor||{}).horizons||{},bad=Object.values(M).filter(v=>v.level==="WASPADA"||v.level==="BAHAYA");
  const P=(D.proposal||{}).horizons||{},pend=Object.values(P).filter(v=>v.status==="usulan"&&!v.applied_at);
  let h="";
  if(bad.length)h+=`<div class="alarm ${bad.some(v=>v.level==="BAHAYA")?"bad":""}"><b>Alarm kinerja</b><span>${bad.map(v=>esc(v.label+" "+v.level.toLowerCase())).join(", ")}. Lihat tab Track record.</span></div>`;
  if(pend.length)h+=`<div class="alarm"><b>Usulan baru</b><span>${pend.length} usulan parameter menunggu keputusan Anda (tab Track record).</span></div>`;
  return h;
}
const pv=v=>Array.isArray(v)?"["+v.join(", ")+"]":String(v);
function renderMonitor(){
  const M=D.monitor,P=D.proposal;let h="";
  if(M&&M.horizons&&Object.keys(M.horizons).length){
    h+=`<h3>Kinerja sungguhan vs perkiraan backtest</h3><p class="muted">Alarm membandingkan hasil rekomendasi yang sudah selesai dengan sebaran hasil backtest. Alarm dini (rentetan rugi, win rate terlalu rendah) sudah aktif mulai ${M.early_trades||5} transaksi. WASPADA = peluang hasil seburuk ini terjadi karena kebetulan di bawah ~5%; BAHAYA = di bawah ~1%. Alarm hanya memberi tahu, tidak mengubah apa pun.</p><div class="mon">`;
    for(const [k,v] of Object.entries(M.horizons)){
      const lv=LV[v.level]||"na",e=v.expected;
      const sub=v.level==="BELUM CUKUP DATA"?`${v.n} dari ${M.min_trades} transaksi`:"";
      h+=`<div class="card"><h4>${esc(v.label)}</h4><div class="lv ${lv}">${esc(v.level)}</div><p>${esc(v.text||sub)}</p>${e&&e.avg_ret!=null&&v.level==="BELUM CUKUP DATA"&&!v.all?`<p>Perkiraan backtest (${esc(e.basis)}): rata-rata ${pct(e.avg_ret)}, win rate ${pctp(e.win_rate,0)}.</p>`:""}</div>`;
    }
    h+=`</div>`;
  }
  if(P&&P.horizons){
    h+=`<h3>Usulan parameter bulanan</h3><p class="muted">Dibuat ${esc(P.generated_at||"")}. Setiap bulan satu perubahan diuji: dipilih tanpa melihat periode sejak ${tgl(P.holdout_from)}, lalu harus tetap lebih baik di periode itu dan di simulasi portofolio. Tidak diterapkan otomatis.</p>`;
    for(const [k,v] of Object.entries(P.horizons)){
      const ev=v.evidence||{},ch=v.change;
      if(v.status==="usulan"&&ch){
        h+=`<div class="prop"><h4 style="margin:0 0 6px">${H[k]}: ubah <code>${esc(ch.param)}</code> ${esc(pv(ch.old))} → <b>${esc(pv(ch.new))}</b>${v.applied_at?` <span class="pos">· sudah diterapkan ${esc(v.applied_at)}</span>`:""}</h4><p class="muted" style="margin:0 0 8px">${esc(v.reason||"")}</p>
        <div class="tbl"><table><tr><th></th><th>Sekarang</th><th>Usulan</th></tr>
        <tr><td>Rata-rata per transaksi (periode pemilihan)</td><td>${pct(ev.select_cur,2)}</td><td>${pct(ev.select_new,2)}</td></tr>
        <tr><td>Rata-rata per transaksi (6 bulan terakhir)</td><td>${pct(ev.holdout_cur,2)} <span class="name">${ev.holdout_n_cur??""} trx</span></td><td>${pct(ev.holdout_new,2)} <span class="name">${ev.holdout_n_new??""} trx</span></td></tr>
        <tr><td>Simulasi portofolio: return</td><td>${pct(ev.port_ret_cur)}</td><td>${pct(ev.port_ret_new)}</td></tr>
        <tr><td>Simulasi portofolio: max drawdown</td><td>${pct(ev.port_dd_cur)}</td><td>${pct(ev.port_dd_new)}</td></tr></table></div>
        ${v.applied_at?"":`<p class="muted">Untuk menerapkan: di aplikasi laptop klik <b>Usulan → Terapkan</b>; untuk GitHub ubah baris <code>${esc(ch.param)}: ${esc(pv(ch.new))}</code> di blok <code>${k}:</code> config.yaml.</p>`}</div>`;
      } else h+=`<div class="prop"><h4 style="margin:0 0 6px">${H[k]}: <span class="pos">tetap</span></h4><p class="muted" style="margin:0">${esc(v.reason||"")}</p></div>`;
    }
  }
  return h;
}
function header(){
  $("stamp").innerHTML=`Data <b>${tgl(D.as_of)}</b>, diperbarui <b>${esc(D.generated_at.slice(11))} WIB</b>`;
  if(D.demo)$("demo").innerHTML='<div class="demo">Mode demo: data sintetis untuk uji coba, bukan data pasar.</div>';
  const DS=D.data_status||{};
  if(DS.stale)$("demo").innerHTML+=`<div class="demo">Data basi: ${esc(DS.text||"")}</div>`;
  const nb=["short","medium","long"].reduce((a,h)=>a+D.horizons[h].buys.length,0);
  const ns=["short","medium","long"].reduce((a,h)=>a+D.horizons[h].sells.length,0);
  $("n-buy").textContent=nb;$("n-sell").textContent=ns;$("n-all").textContent=D.all.length;
  hero();
}
function seg(id,cb,count){
  const el=$(id);el.innerHTML=["short","medium","long"].map((h,i)=>`<button data-h="${h}" class="${i?"":"on"}">${H[h]}<span class="n">${count(h)}</span></button>`).join("");
  el.onclick=e=>{const b=e.target.closest("button");if(!b)return;[...el.children].forEach(x=>x.classList.toggle("on",x===b));cb(b.dataset.h);};
  const first=["short","medium","long"].find(h=>count(h)>0)||"short";
  [...el.children].forEach(x=>x.classList.toggle("on",x.dataset.h===first));cb(first);
}
function rulesText(r){
  if(!r)return "";
  const out=[`skor ≥ ${r.min_score??30}`];
  if(r.market_filter&&r.market_filter!=="none")out.push(`IHSG di atas ${r.market_filter.toUpperCase()}`);
  if(r.trend_filter&&r.trend_filter!=="none")out.push(`harga di atas ${r.trend_filter.toUpperCase()}`);
  if(r.entry_mode)out.push(r.entry_mode==="limit"?`antre di area bawah ${r.limit_days} hari`:"beli di pembukaan T+1");
  if(r.market_exit&&r.market_exit!=="none")out.push(`keluar bila IHSG di bawah ${String(r.market_exit_ma).toUpperCase()}`);
  return "Aturan: "+out.join(", ")+".";
}
function renderBuy(h){
  const b=D.horizons[h];
  let html=`<p class="intro">${esc(b.label)}. Alokasi ${pctp(b.allocation,0)} modal, ${b.buys.length} posisi, kas ${pctp(b.cash_weight,0)} dari porsi ini. ${rulesText(b.rules)}${b.version?` <span class="muted">Strategi ${esc(b.version)}.</span>`:""}</p>`;
  if(b.market_exit_active)html+=`<div class="alert"><b>Aturan keluar aktif.</b> ${esc(b.market_exit_active)}</div>`;
  if(b.regime_text)html+=`<div class="note-cut">Porsi dikurangi menjadi <b>${pctp(b.regime_scale,0)}</b> karena ${esc(b.regime_text)}. Sisanya ditahan sebagai kas.</div>`;
  html+=b.buys.length?`<div class="list">${b.buys.map(buyRow).join("")}</div>`
    :`<div class="empty"><b>Tidak ada rekomendasi beli untuk horizon ini.</b> Modal porsi ini tetap di kas.${b.n_held?` Ada ${b.n_held} sinyal beli yang tertahan filter; daftarnya di bawah.`:""}</div>`;
  if(b.watchlist.length){html+=`<h3>Menunggu syarat terpenuhi</h3><div class="tbl"><table><tr><th>Kode</th><th>Sinyal</th><th>Harga</th><th>Area beli</th><th>TP1</th><th>Cut loss</th><th>Kenapa belum</th></tr>${b.watchlist.map(w=>`<tr><td><b>${w.code}</b><div class="name">${esc(w.name)}</div></td><td>${badge(w.signal,w.score)}</td><td>${n(w.price)}</td><td>${n(w.entry_low)}–${n(w.entry_high)}</td><td>${n(w.tp1)}</td><td>${n(w.sl)}</td><td style="text-align:left" class="muted">${esc(w.held||"")}</td></tr>`).join("")}</table></div>`;}
  $("buy-body").innerHTML=html;
}
function renderSell(h){
  const s=D.horizons[h].sells;
  $("sell-body").innerHTML=`<p class="intro">Untuk Anda yang sedang memegang saham ini: keluar atau kurangi posisi, dan jangan membeli baru. Aplikasi tidak menyarankan short selling.</p>`+
   (s.length?`<div class="list">${s.map(sellRow).join("")}</div>`:`<div class="empty"><b>Tidak ada sinyal jual untuk horizon ini.</b></div>`);
}
let sortK="mcap",sortD=-1;
function renderAll(){
  const q=$("q").value.toLowerCase();
  const rows=D.all.filter(r=>!q||(r.code+" "+r.name+" "+r.sector).toLowerCase().includes(q));
  const key=r=>["short","medium","long"].includes(sortK)?(r[sortK].score??-999):(r[sortK]??-1e18);
  rows.sort((a,b)=>sortK==="code"?sortD*a.code.localeCompare(b.code):sortD*(key(a)-key(b)));
  const th=[["code","Kode"],["price","Harga"],["chg_1d","Hari ini"],["mcap","Kapitalisasi"],["short","Pendek"],["medium","Menengah"],["long","Panjang"],["pe","PER"],["pb","PBV"],["roe","ROE"],["div_yield","Dividen"]];
  const hasF=D.all.some(r=>r.foreign_20d!=null); if(hasF)th.push(["foreign_20d","Asing 20 hari"]);
  $("all-t").innerHTML=`<tr>${th.map(([k,l])=>`<th data-k="${k}" aria-sort="${k===sortK?(sortD>0?"ascending":"descending"):"none"}">${l}${k===sortK?(sortD>0?" ▲":" ▼"):""}</th>`).join("")}</tr>`+rows.map(r=>`<tr><td><b>${r.code}</b>${r.news&&r.news.length?` <span class="neg" title="${esc(r.news[0].categories[0]+": "+r.news[0].title)}">⚠</span>`:""}<div class="name">${esc(r.name)}</div></td><td>${n(r.price)}</td><td class="${r.chg_1d>=0?"pos":"neg"}">${pct(r.chg_1d)}</td><td>${tri(r.mcap)}</td>
  <td>${badge(r.short.signal,r.short.score)}</td><td>${badge(r.medium.signal,r.medium.score)}</td><td>${badge(r.long.signal,r.long.score)}</td>
  <td>${dec(r.pe)}</td><td>${dec(r.pb,2)}</td><td>${pctp(r.roe)}</td><td>${pctp(r.div_yield)}</td>${hasF?`<td class="${(r.foreign_20d||0)>=0?"pos":"neg"}">${rpM(r.foreign_20d)}</td>`:""}</tr>`).join("");
  $("all-t").querySelectorAll("th").forEach(t=>t.onclick=()=>{const k=t.dataset.k;sortD=k===sortK?-sortD:-1;sortK=k;renderAll();});
}
function statRow(lbl,s){if(!s||!s.n)return `<tr><td>${lbl}</td><td colspan="5" class="muted" style="text-align:left">belum ada transaksi selesai</td></tr>`;
  return `<tr><td>${lbl}</td><td>${s.n}</td><td>${pctp(s.win_rate,0)}</td><td class="${s.avg_ret>=0?"pos":"neg"}">${pct(s.avg_ret)}</td><td>${dec(s.profit_factor,2)}</td><td>${s.avg_days==null?pct(s.median_ret):dec(s.avg_days)}</td></tr>`;}
function posRow(x){
  const lvl={sl:x.sl,entry_low:x.buy_price,entry_high:x.buy_price,tp1:x.tp1,tp2:x.tp2,price:x.price};
  return `<article class="sig"><div class="id"><span class="tk">${esc(x.code)}</span><span class="nm">${HL[x.horizon]||""}, beli ${tgl(x.buy_date)}</span><span class="nm">hari ke-${x.days??"-"} dari ${x.max_days??"-"}</span></div>
   <div class="sp">${spark(x.spark,trendCol(x.spark))}<div class="px">${n(x.price)}<em class="${(x.pnl_pct||0)>=0?"pos":"neg"}">${pct(x.pnl_pct)}</em></div></div>
   ${x.tp1&&x.sl?ladder(lvl).replace(/area beli|antre beli/g,"harga beli"):"<div></div>"}
   <div class="alloc">${x.lots!=null?`<b>${n(x.lots)} lot</b><span>${x.pnl_value!=null?(x.pnl_value>=0?"+":"−")+"Rp "+n(Math.abs(x.pnl_value)):""}</span>`:`<b class="${(x.pnl_pct||0)>=0?"pos":"neg"}">${pct(x.pnl_pct)}</b><span>untung/rugi</span>`}</div>
   <div class="tag"><span class="pill ${PCLS[x.status]||"p-x"}">${esc(x.status)}</span>${x.signal?`<div style="margin-top:6px">${badge(x.signal,x.score)}</div>`:""}${newsChip(x)}</div>
   <details ${x.rank<3||(x.news&&x.news.length)?"open":""}><summary>Tindakan</summary><div class="more"><div><p>${esc(x.action)}</p></div>${newsBlock(x)}</div></details></article>`;
}
function renderNews(){
  const N=D.news||{},I=N.items||{},codes=Object.keys(I);
  const byCode=Object.fromEntries(D.all.map(r=>[r.code,r]));
  $("n-news").textContent=codes.length||"";
  let h=`<p class="intro">Berita ${NEWS_DAYS()} hari terakhir yang judulnya menyebut saham dalam pantauan dan mengandung kata risiko: right issue / private placement (dilusi), PKPU, gagal bayar, suspensi, kasus hukum, gugatan, sanksi, kinerja memburuk, peringkat turun, pengendali menjual saham. Hanya peringatan: skor dan sinyal tidak diubah. Sumber: Google News & RSS portal berita.</p>`;
  if(!N.stats&&!codes.length){$("p-news").innerHTML=h+'<div class="empty"><b>Data berita belum tersedia.</b></div>';return;}
  if(!codes.length){$("p-news").innerHTML=h+'<div class="empty"><b>Tidak ada berita negatif untuk saham dalam pantauan.</b></div>';return;}
  codes.sort((a,b)=>{const s=c=>I[c].some(w=>w.severity==="tinggi")?0:1;return s(a)-s(b)||(I[b][0].date||"").localeCompare(I[a][0].date||"");});
  h+=codes.map(c=>{const r=byCode[c]||{};const sig=r.short?["short","medium","long"].map(k=>`${H[k]} ${badge(r[k].signal,r[k].score)}`).join(" "):"";
    return `<div class="ncard"><h4>${esc(c)}<span>${esc(r.name||"")}</span></h4>${sig?`<div style="margin-bottom:8px;font-size:13px">${sig}</div>`:""}${newsList(I[c])}</div>`;}).join("");
  const st=N.stats;if(st)h+=`<p class="muted" style="font-size:13px">Diperiksa ${st.recent_items} judul berita ${NEWS_DAYS()} hari terakhir dari ${st.google?st.google.ok:0} pencarian Google News dan ${Object.values(st.feeds||{}).filter(f=>f.status==="OK").length} RSS portal.</p>`;
  $("p-news").innerHTML=h;
}
function renderPositions(){
  const P=D.positions, E=D.positions_errors||[];
  if(P==null){$("tab-pos").style.display="none";return;}
  $("n-pos").textContent=P.length||"";
  let h=`<p class="intro">Saham yang Anda catat sudah dibeli. Status dihitung dari harga sejak tanggal beli: cut loss, TP1/TP2, batas waktu hold, aturan keluar pasar, dan sinyal terbaru.</p>`;
  if(E.length)h+=E.map(x=>`<div class="alert">${esc(x)}</div>`).join("");
  if(!P.length){$("p-pos").innerHTML=h+'<div class="empty"><b>Belum ada posisi.</b> Tambahkan lewat tombol “Posisi saya” di aplikasi laptop, atau isi file positions.csv: kode, horizon, tanggal beli, harga beli, lot.</div>';return;}
  h+=`<div class="list">${P.map(posRow).join("")}</div>`;
  $("p-pos").innerHTML=h;
}
function renderTrack(){
  const t=D.track||{by_horizon:{},open:[],recent_closed:[]};
  let h=`<p class="intro">Setiap rekomendasi beli dicatat lalu dinilai otomatis dengan harga sesudahnya: masuk T+1, keluar di TP, cut loss, atau batas waktu, biaya transaksi termasuk. ${t.cancelled||0} rekomendasi batal karena harga tidak sampai ke area beli.</p>${renderMonitor()}<h3>Hasil per horizon</h3>
  <div class="tbl"><table><tr><th>Horizon</th><th>Transaksi</th><th>Menang</th><th>Rata-rata</th><th>Profit factor</th><th>Median</th></tr>
  ${["short","medium","long"].map(k=>statRow(H[k],t.by_horizon[k])).join("")}${statRow("Total",t.all)}</table></div>`;
  const BV=t.by_version||{};
  if(Object.values(BV).some(v=>v&&v.length)){
    h+=`<h3>Hasil per versi strategi</h3><p class="muted">Setiap perubahan parameter atau rumus membuat versi baru, supaya hasil strategi lama tidak tercampur dengan yang sekarang. v0 = rekomendasi sebelum pelabelan versi.</p>
    <div class="tbl"><table><tr><th>Horizon · versi</th><th>Transaksi</th><th>Menang</th><th>Rata-rata</th><th>Profit factor</th><th>Median</th></tr>
    ${["short","medium","long"].flatMap(k=>(BV[k]||[]).map(v=>statRow(`${H[k]} · ${esc(v.version)}${v.current?' <span class="pos">(aktif)</span>':""}<div class="name">${v.n_recs} rekomendasi, ${v.n_open} berjalan</div>`,v))).join("")}</table></div>`;
  }
  const tb=(rows,cl)=>rows.length?`<div class="tbl"><table><tr><th>Tanggal sinyal</th><th>Kode</th><th>Horizon</th><th>Masuk</th><th>TP1</th><th>Cut loss</th><th>Status</th><th>Hasil</th><th>Hari</th></tr>${rows.map(r=>`<tr><td>${tgl(r.date)}</td><td><b>${r.code}</b></td><td>${H[r.horizon]}<div class="name">${esc((r.version||"").split(" ·")[0])}</div></td><td>${n(r.entry_px??r.entry)}</td><td>${n(r.tp1)}</td><td>${n(r.sl)}</td><td>${esc(r.outcome)}</td><td class="${(r.ret||0)>=0?"pos":"neg"}">${r.ret==null?"-":pct(r.ret)}</td><td>${r.days??"-"}</td></tr>`).join("")}</table></div>`:`<div class="empty">${cl}</div>`;
  h+=`<h3>Masih berjalan</h3>`+tb(t.open,"Tidak ada rekomendasi yang sedang berjalan.")+`<h3>Selesai terakhir</h3>`+tb(t.recent_closed,"Belum ada rekomendasi yang selesai. Bagian ini terisi seiring waktu.");
  $("p-track").innerHTML=h;
}
function svgChart(series,o={}){
  const W=640,Hh=o.h||220,L=46,R=10,T=10,B=22,dates=series[0].data.map(d=>d[0]),N=dates.length;
  let lo=Infinity,hi=-Infinity;series.forEach(s=>s.data.forEach(d=>{lo=Math.min(lo,d[1]);hi=Math.max(hi,d[1]);}));
  if(o.zeroTop){hi=Math.max(hi,0);} const pad=(hi-lo)*0.06||1;lo-=pad;hi+=o.zeroTop?0:pad;
  const x=i=>L+(W-L-R)*i/Math.max(1,N-1),y=v=>T+(Hh-T-B)*(hi-v)/(hi-lo);
  let g="";for(let k=0;k<=4;k++){const v=lo+(hi-lo)*k/4;g+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/><text x="${L-6}" y="${y(v)+4}" text-anchor="end">${o.fmt?o.fmt(v,hi-lo):v.toFixed(0)}</text>`;}
  if(o.base!=null&&o.base>lo&&o.base<hi)g+=`<line x1="${L}" x2="${W-R}" y1="${y(o.base)}" y2="${y(o.base)}" stroke="var(--mute)" stroke-dasharray="3 3" opacity=".6"/>`;
  let yr="";dates.forEach((d,i)=>{const y0=d.slice(0,4);if(i===0||dates[i-1].slice(0,4)!==y0)yr+=`<text x="${x(i)}" y="${Hh-6}" text-anchor="${i===0?"start":"middle"}">${i===0?d.slice(0,7):y0}</text>`;});
  const paths=series.map(s=>{const pts=s.data.map((d,i)=>`${x(i).toFixed(1)},${y(d[1]).toFixed(1)}`);
    if(s.area)return `<path d="M${x(0)},${y(0)} L${pts.join(" L")} L${x(N-1)},${y(0)} Z" fill="${s.color}" opacity=".25" stroke="${s.color}" stroke-width="1.2"/>`;
    return `<polyline points="${pts.join(" ")}" fill="none" stroke="${s.color}" stroke-width="${s.w||2}" ${s.dash?'stroke-dasharray="5 4"':""}/>`;}).join("");
  return `<svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="${esc(o.label||"grafik")}">${g}${paths}${yr}</svg>`;
}
function legend(series){return `<div class="legend">${series.map(s=>`<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}</div>`;}
function renderPortfolio(P){
  if(!P||!P.combined||!P.combined.equity)return "";
  const S=[{name:"Akun total (pendek+menengah, bucket panjang = kas)",data:P.combined.equity,color:"var(--brass)",w:2.5}];
  if(P.buckets.short)S.push({name:"Bucket pendek",data:P.buckets.short.equity,color:"var(--buy)",w:1.5});
  if(P.buckets.medium)S.push({name:"Bucket menengah",data:P.buckets.medium.equity,color:"#7FB2E5",w:1.5});
  if(P.ihsg)S.push({name:"IHSG (beli & tahan)",data:P.ihsg.equity,color:"var(--mute)",dash:1,w:1.5});
  const rows=[["Akun total",P.combined],["Bucket pendek",P.buckets.short],["Bucket menengah",P.buckets.medium],["IHSG beli & tahan",P.ihsg]].filter(r=>r[1]);
  const td=v=>`<td class="${v==null?"":v>=0?"pos":"neg"}">${pct(v)}</td>`;
  let h=`<h2>Simulasi portofolio</h2><p class="muted">Sinyal pendek & menengah dijalankan sebagai akun sungguhan mulai ${esc(P.start)} dengan modal acuan Rp ${n(P.capital)}: kuota posisi, ukuran per posisi, batas risiko, pembulatan lot, TP1 jual separuh, biaya transaksi. Bucket jangka panjang tidak bisa disimulasikan (butuh fundamental historis) sehingga dihitung sebagai kas. Indeks awal = 100.</p>
  <div class="chart">${legend(S)}${svgChart(S,{base:100,label:"Kurva modal vs IHSG"})}</div>
  <div class="chart"><div class="legend"><span><i style="background:var(--sell)"></i>Drawdown akun total (% dari puncak)</span></div>${svgChart([{name:"dd",data:P.combined.drawdown,color:"var(--sell)",area:1}],{h:130,zeroTop:1,fmt:(v,r)=>v.toFixed(r<12?1:0).replace(".",",")+"%",label:"Drawdown"})}</div>
  <div class="tbl"><table><tr><th></th><th>Total return</th><th>Per tahun (CAGR)</th><th>Max drawdown</th><th>Bulan terburuk</th><th>Sharpe</th><th>Rata-rata terinvestasi</th><th>Transaksi</th></tr>
  ${rows.map(([l,s])=>`<tr><td>${l}</td>${td(s.total_return)}${td(s.cagr)}<td class="neg">${pct(s.max_drawdown)}<div class="name">${s.dd_peak||""} → ${s.dd_trough||""}${s.dd_recovered?"":" (belum pulih)"}</div></td>${td(s.worst_month)}<td>${dec(s.sharpe,2)}</td><td>${s.avg_exposure==null?"-":pctp(s.avg_exposure,0)}</td><td>${s.trades??"-"}</td></tr>`).join("")}</table></div>`;
  const yrs=[...new Set(rows.flatMap(([,s])=>Object.keys(s.by_year||{})))].sort();
  h+=`<h3>Return per tahun</h3><div class="tbl"><table><tr><th></th>${yrs.map(y=>`<th>${y}</th>`).join("")}</tr>${rows.map(([l,s])=>`<tr><td>${l}</td>${yrs.map(y=>td((s.by_year||{})[y])).join("")}</tr>`).join("")}</table></div>`;
  if(P.split&&P.split.out_sample&&P.split.out_sample.total_return!=null)h+=`<p class="muted">Periode out-of-sample (sejak ${esc(D.params.split_date||"")}): akun total ${pct(P.split.out_sample.total_return)}, max drawdown ${pct(P.split.out_sample.max_drawdown)}; IHSG ${pct((P.split.ihsg_out_sample||{}).total_return)}.</p>`;
  const sk=Object.entries(P.buckets).map(([k,b])=>`${H[k]}: ${b.skipped_full} sinyal dilewati karena kuota posisi penuh`).join(" · ");
  h+=`<p class="muted">${sk}. Hasil simulasi bukan jaminan hasil ke depan.</p>`;
  return h;
}
function assumeText(a){
  if(!a)return "Universe memakai market cap saat ini (bias survivorship) dan eksekusi ideal — anggap sebagai batas atas, bukan janji hasil.";
  const p=[];
  p.push(a.point_in_time?`Universe per tanggal: saham hanya dibeli pada hari market cap & likuiditasnya lolos batas${a.n_not_current?` (${a.n_not_current} dari ${a.n_stocks} saham yang diuji kini sudah tidak lolos)`:""}`:"Universe memakai daftar saham yang lolos hari ini (bias survivorship)");
  if(a.slippage_ticks||a.limit_through||a.arb){
    if(a.slippage_ticks)p.push(`cut loss terisi ${a.slippage_ticks} fraksi harga lebih buruk`);
    p.push(a.auction_slippage_ticks?`beli di open/jual di close ${a.auction_slippage_ticks} fraksi lebih buruk`:"beli di open/jual di close di harga lelang");
    if(a.limit_through)p.push("antre beli dan TP baru terisi bila harga menembus 1 fraksi");
    if(a.arb)p.push("saham terkunci ARB tidak bisa dijual hari itu");
  } else p.push("eksekusi ideal tanpa slippage");
  return p.join("; ")+". Saham yang sudah delisting tidak tersedia di data gratis, jadi hasil masih sedikit optimistis.";
}
function renderRealism(R){
  if(!R||!R.steps||!R.steps.length)return "";
  const td=v=>`<td class="${v==null?"":v>=0?"pos":"neg"}">${pct(v)}</td>`;
  let h=`<h3>Seberapa optimistis backtest lama?</h3><p class="muted">Realisme ditambahkan selangkah demi selangkah (uji ${esc(R.generated_at)}${R.demo?", data demo":""}; ${R.universe_backtest} saham diuji, ${R.universe_today} lolos hari ini).</p>
  <div class="tbl"><table><tr><th>Asumsi</th><th>Pendek: rata per trx</th><th>Menengah: rata per trx</th><th>Akun total: return</th><th>Max drawdown</th><th>Out-of-sample</th></tr>`;
  for(const r of R.steps){const c=r.portfolio.combined||{},o=r.portfolio.combined_oos||{};
    h+=`<tr><td>${esc(r.name)}</td>${td((r.trades.short||{}).avg_ret)}${td((r.trades.medium||{}).avg_ret)}${td(c.total_return)}<td class="neg">${pct(c.max_drawdown)}</td>${td(o.total_return)}</tr>`;}
  return h+`</table></div>`;
}
function renderBt(){
  const b=D.backtest;
  if(!b||!b.results){$("p-bt").innerHTML='<div class="empty">Backtest belum dijalankan.</div>';return;}
  let h=renderPortfolio(b.portfolio)+`<h2>Backtest per transaksi</h2><p class="muted">Dijalankan ${esc(b.generated_at)}. Masuk saat skor menembus ambang BUY, keluar via TP/SL/time-stop, biaya termasuk.</p><p class="note">Asumsi: ${esc(assumeText(b.assumptions))}</p>
  <div class="tbl"><table><tr><th>Horizon</th><th>Transaksi</th><th>Win rate</th><th>Rata-rata</th><th>Profit factor</th><th>Rata hari</th></tr>`;
  for(const [k,s] of Object.entries(b.results)){h+=statRow(H[k]+" (semua)",s);if(s.in_sample)h+=statRow(H[k]+" · in-sample",s.in_sample);if(s.out_sample)h+=statRow(H[k]+" · out-of-sample",s.out_sample);if(s.strong_only)h+=statRow(H[k]+" (STRONG BUY saja)",s.strong_only);}
  h+=`</table></div>`;
  for(const [k,s] of Object.entries(b.results)) if(s.by_year) h+=`<p class="muted">${H[k]} per tahun: ${Object.entries(s.by_year).map(([y,v])=>y+": "+(v.n?v.n+" trx, rata "+pct(v.avg_ret)+", PF "+dec(v.profit_factor,2):"-")).join(" · ")}</p>`;
  for(const [k,s] of Object.entries(b.results)) if(s.outcomes) h+=`<p class="muted">${H[k]}: periode ${s.period?s.period.join(" s/d "):"-"} · hasil keluar: ${Object.entries(s.outcomes).map(([a,c])=>a+" "+c).join(", ")}${s.arb_blocked?` · ${s.arb_blocked} transaksi tertahan ARB`:""}${s.not_current?` · ${s.not_current} transaksi pada saham yang kini sudah tidak lolos universe`:""}</p>`;
  h+=renderRealism(b.realism);
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
  <p><b>Peringatan berita.</b> Setiap hari judul berita 7 hari terakhir (Google News per saham + RSS portal berita) dicocokkan ke kode atau nama saham, lalu diperiksa kata risikonya: right issue / private placement, PKPU / pailit, gagal bayar, suspensi / delisting, UMA, kasus hukum, gugatan, sanksi, kinerja memburuk, peringkat turun, pengendali menjual saham, gangguan operasi. Hanya peringatan; skor dan sinyal tidak diubah. Berita yang cocok diarsip agar kelak bisa diuji.</p>
  <h3>Sumber data</h3><ul>${D.sources.map(s=>`<li>${esc(s)}</li>`).join("")}</ul>
  <h3>Disclaimer</h3><p>Aplikasi ini alat bantu analisis kuantitatif, bukan nasihat investasi dan bukan ajakan membeli/menjual efek. Data gratis dapat terlambat atau keliru — cek ulang harga di aplikasi sekuritas sebelum bertransaksi. Kinerja masa lalu tidak menjamin hasil di masa depan.</p>`;
}
$("tabs").onclick=e=>{const b=e.target.closest("button");if(!b)return;document.querySelectorAll("#tabs button").forEach(x=>x.classList.toggle("on",x===b));document.querySelectorAll(".panel").forEach(p=>p.classList.toggle("on",p.id==="p-"+b.dataset.p));};
header();
seg("seg-buy",renderBuy,h=>D.horizons[h].buys.length);
seg("seg-sell",renderSell,h=>D.horizons[h].sells.length);
$("q").oninput=renderAll;renderAll();renderPositions();renderNews();renderTrack();renderBt();renderMethod();
$("foot").textContent="PANDU (Portofolio · Analisis · Notifikasi · Disiplin risiko · Uji balik) adalah alat bantu analisis, bukan nasihat investasi. Cek ulang harga di aplikasi sekuritas sebelum bertransaksi.";
</script>
</body>
</html>
"""


def write_html(data: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    path.write_text(TEMPLATE.replace("/*__DATA__*/null", payload), encoding="utf-8")
