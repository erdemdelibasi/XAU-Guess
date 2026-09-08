# XAU-Guess

**Altın (GC=F) ve gümüş (SI=F)** için tahmin ve kağıt-alım/satım sistemi.
Anahtarsız kamuya açık piyasa verisiyle çalışır, günde bir kez her metal için
karar üretir ve metal başına on bağımsız $1000 sanal portföyü yan yana
yarıştırır. Ayrıca bir YouTube kanalının (Kanal Finans TŞ) altın/gümüş
görüşlerini ve makro gerekçelerini ayrı bir akış olarak çıkarır.

> **Bu bir yatırım tavsiyesi aracı değildir.** Hiçbir gerçek emir verilmez,
> hiçbir aracı kurum hesabına bağlanılmaz. Tüm portföyler simülasyondur.

---

## Bu sistem ne iddia ediyor?

Az şey — ve bunu açıkça söylemek projenin ana tasarım ilkesidir.

`backend/research/` altındaki ölçümler şunu buldu:

| Soru | Cevap |
|---|---|
| Altın günlük ufukta tahmin edilebilir mi? | Model şansı yeniyor (%53,3, z=+2,04) |
| Maliyeti karşılıyor mu? | 5 günlük ufukta **evet** (duvar %52,7) |
| "Hep yükseliş" demekten iyi mi? | **Hayır.** Altın zaten %55,7 yükseliyor |
| Peki ne işe yarıyor? | **Pozisyon boyutlandırma** — düşüşü %44,4'ten %30,1'e indiriyor |
| Gümüş daha mı iyi? | **Hayır.** Aynı getiri, 1,86 kat oynaklık, %75,8 düşüş |
| Altın/gümüş oranı yön söyler mi? | **Hayır.** 60 testin 0'ı geçti |
| İkisini birden tutmak? | Daha çok getiri, orantısız daha çok risk |
| Fed faiz kararları alınabilir bir şey veriyor mu? | **Hayır.** 32 testin 0'ı geçti |
| Merkez bankası alımı izlenebilir mi? | Tonaj **hayır** (günlük anahtarsız veri yok); **izi** evet |

Yani: **yön tahmini al-ve-tut'u yenmiyor.** Ölçülebilir katkı yalnızca riski
yönetmekte ve orada bile mütevazı — 19,9 yıllık örneklem dışı testte Sharpe
0,58'den 0,64'e çıkıyor, karşılığında yıllık getiriden 2,1 puan veriyor.

Bu yüzden **al-ve-tut sistemde gerçek bir portföydür**, raporda bir dipnot
değil. Diğer dokuz strateji ona yenildiğinde bu ekranda görünür.

### Gümüş neden ayrı ölçüldü

"Varlık ekle" tek satırlık bir ayar değişikliği gibi görünür. Değil:

| | Altın | Gümüş |
|---|---|---|
| 25 yıllık getiri | %11,8/yıl | %11,7/yıl |
| Oynaklık | %18,1 | **%33,7** |
| Maksimum düşüş | %44,4 | **%75,8** |
| Al-ve-tut Sharpe | 0,56 | **0,25** |
| Taban oran (5g) | %55,7 | %53,9 |
| Öncü sürücüler | tip, ief, vix | tip, vix (**`ief` geçmiyor**) |

Gümüş neredeyse aynı getiriyi iki katı acıyla veriyor. Altının sabitlerini
gümüşe kopyalamak hiçbir hata vermezdi — sadece gümüşün tüm skorbordunu
sessizce yeniden tabanlar ve oynaklık hedeflemesini "daha az gümüş tut"a
çevirirdi. Her sayı `backend/research/compare.py` ile ölçülüp
`backend/assets.py`'ye işlendi.

## Neden altın?

Kardeş proje XRP-Guess kripto üzerinde aynı mimariyi denedi ve aritmetik bir
duvara çarptı: 15 dakikalık ufukta XRP ortalama %0,219 oynuyor, gidiş-dönüş
komisyonu %0,20 — **başabaş için %95,7 yön isabeti** gerekiyordu. Hiçbir model
bunu yapamaz.

