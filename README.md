# PANDU — sinyal saham IHSG

**PANDU** = **P**ortofolio · **A**nalisis · **N**otifikasi · **D**isiplin risiko · **U**ji balik.

Aplikasi rekomendasi **beli / jual** saham Bursa Efek Indonesia untuk saham berkapitalisasi pasar **≥ Rp 5 triliun**, dengan tiga horizon (pendek, menengah, panjang). Setiap hari bursa aplikasi mengunduh data terbaru, menghitung skor, lalu menerbitkan dashboard berisi:

- **Sinyal** STRONG BUY / BUY / HOLD / SELL / STRONG SELL + skor −100…+100
- **Kapan beli**: area beli (entry) dan batas kejar
- **Kapan jual**: TP1, TP2, cut loss, aturan trailing & time-stop
- **Berapa lama hold**: 3–10 hari bursa · 1–3 bulan · 6–24 bulan
- **Bobot (weight)** per saham terhadap total modal + jumlah lot
- **Track record** otomatis atas setiap rekomendasi, dan **backtest** aturan sinyal

> ⚠️ Alat bantu analisis, **bukan nasihat investasi**. Selalu cek ulang harga di aplikasi sekuritas Anda.

---

## Sumber data (gratis & terbuka, diperbarui harian)

| Data | Sumber | Keterangan |
|---|---|---|
| Harga OHLCV harian, jumlah saham, fundamental (PER, PBV, ROE, DER, dividen, pertumbuhan laba, sektor) | Yahoo Finance melalui **[yfinance](https://github.com/ranaroussi/yfinance)** | Library open source (Apache-2.0). Kode BEI memakai sufiks `.JK`, IHSG = `^JKSE` |
| Daftar seluruh emiten + jumlah saham tercatat + papan pencatatan | Endpoint publik **idx.co.id** | Bila diblokir (Cloudflare), otomatis memakai `data/tickers_seed.csv` |

Catatan jujur: kode pengambilnya open source, datanya publik dan gratis, tetapi Yahoo/IDX bukan penyedia "open data" resmi berlisensi — data bisa terlambat, kosong, atau berubah format. Karena itu aplikasi punya cache, retry, dan cadangan.

## Filter universe

1. Market cap = jumlah saham × harga penutupan terakhir **≥ Rp 5.000.000.000.000** (`universe.min_market_cap`)
2. Rata-rata nilai transaksi 20 hari ≥ Rp 5 miliar (hindari saham big-cap tapi tidak likuid)
3. Masih diperdagangkan (tidak suspensi > 5 hari), bukan papan pemantauan khusus

## Cara menjalankan

```bash
pip install -r requirements.txt
python main.py --demo            # uji coba offline (data sintetis)
python main.py                   # data asli, butuh internet
python main.py --backtest always # paksa backtest ulang
```

Hasil:
- `docs/index.html` — dashboard (buka langsung di browser)
- `docs/data/latest.json` — semua sinyal (untuk integrasi lain)
- `docs/data/history/signals_YYYY-MM-DD.json` — arsip harian
- `docs/data/recommendations.csv` — catatan & hasil setiap rekomendasi
- `output/signals_latest.csv` — tabel sinyal untuk Excel

## Update otomatis setiap hari (gratis)

**Opsi A — GitHub Actions + GitHub Pages (disarankan)**
1. Buat repository baru di GitHub, upload seluruh folder ini.
2. *Settings → Pages* → Source: `Deploy from a branch`, branch `main`, folder `/docs`.
3. *Actions* → aktifkan workflow **Update sinyal IHSG harian**. Workflow berjalan otomatis Senin–Jumat pukul 17:30 WIB (setelah bursa tutup), atau klik *Run workflow* untuk manual.
4. Dashboard tersedia di `https://<username>.github.io/<repo>/`.

**Opsi B — komputer sendiri**
- Linux/Mac: `crontab -e` lalu tambahkan `30 17 * * 1-5 cd /path/ihsg-signal && python main.py`
- Windows: Task Scheduler → jalankan `python main.py` setiap hari kerja 17:30.

**Notifikasi Telegram (opsional):** buat bot lewat @BotFather, lalu isi secret `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID` di repo (atau environment variable lokal).

## Aplikasi laptop (Windows)

Versi aplikasi berjalan mandiri di laptop: tombol **Update sekarang**, **Buka dashboard**, **Posisi saya**
(formulir), **Pengaturan** (modal, Telegram), dan jadwal otomatis Senin–Jumat 17:30 lewat Windows Task Scheduler.
Dari internet rumah, aplikasi juga mengambil data **idx.co.id** (daftar emiten & jumlah saham resmi,
papan pemantauan khusus, transaksi asing harian) yang diblokir untuk server GitHub.

Membuat `.exe`: jalankan workflow **Build aplikasi Windows** di tab Actions → unduh artifact
`PANDU-Windows` → ekstrak → jalankan `PANDU.exe` (lihat `CARA PAKAI.txt`).
Menjalankan dari kode: `python app.py` (jendela) atau `python app.py --auto` (tanpa jendela).

## Pemantau posisi pribadi

Catat saham yang benar-benar Anda beli di **`positions.csv`** (root repo, bisa diedit langsung di GitHub):

```
code,horizon,buy_date,buy_price,lots,tp1_done,sl,tp1,tp2,note
BBCA,pendek,2026-10-29,4900,10,,,,,
```

- `horizon`: pendek / menengah / panjang · `tp1_done`: isi `ya` setelah menjual separuh
- `sl`, `tp1`, `tp2` opsional — kosongkan untuk memakai level hitungan aplikasi
- Hapus barisnya setelah posisi dijual habis

Setiap hari tab **Posisi Saya** dan Telegram memberi status: JUAL SEMUA (cut loss / TP2 / batas waktu / pasar berbalik),
JUAL 50% (TP1), WASPADA (sinyal berbalik SELL), atau TAHAN. Dashboard (publik) tidak menampilkan lot & nominal Rp
(`positions.dashboard: percent` di config.yaml); Telegram selalu lengkap.

## Aturan keluar saat pasar berbalik

Opsi per horizon di `config.yaml`: `market_exit` (none / half / all), `market_exit_ma` (ema20 / sma50),
`market_exit_confirm` (1–2 hari). Uji pilihan terbaik dengan workflow **Tuning strategi (manual)**
(`python tune.py --propose` = usulan bulanan; `--realism` = backtest lama vs realistis; tanpa argumen = uji aturan keluar; `--full` = grid lengkap).

## Metodologi singkat

Skor tiap horizon = rata-rata berbobot komponen bernilai −1…+1, dikali 100.

| Horizon | Komponen (bobot) |
|---|---|
| **Pendek** (3–10 hari) | Harga vs EMA20 (20) · EMA9 vs EMA20 (15) · momentum MACD (15) · zona RSI (15) · lonjakan volume naik/turun (15) · breakout/breakdown 20 hari (10) · IHSG vs EMA20 (10) |
| **Menengah** (1–3 bulan) | Harga vs SMA50 (15) · SMA50>SMA100 & menanjak (15) · ADX/DMI (15) · return 3 bulan (15) · kekuatan relatif vs IHSG (15) · rezim RSI (10) · MACD vs sinyal & nol (15) |
| **Panjang** (6–24 bulan) | Harga vs SMA200 (15) · kemiringan SMA200 (10) · momentum 12-1 bulan (15) · ROE (15) · PER relatif sektor (10) · PBV relatif sektor (10) · DER (10, tidak untuk bank) · dividend yield (5) · pertumbuhan laba (10) |

**Ambang sinyal:** ≥ 60 STRONG BUY · ≥ 30 BUY · ≤ −30 SELL · ≤ −60 STRONG SELL · lainnya HOLD.

**Rencana trading** (semua harga dibulatkan ke fraksi harga BEI: Rp1/2/5/10/25):

| | Pendek | Menengah | Panjang |
|---|---|---|---|
| Area beli | close − 0,5 ATR s/d close + 0,3 ATR | close − 1 ATR (≥ EMA20) s/d close + 0,2 ATR | close − 1,5 ATR (≥ SMA50) s/d close, dicicil |
| Cut loss | 1,5 ATR, maks −7% | 2,5 ATR, maks −12% | 4 ATR, maks −20% |
| TP1 / TP2 | 1,5R / 2,5R | 2R / 3,5R | 1,5R / 3R |
| Time-stop | 10 hari bursa | 60 hari bursa | review per kuartal |

Aturan keluar: jual 50% di TP1 lalu cut loss naik ke harga beli; sisa di TP2 atau trailing (EMA9 / EMA20 / SMA200 sesuai horizon).

**Bobot portofolio:** modal dibagi ke bucket (pendek 20%, menengah 30%, panjang 50%). Di tiap bucket, bobot ∝ skor ÷ ATR% (keyakinan tinggi & volatilitas rendah dapat porsi lebih besar), dibatasi bobot maks. per saham & per sektor; sisanya **kas**. Lot juga dibatasi agar rugi per posisi ≤ 1% modal.

**Sinyal jual** ditujukan untuk pemegang saham (tanpa short selling): STRONG SELL = jual seluruhnya, SELL = kurangi 50%, dengan area jual saat pantulan dan level breakdown.

Semua parameter dapat diubah di `config.yaml`.

## Struktur proyek

```
main.py                 orkestrasi harian
config.yaml             parameter
src/data.py             scraper IDX + yfinance (+ data demo)
src/universe.py         filter market cap ≥ Rp 5 T, likuiditas, suspensi
src/indicators.py       EMA/SMA/RSI/MACD/ATR/ADX/volume/momentum
src/signals.py          skor & sinyal 3 horizon + alasan
src/risk.py             area beli, TP, SL, lama hold
src/portfolio.py        bobot & lot
src/sim.py              simulasi transaksi (track record & backtest)
src/tracker.py          catatan kinerja rekomendasi riil (per versi strategi)
src/versions.py         versi strategi per horizon (docs/data/strategy_versions.json)
src/monitor.py          alarm penyimpangan (termasuk alarm dini rugi beruntun)
src/backtest.py         backtest aturan pendek & menengah
src/report.py           dashboard HTML
src/notify.py           Telegram
.github/workflows/daily.yml   jadwal harian
tests/test_core.py      uji unit (dijalankan otomatis sebelum dashboard harian diterbitkan)
```

## Keterbatasan

- Data gratis bisa terlambat/hilang untuk sebagian saham; fundamental Yahoo untuk emiten BEI kadang kosong (komponen yang kosong otomatis tidak dihitung).
- Backtest memakai daftar saham besar saat ini → ada *survivorship bias*; perlakukan sebagai batas atas.
- Sinyal dihitung dari harga penutupan; eksekusi T+1 bisa berbeda karena gap, ARB/ARA, atau antrean.
- Tidak memperhitungkan berita, aksi korporasi mendadak, atau sentimen.

## Belajar dari kesalahan (dengan persetujuan Anda)

- **Alarm penyimpangan** (`src/monitor.py`): setiap hari hasil rekomendasi sungguhan dibandingkan dengan sebaran hasil
  backtest. Status per horizon: BELUM CUKUP DATA · NORMAL · LEBIH BAIK · WASPADA (peluang kebetulan < ~5%) ·
  BAHAYA (< ~1%). Tampil di dashboard (tab Track record), jendela aplikasi, dan Telegram. Tidak mengubah apa pun.
  Sejak 8-11-2026: win rate diuji dengan uji binomial eksak; **alarm dini** (rentetan rugi / win rate terlalu rendah)
  aktif mulai 5 transaksi; tetap jalan walau backtest belum punya data sebaran; jangka panjang (tanpa backtest)
  dibandingkan dengan win rate 50%. Pengaturan di `monitor:` config.yaml.
- **Versi strategi** (`src/versions.py`): setiap perubahan parameter horizon, ambang, biaya, atau `LOGIC_VERSION`
  (naikkan bila rumus di kode berubah) membuat versi baru (v1, v2, ...). Setiap rekomendasi menyimpan versinya
  (kolom `strategy`); rekomendasi sebelum 9-11-2026 = v0. Track record menampilkan hasil per versi; alarm menilai
  versi aktif saja begitu versi itu punya ≥ 10 transaksi (sebelumnya digabung dengan versi lama).
- **Data tepat waktu** (sejak 14-11-2026): update terjadwal 17:30, 20:30, dan 06:30 WIB (GitHub sering menunda jadwal);
  Telegram hanya sekali per tanggal data. Bila bar harian Yahoo untuk hari bursa terakhir belum terbit, bar itu
  dihitung dari data per jam (uji 13-11-2026 atas 122 saham: harga penutupan sama persis, volume selisih median 4%).
  Bar sesi yang belum selesai dibuang. Matikan dengan `data.hourly_fill: false`.
- **Peringatan data basi**: bila data harga belum sampai hari bursa terakhir (lewat `data.ready_after`, bawaan 17:00
  WIB), dashboard, Telegram, dan aplikasi menampilkan peringatan. Isi `data.holidays` dengan libur bursa.
- **Usulan parameter bulanan** (`python tune.py --propose`, otomatis tanggal 1 lewat workflow Tuning strategi):
  satu perubahan parameter dipilih dari data sebelum 6 bulan terakhir, lalu harus tetap lebih baik di 6 bulan terakhir
  dan di simulasi portofolio. Hasil di `docs/data/proposal.json` + Telegram. Diterapkan hanya lewat tombol
  **Usulan → Terapkan** di aplikasi (config lama disalin ke `backup/`) atau dengan mengubah `config.yaml`.