Altında aynı hesap:

| | Ortalama hareket | Maliyet | Başabaş | Gereken avantaj |
|---|---|---|---|---|
| XRP, 15 dakika | %0,219 | 20 bp | %95,7 | +45,7 puan |
| **Altın, 5 gün** | **%1,881** | **10 bp** | **%52,7** | **+2,7 puan** |

Hareket 3,7 kat büyük, maliyet 2 kat ucuz. Duvar **7,3 kat alçak.** Modeli
iyileştirmedik; oynanan oyunu değiştirdik.

Ayrıca altının kriptoda olmayan bir şeyi var: **gerçek makro sürücüler.**
Altın, getirisi olmayan bir varlığın dolar fiyatıdır, dolayısıyla dolar ve
nakit tutmanın getirisi ona mekanik olarak bağlıdır.

---

## Nasıl çalışır?

```
GitHub Actions (cron)
  -> predict.py    her iş günü 23:00 UTC (COMEX kapanışından sonra)
  -> retrain.py    her gün 01:30 UTC
       |
       v
   Supabase  ->  Vercel (frontend)
```

### Sinyal bileşenleri

| Bileşen | Nereden | Backtest edilebilir mi |
|---|---|---|
| `technical` | RSI, MACD, EMA, Bollinger, Donchian (günlük) | evet |
| `ml` | Gradient boosting, 27 özellik, 5 günlük etiket | evet |
| `macro` | TIP / IEF / VIX — ölçülmüş öncü sürücüler | evet |
| `news` | Google News RSS, metal başına ayrı sorgu ve sözlük | hayır (arşiv yok) |
| `claude` | Claude'un bağımsız yargısı (metal başına günde 1 çağrı) | hayır |

Bileşenler **log-odds uzayında**, beyan ettikleri güvene göre değil
**ölçülmüş sicillerine** göre havuzlanır. O metalin taban oranından (altın
%55,7, gümüş %53,9) daha iyisini yapamamış bir bileşen otomatik olarak
susturulur.

### Portföyler

| Portföy | Mantık |
|---|---|
| **`buyhold`** | Hiçbir şey yapma. **Kıyas ölçütü.** |
| `voltarget` | Pozisyonu gerçekleşen oynaklığa göre ölçekle |
| `trend` | 200 günlük ortalamanın altında pozisyonu kıs |
| `defensive` | İkisi birlikte |
| `ensemble` | Tüm sinyaller + risk kuralları |
| `technical` / `ml` / `macro` / `claude` | Tek sinyal, tek portföy |
| `kanalfinans` | Tunç Şatıroğlu ne derse o. Tam giriş/çıkış, zarar-kes takipli |

### Kanal Finans TŞ

Kanalın videolarından **iki ayrı şey** çıkarılır:

- **Görüşler** — altın/gümüş başına: sadık tek cümlelik özet, konuşmacının
  duruşu, al/tut/sat, ve verdiyse **ons hedefi, zarar-kes ve direnç
  seviyeleri**. `kanalfinans` portföyü bunları birebir uygular; zarar-kes
  her gün sürekli izlenir.
- **Gerekçeler** — görüşün dayandığı makro hikâye: `SAVAS`,
  `ABD_POLITIKA` (Fed/ABD siyaseti), `REZERV` (merkez bankası altın
  alımları, dolarsızlaşma), `DOLAR`, `ENFLASYON`, `ARZ_TALEP`, `BORSA`,
  `TURKIYE`. Bunlar **bilerek işlem üretmez** — çıplak bir "yükseliş"in
  bağlamıyla okunabilmesi için tutulur.

Bu bir tahmin bileşeni **değildir**; bir insanın görüşünün raporudur ve
arayüzde de öyle etiketlenir. Ayrıca **GitHub Actions'ta çalışmaz**: YouTube
transkript isteklerini bulut IP'lerinden sistematik olarak reddediyor, o
yüzden Windows Task Scheduler ile kullanıcının kendi makinesinde 15 dakikada
bir çalışır (`backend/run_kanal_finans_hidden.vbs`).

### 19,5 yıllık backtest, ALTIN (ETF maliyeti, 10 bp gidiş-dönüş)

| Strateji | YBG | Sharpe | Maks düşüş | Calmar | İşlem |
|---|---|---|---|---|---|
| `macro` | %9,4 | 0,60 | %37,2 | **0,25** | 2288 |
| `ml` | %9,3 | 0,59 | %38,3 | 0,24 | 379 |
| `voltarget` | %9,6 | **0,67** | %40,0 | 0,24 | 158 |
| `technical` | %8,9 | 0,57 | %38,6 | 0,23 | 377 |
| **`buyhold`** | **%10,3** | 0,56 | %44,4 | 0,23 | 1 |
| `ensemble` | %7,4 | 0,70 | **%32,7** | 0,23 | 457 |
| `defensive` | %8,0 | 0,65 | %38,4 | 0,21 | 286 |
| `trend` | %8,2 | 0,54 | %41,5 | 0,20 | 159 |

**Al-ve-tut hâlâ en yüksek getiriyi veriyor.** Diğerleri riskte kazanıyor,
getiride kaybediyor. Ve **banka gram altın maliyetinde (150 bp) hiçbiri
al-ve-tut'u geçemiyor** — `macro` 2288 işlemiyle Calmar 0,25'ten 0,03'e
düşüyor.

### Aynı test, GÜMÜŞ (kendi maliyeti, 20 bp gidiş-dönüş)

| Strateji | YBG | Sharpe | Maks düşüş | Calmar | İşlem |
|---|---|---|---|---|---|
| `macro` | %9,2 | 0,31 | %65,9 | **0,14** | 2051 |
| `technical` | %8,3 | 0,28 | %68,1 | 0,12 | 389 |
| `voltarget` | %8,2 | 0,31 | %69,5 | 0,12 | 169 |
| `ml` | %7,9 | 0,26 | %68,8 | 0,11 | 408 |
| **`buyhold`** | **%8,6** | 0,25 | %75,8 | 0,11 | 1 |
| `ensemble` | %5,9 | **0,32** | **%59,3** | 0,10 | 442 |

Aynı şekil, daha sert zemin. `ensemble` düşüşü %75,8'den %59,3'e indiriyor
ama getirinin üçte birini ödüyor.

---

## Kurulum

### 1. Supabase

Yeni bir proje aç, SQL Editor'de `supabase/schema.sql`'i çalıştır.
Project Settings → API'den `URL`, `anon key` ve `service_role key` al.

### 2. GitHub Secrets

Repo → Settings → Secrets and variables → Actions:

| Secret | Zorunlu |
|---|---|
| `SUPABASE_URL` | evet |
| `SUPABASE_SERVICE_KEY` | evet (`service_role`) |
| `ANTHROPIC_API_KEY` | hayır — yoksa `claude` bileşeni nötr kalır |

### 3. Frontend

`frontend/config.js` içine Supabase URL ve **anon** key'i yaz (service_role
değil). Vercel'e `frontend/` klasörünü statik olarak bağla.

### 4. Yerel geliştirme

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows
# .venv/bin/pip install -r requirements.txt       # macOS / Linux

cp .env.example .env      # değerleri doldur
.venv/Scripts/python -m pytest tests/ -v
```

Araştırma tezgâhı Supabase'e hiç dokunmaz, anahtarsız çalışır:

```bash
cd backend/research
python panel.py --rebuild   # her iki metal icin panel (~60 sn)
python wall.py              # once bunu oku
python compare.py           # gumus vs altin -- assets.py'deki sayilarin kaynagi
python edge.py              # ~3 dk
python defense.py
python ratio.py             # altin/gumus orani -- 60 test, 0 gecti
python ablation.py          # ~12 dk: etiket mi ozellikler mi
python fedcycle.py          # Fed faiz kararlari -- 32 test, 0 gecti
python realrate.py          # gercek reel faiz vs vekil; merkez bankasi izi
```

### 5. Kanal Finans (isteğe bağlı, yerel)

GitHub Actions'ta çalışmaz (YouTube bulut IP'lerini engelliyor). Windows'ta:

1. `backend/.env` içine `ANTHROPIC_API_KEY` ve Supabase bilgilerini yaz.
2. Task Scheduler → yeni görev → eylem:
   `wscript.exe "...\backend\run_kanal_finans_hidden.vbs"`
3. Tetikleyici: günlük 00:00, **15 dakikada bir tekrarla, 24 saat boyunca**.
4. Ayarlar: `MultipleInstances = IgnoreNew`, `ExecutionTimeLimit = 10 dk`,
   ve **"Yalnızca AC gücündeyse çalıştır" seçeneğini KAPAT** — varsayılan
   açık, ve dizüstü fişten çekiliyken görev hiç çalışmaz.

---

## Sınırlamalar

- **25 yıllık panel altın için olağanüstü bir boğa dönemi** (270$ → 4400$,
  yıllık %11,8). Al-ve-tut'un bu kadar güçlü görünmesinin bir kısmı budur ve
  gelecek için garanti değildir. Savunma kurallarının bedeli boğada ödenir,
  karşılığı ayıda alınır.
- **`claude`, `news` ve `kanalfinans` backtest edilemez** — geçmiş arşivleri
  yok. Değerleri ancak birkaç aylık canlı veriyle yargılanabilir.
- **Gümüşün hafta sonu fiyatı yok.** Altın için PAXG bir 24/7 vekil sağlıyor;
  gümüşün güvenilir muadili yok, o yüzden hafta sonu son COMEX kapanışı
  `SI=F(stale)` etiketiyle gösterilir.
- **Altın/gümüş oranı ölçüldü ve yön bilgisi taşımıyor.** 5 form × 3 hedef
  × 4 ufuk = 60 testin **sıfırı** eşiği geçti. Oran arayüzde tarihsel
  konumuyla gösteriliyor ama hiçbir strateji ona göre işlem yapmıyor —
  artık "test edilmedi" diye değil, **test edildi diye**
  (`backend/research/ratio.py`).
- **Fed faiz kararları ölçüldü ve ayrıca alınabilir bir şey bırakmıyor.**
  Olay, rejim ve sürpriz olarak üç ayrı sınanabilir parçaya bölündü; 32
  testin **sıfırı** eşiği geçti. İndirim sonrası 20 gün altında %+2,71,
  gümüşte %+5,60 — yön hikâyeyle uyumlu, ama sürükleme çıkarıldığında
  eşiğin uzağında ve bu örneklemin görebileceği en küçük fark 9-13 puan
  (`backend/research/fedcycle.py`).
- **Merkez bankası altın alımı doğrudan izlenmiyor ve izleniyormuş gibi
  yapılmıyor.** Dünya Altın Konseyi tonaj verisi üç aylık, gecikmeli ve
  kayıt duvarının arkasında; günlük anahtarsız serisi yok. Ölçülen şey
  **izi**: altının makro modelinden artan kısmı. Reel faiz betası 2020'de
  −0,073 iken 2026'da +0,001 — "altın reel faizden koptu" iddiasının
  ölçülmüş hâli. Ama artık modelin açıklamadığı her şeydir, alımın kanıtı
  değildir; ve ileri getiriyi de öncülemiyor (`backend/research/realrate.py`).
- **FRED erişilemezse** reel faiz, TIP/IEF vekiliyle yaklaşık hesaplanır.
  Vekil **seviyeyi** yakalamıyor (r=+0,59) ama **değişimi** neredeyse birebir
  yakalıyor (r=+0,93, ölçek 1,02x) ve modelde gerçek seriden ayırt
  edilemiyor (p=0,984). Yani bu bir eksiklik değil, ölçülmüş bir denklik.
- **Backtest gelecek değildir.** Buradaki hiçbir sayı "böyle olacak" demek
  değil; "geçmişte böyle olmuş" demek.

Ölçülüp **elenmiş** hipotezlerin tam kaydı: `backend/research/README.md`.
Mimari kararların gerekçeleri: `CLAUDE.md`.
