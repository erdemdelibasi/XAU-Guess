# XAU-Guess

Kişisel kullanım için **altın (GC=F) ve gümüş (SI=F)** tahmin/izleme PWA'sı.
Anahtarsız kamuya açık piyasa verisi kullanır, **hiçbir aracı kurum hesabı
yok, gerçek emir yok**. Tüm portföyler sanal/kağıt üzerindedir ($1000
simülasyon).

XRP-Guess'in kardeşi ve ondan çok şey devraldı — ama **kopyası değil.**
Farklar sezgiyle değil ölçümle seçildi ve nedenleri aşağıda yazılı.

## Mimari

```
GitHub Actions (cron, sunucusuz zamanlayıcı)
  -> backend/predict.py       her iş günü 23:00 UTC (COMEX kapanışından sonra)
                              iki metal için de sırayla çalışır
  -> backend/retrain.py       her gün 01:30 UTC
  -> backend/daily_report.py  her iş günü 06:00 UTC (09:00 TRT) -- günlük
                              özet maili; hiçbir şey yazmaz, sadece okur

Kullanıcının kendi bilgisayarı (Windows Task Scheduler -- GitHub Actions DEĞİL,
bkz. aşağıdaki Kanal Finans notu)
  -> ../Kanal-Finans-Fetcher/fetcher.py    her 30 dk -- YouTube'dan TEK çekiş,
                              XRP-Guess'le PAYLAŞILAN sibling repo, iki projeye
                              de kendi şemasıyla yazar (bkz. o reponun README'si)
  -> backend/run_kanal_finans_hidden.vbs -> run_kanal_finans.ps1
                              her 15 dk, YouTube'a HİÇ gitmez: sadece
                              fetcher'ın yazdığı bekleyen görüşleri portföye
                              uygular (bkz. aşağıdaki Kanal Finans notu)
       |
       v
Supabase (Postgres + otomatik REST API, RLS ile korunur)
       |
       v
Vercel (frontend/ statik hosting, GitHub push'unda otomatik deploy)
```

- **Backend**: Python, `backend/` altında.
- **Frontend**: framework yok, saf HTML/CSS/JS. `config.js` gerçek Supabase
  URL + anon key içerir (bilerek — anon key public kullanım için tasarlanmıştır,
  gerçek koruma RLS'dedir).
- **Şema**: `supabase/schema.sql` tek doğruluk kaynağı. Değiştirirsen dosyayı
  güncelle VE kullanıcıya Supabase SQL Editor'de çalıştıracağı migration'ı
  ayrıca ver (repo'dan otomatik uygulanmaz).
- **Araştırma tezgâhı**: `backend/research/`, canlı sistemden tamamen ayrık.

---

## ÖNCE BUNU OKU: sistem ne iddia ediyor, ne iddia etmiyor

Bu projenin en önemli bulgusu olumsuz bir bulgudur ve kod her yerde buna
göre şekillenmiştir. `backend/research/README.md` tam ölçümleri taşıyor;
özeti:

1. **Altının duvarı aşılabilir.** 5 günlük ufukta başabaş yön isabeti %52,7
   (XRP'de 15 dakikada %95,7 idi). Oyun oynanabilir.
2. **Yön modeli şansı yeniyor** — 5 günde %53,26, örtüşme düzeltmeli z=+2,04.
3. **Ama "hep YUKARI" demeyi yenmiyor.** Altın 5 günde zaten %55,7, gümüş
   %53,9 ihtimalle yükseliyor. Model hiçbir ufukta bu tabanı geçmiyor ve
   Brier beceri skoru her ufukta negatif.
4. **Model pozisyon boyutunu da eğemiyor.** `research/tilt.py`'de eğitim
   ızgarası zorlanmadan EĞİM=0 seçti.
5. **Ölçülebilir katkı veren tek mekanizma oynaklığa tepki veren pozisyon
   boyutlandırma.** 19,9 yıl örneklem dışı: Sharpe 0,58→0,64, maksimum düşüş
   %44,4→%30,1, karşılığında 2,1 puan yıllık getiri.
6. **Altın/gümüş oranı yön bilgisi taşımıyor.** 5 form × 3 hedef × 4 ufuk =
   60 testin **sıfırı** eşiği geçti (`research/ratio.py`). Rotasyon da,
   çifti birlikte tutmak da altını risk-ayarlı geçemiyor.
7. **Sorun etikette değil.** Sürüklemesi çıkarılmış bir etiket denendi ve
   IC +0,055'ten −0,004'e düştü (`research/ablation.py`): taban oranın
   kendisi öğrenilebilir olan tek şey.
8. **Fed faiz kararları da ayrıca alınabilir bir şey bırakmıyor.**
   `research/fedcycle.py` "Fed indirince altın çıkar" iddiasını üç ayrı
   sınanabilir parçaya böldü (olay / rejim / sürpriz) ve **32 testin 0'ı**
   eşiği geçti. Taban oran gevşeme rejiminde daha yüksek görünüyor
   (altın 0,596 vs 0,557) ama bu örneklemin ayırt edebileceği en küçük
   fark 9-13 puan, ölçülen ise 3,9 puan — yani "etki yok" değil, "varsa
   göremiyoruz". Politika duruşunu kolon olarak eklemek de reddedildi
   (p=0,947 ve p=0,377).

Madde 5'in madde 3'ü **kurtarmadığını** anlamak kritik: oynaklık hedefleme
hiçbir şey tahmin etmiyor, gerçekleşen oynaklığa tepki veriyor ve oynaklık
(yönün aksine) güçlü şekilde otokorelasyonlu. Bunlar ayrı iki makine.
`defense.py`'nin kazancını "demek ki model iyi" diye okuma.

**Bu yüzden `buyhold` gerçek bir portföydür**, raporda bir satır değil.
XRP-Guess al-ve-tut'u sadece düzyazıda anıyordu ve her stratejinin ona
yenildiğini okuyucunun kendisi çıkarması gerekiyordu. Burada ekranda,
diğerlerinin yanında, kıyas rozetiyle duruyor.

---

## Önemli kısıtlar

- **Gerçek para/emir yok.** Metal başına on portföy (dokuzu `trading.py`'nin
  motoruyla, biri Kanal Finans takipçisi) — toplam yirmi, hepsi sanal.
- **Hiçbir piyasa verisi anahtarı gerekmiyor.** Yahoo Finance chart API
  (GC=F, SI=F + 13 makro seri), Binance'in kamuya açık
  `data-api.binance.vision` uç noktası (altının hafta sonu fiyatı için
  PAXG), ve YouTube'un anahtarsız RSS'i.
- **Gümüşün hafta sonu fiyatı YOKTUR.** Altın için PAXG bir 24/7 vekil
  sağlıyor; gümüşün Binance'te güvenilir bir muadili yok. `get_live_price`
  bu durumda son COMEX kapanışını döndürür ve kaynağı `SI=F(stale)` diye
  **etiketler**. Dürüst bir boşluk, kaynağı eğitim verisinden farklı bir
  sayıdan iyidir. `ANTHROPIC_API_KEY` isteğe bağlı — yoksa `claude` bileşeni
  sürekli nötr kalır, sistem çökmez.
- **FRED aralıklı erişilebiliyor — canlı yol ona bağlanamaz.** 2026-09-07'de
  tekrarlanan 60 sn zaman aşımı verdi (aynı anda her Yahoo çağrısı geçerken);
  2026-09-08'de aynı makineden her seri 1,2 sn altında geldi ve arada kodda
  hiçbir şey değişmedi. Doğru okuma "engel kalktı" değil, **"bu host burada
  aralıklı olarak engelli"**. `fetch_data.get_fred_series` bilerek `None`
  dönebilir ve `indicators.py` TIP/IEF vekiline düşer.

  **Hiçbir model özelliği bir FRED serisine bağlanmamalı.** Ağ havasına göre
  var olup yok olan bir kolon, kayıtlı modelin özellik listesini bir sonraki
  koşuyla uyumsuz hâle getirir — `predict.py` bunu yakalayıp yeniden eğitir,
  ama her gün bunu yapmak sessiz bir israftır. Araştırma tezgâhı FRED'i
  serbestçe kullanır (`research/fedcycle.py`, `research/realrate.py`).

  **Ve vekilin bir bedeli olmadığı artık ölçüldü** (`research/realrate.py`):
  5 günlük değişimde DFII10 ile vekil r=+0,929 ve ölçek oranı 1,02x;
  `real_yield_chg`'i gerçek seriyle değiştiren eşleştirilmiş A/B'de IC
  +0,0646 → +0,0643, **p=0,984**. Vekil bedava. Buna karşılık **seviye**
  korelasyonu sadece +0,592 — yani eski uyarı hâlâ geçerli: **vekile asla
  "reel faiz" gibi kesin bir sayı muamelesi yapma**, şeklini yakalar,
  seviyesini değil.

### Ufuk bir seçimdir, cron'un yan etkisi değil

XRP-Guess 15 dakika sonrasını tahmin ediyordu çünkü cron 15 dakikada bir
çalışıyordu. Ufuk zamanlamanın kazasıydı ve projeyi %95,7'lik bir duvarın
yanlış tarafına hapsetti. Burada ufuk **önce** seçildi (`research/wall.py`),
sistem sonra kuruldu. `ml_model.HORIZON_DAYS = 5` bu tablodan geliyor:
1 günde duvar %56,2, 5 günde %52,7, 20 günde %51,3 — ve `edge.py` modelin
sadece 5 günde duvarı aştığını ölçtü.

### İki metal, tek boru hattı — ama paylaşılan sabit YOK

`assets.py` bu projedeki en önemli dosyalardan biri: metaller arasında
farklı olabilecek her şey orada ve **her sayısı ölçülmüştür**
(`research/compare.py`).

| | Altın | Gümüş | Neden farklı |
|---|---|---|---|
| `base_rate_up` | 0,557 | 0,539 | `ensemble.py` her bileşeni buna karşı ölçüyor |
| `target_volatility` | %15 | %28 | gümüş 1,86 kat oynak (ölçüldü) |
| `fee_rate` | 5 bp | 10 bp | gümüşün spread'i fiyatının daha büyük bir oranı |
| `leading_drivers` | tip, ief, vix | tip, vix | **`ief` gümüşü öncülemiyor** (t=2,56 vs eşik 3,29) |
| `price_scales.macd` | 172 | 93,4 | gümüşün `macd_hist/close` p90'ı 1,84 kat büyük |
| `price_scales.ema_cross` | 51,5 | 29,3 | aynı sebep (1,76 kat) |
| `price_scales.sma200` | 6,5 | 3,72 | aynı sebep (1,75 kat) |
| model dosyası | `xau_model.joblib` | `xag_model.joblib` | farklı özellik seti, değiştirilemezler |

**"Varlık ekle" tek satırlık bir ayar değişikliği gibi görünüp öyle
değildir.** Altının sayılarını gümüşe kopyalamak hiçbir hata vermez; sadece
gümüşün tüm skorbordunu sessizce yeniden tabanlar ve oynaklık hedeflemesini
"daha az gümüş tut"a çevirir. `test_trading.test_target_volatility_is_per_asset_not_global`
ve `test_ensemble.test_always_up_contributes_nothing_at_silvers_base_rate_too`
bu ikisini kilitliyor.

Ölçülen tablo şu: **gümüş 25 yılda altınla neredeyse aynı getiriyi
(%11,7 vs %11,8) iki katı acıyla veriyor** — oynaklık %33,7 vs %18,1,
maksimum düşüş %75,8 vs %44,4, al-ve-tut Sharpe'ı 0,25 vs 0,56.

**Fiyat türevli ölçekler 2026-09-08'de bu tabloya taşındı ve bu bir hata
düzeltmesidir.** `indicators.py`'nin yedi skorlayıcısından üçü fiyat türevli
bir niceliği sıkıştırıyor ve o niceliğin dağılımı metale bağlı. Sabitler
yalnızca altın panelinde ölçülmüştü; gümüş onları ödünç alıyordu. Sonuç,
bu dosyanın "Ölçek sabitleri tahmin edilmez, ölçülür" bölümünde anlatılan
**tam olarak aynı arıza**, ikinci varlık kapısından geri girmiş hâli:

| | altın | gümüş (eski) | gümüş (yeni) |
|---|---|---|---|
| `macd` doyma | %10,6 | **%35,2** | %10,0 |
| `macd` medyan \|skor\| | 0,388 | **0,715** | 0,382 |
| `trend` doyma | %4,7 | %14,9 | %4,6 |

Makro kaynaklı üç ölçek (`BOND_SCALE`, `VIX_SCALE`, `REAL_YIELD_SCALE`) iki
panelde de üçüncü haneye kadar aynı çıktı — aynı serileri okuyorlar — o yüzden
modül sabiti olarak kaldılar. Bölünmenin nerede olması gerektiğini tahmin
etmeye gerek kalmadı, ölçüm söyledi.

**Bedeli ölçüldü ve bir performans kazancı DEĞİL:** eşleştirilmiş backtest'te
(gümüş, 4897 seans, 19,5 yıl, aynı ML yolu) Calmar `technical` için +0,002,
`ensemble` için −0,004 oynadı, işlem sayısı değişmedi (715 → 718). Harman skoru
zaten hiçbir ayarda doymuyordu (%0,0), çünkü yedi ağırlıklı terim aynı anda
nadiren kırpılır — hasar **harmanın içindeki derecelendirmedeydi** ve bir Calmar
sütunu onu göremez. Yani bu bir doğruluk düzeltmesi: sabitlerin belgelenmiş
iddiası ("p90 ≈ 1,0") iki varlıktan biri için yanlıştı.

İki incelik:
- **Panelde varlığın kendisi makro kolonu olamaz.** `assets.macro_symbols_for`
  gümüşün panelinden `silver`'ı çıkarıp `gold`'u koyuyor; yoksa gümüş kendi
  kapanışıyla mükemmel korelasyonlu bir "makro" kolon taşır ve `gs_ratio`
  sabit 1,0 olur.
- **`gs_ratio` her iki panelde de altın/gümüş olmalı.** Körü körüne
  `close/counterpart` hesaplamak gümüş panelinde **tersini** verir — adı
  `gs_ratio_z` olan ama işareti ters bir özellik. `indicators.py` bunu
  açıkça ayırıyor.

### Altın/gümüş oranı: ölçüldü, taşımıyor — ama ekranda kalıyor

Bu proje uzun süre "oran ölçülmedi" itirafını taşıdı. `research/ratio.py`
onu kaldırdı ve cevap negatif: **60 testin 0'ı** Bonferroni eşiğini geçti.

Üç şey burada yanlış yapılmaya çok müsait:

1. **Tüm-örneklem ortalamasına dönüş testi geleceği okur.** Oran 2011'de
   32, 2020'de 126 gördü; panelin ilk yarısının medyanı 60,3, ikincisinin
   78,7. "Ortalama" sabit değil, kaymış bir seviye. Her test **kayan 250
   günlük z** kullanıyor — tüm-örneklem z'si kullanan bir sürüm harika
   sonuç verir ve tamamen sahtedir.
2. **"Oran döner" bir UZUN/KISA iddiasıdır.** log(oran) değişimi = altının
   log getirisi − gümüşünkü. Bu sistem kısa pozisyon almıyor, dolayısıyla
   spread testinin geçmesi bile tek başına işe yaramazdı. Ayrı ayrı **bacak
   testleri** karar verici olandır — ve her iki bacak da **pozitif** çıktı
   (yüksek oran, ardından iki metalin de yükselmesini öncülüyor), yani
   hikâyenin öngördüğünün tersi bir yapı.
3. **Rotasyon kontrolsüz okunursa "işe yarıyor" görünür.** "z yüksekse
   gümüş tut" kuralı YBG'de altını 2,1 puan geçiyor — çünkü gümüş 1,86 kat
   oynak ve örneklem yükseliyor. **Oynaklık eşitlendiğinde her boyutta
   altının altına düşüyor.** `ratio.rotation_curve(vol_match=...)` bu
   kontrolü zorunlu kılmak için orada; kapatıp okuma.

`gs_ratio_z` `ml_model.FEATURE_COLUMNS` içinde **kaldı**, ve bu bir karar:
permütasyon önemi ile yürüyen-ileri A/B **her iki metalde de işaret
bakımından çelişti** (altın +0,19p vs +0,78p, gümüş −1,67p vs −0,20p),
eşleştirilmiş McNemar p=0,489 ve p=0,935. p=0,49'a dayanarak kolon çıkarmak
tam olarak bu tezgâhın önlemek için var olduğu şeydir. **Gürültüye göre
hareket etmek de bir aşırı-uydurmadır.**

Oran arayüzde **tarihsel konumuyla birlikte** gösteriliyor
(`predictions.gs_ratio`, `gs_ratio_z`) ve yanında ölçüm sonucu yazıyor.
Çıplak bir "67,1" okuyucuyu ölçekten yoksun bırakır ve akla gelen ölçek
("60'a döner") tam da desteklenemeyen inançtır. **Bu iki kolonu hiçbir
strateji ve hiçbir bileşen okumuyor** — okutmadan önce ratio.py'yi yeniden
çalıştır.

### ML bileşeni taban orana takılı: suç etikette değil

`research/ablation.py` iki açıklamayı ayırdı ve **kendi tercih ettiğim
hipotezi çürüttü**:

- **A) Etiket.** Altının etiketlerinin %55,8'i 1; sınıflandırıcı marjinali
  öğrenip duruyor olabilir. Test: sürüklemesi çıkarılmış etiket (L1) eğitim
  dengesini temiz %51,2'ye getirdi — ve **IC +0,0554'ten −0,0040'a düştü.**
- **B) Özellikler.** Dört farklı özellik grubu denendi (F1-F4); hiçbiri
  üretim setinden ayırt edilemedi (en düşük p=0,35).

Yani model taban oranı *yeniden üretiyor* değil; **taban oran öğrenilebilir
olan tek şey.** Altının +0,055'lik IC'si büyük ölçüde "her şey yükselir"
bilgisidir. Bir sonraki kişi "etiketi dengeleyelim" diye gelirse: denendi,
ölçüldü, işe yaramadı.

**Ama negatifin sınırını da yaz:** bu örneklemin sıfırdan ayırt edebileceği
en küçük IC **0,086**, ölçülen ise 0,055. Yani çalışma "IC > 0,086 değil"
diyebiliyor, "IC = 0" **diyemiyor**. Doğru okuma "burada bir şey yok" değil,
"büyük bir şey yok; küçük bir şey varsa 25 yıllık günlük veri onu
kanıtlayamaz". Çözüm daha çok özellik değil, **daha çok bağımsız gözlem**.

### Taban oran her yere sızar ve düzeltilmezse her şeyi bozar

Altın %55,7, gümüş %53,9 ihtimalle yükseliyor. XRP ~%50/%50 bir yazı-turaydı.
Bu tek fark dört ayrı yerde düzeltme gerektirdi ve dördü de sessizce yanlış
olabilirdi:

0. **`base_rate` bir parametredir, modül sabiti değil.** `ensemble.combine`,
   `component_evidence`, `calibration.fit/apply` hepsi onu argüman olarak
   alır. Gümüşe altının oranını vermek hiçbir hata üretmez, sadece 1,8
   puanlık görünmez bir yanlılık enjekte eder.
1. **`ensemble.py`** — bileşenler artık "P(doğru)" ile değil, **taban orana
   karşı olabilirlik oranıyla** havuzlanıyor. Hep-YUKARI diyen bir bileşen
   %55 isabet tutturur ve %50'ye karşı ölçülürse yetenekli görünür; burada
   tam olarak **sıfır** kanıt üretiyor (`test_ensemble.py` bunu kilitliyor).
   Bunun için `model_state` tek bir isabet oranı değil **dört sayaç** tutuyor
   (UP çağrıları/doğruları, DOWN çağrıları/doğruları) — çünkü bir bileşenin
   UP ve DOWN taraflarının bilgisizlik noktaları **farklıdır** (altında
   0,557 ve 0,443). İkisini de 0,557'ye büzen ilk sürüm, DOWN tarafında
   sıfır yeteneği olan bir bileşene +0,024 kanıt ve %4,9 hak edilmemiş etki
   ağırlığı veriyordu.

   > Bu sabitin kendisi de bir kez yanlıştı: kodda 0,552 yazıyordu, çünkü
   > `wall.py`'nin tablosundan yanlış satır okunmuştu. Gerçek değer 0,557.
   > Yarım puan — ama tüm sistemin kalibre edildiği tek sayıda.
   > `research/compare.py` yakaladı.
2. **`calibration.py`** — isotonic tabanı 0,5 değil, o varlığın taban oranı.
   Taban oranı yakalayan bir bileşenin kalibre güveni tam sıfır olmalı.
   Kalibratör dosyaları da varlık başınadır (`calibration_gold.joblib` /
   `calibration_silver.joblib`).
3. **`frontend/app.js`** — her yerde yönün yanında `edge_over_base` gösteriliyor.
   Sadece "YÜKSELİŞ, %62 güven" yazan bir arayüz sistematik olarak abartır.

`retrain.py` her gece gerçekleşen taban oranı sabitin yanına basıyor;
6 puandan fazla saparsa yüksek sesle uyarıyor. Çünkü sabit kayarsa her
bileşenin "becerisi" sessizce yeniden tabanlanır.

### Düz mumlar atılmaz, işaretlenir

GC=F günlük geçmişinin ~%11'i (modern dönemde ~%5) `open=high=low=close`
olan "düz mum". İlk içgüdü atmaktı. **Ölçüm bunu reddetti**: GLD'ye
(bağımsız, temiz bir altın serisi) karşı düz mumların ima ettiği günlük
getiri r=0,737 korelasyon gösteriyor (normal mumlarda 0,892) ve medyan
mutlak farkı **daha küçük** (%0,175 vs %0,213). **Kapanış gerçek; sadece
open/high/low uydurma** (kapanışın kopyası).

Atmak iki şeyi bozardı: %11 gerçek kapanışı çöpe atmak, ve daha kötüsü
**takvim sürekliliğini sessizce kırmak** — Salı'yı silersen Pazartesi'nin
"ertesi gün getirisi" hiçbir hata vermeden iki günlük getiriye dönüşür.
Bu yüzden `panel.py` işaretliyor (`flat_bar`) ve `indicators.py` yüksek/düşük
tabanlı ölçüler yerine **kapanıştan kapanışa** ölçüleri tercih ediyor
(ATR yerine getiri std sapması, yüksek yerine kapanış Donchian'ı).

### Seansın bitip bitmediğini Yahoo'nun damgası söylemez

`fetch_data.bar_is_complete` / `drop_forming_bar` — **tek** uygulama,
`predict.load_panel` ve `research/panel.py` ikisi de onu çağırır.

Eski kural mumun damga **şeklini** okuyordu: "04:00 UTC'de temiz bir açılış
damgası varsa seans bitmiştir". Yanlıştı ve **iki yönde birden** yanlıştı.
2026-09-08 07:58 UTC'de ölçüldü: yarısı işlenmiş 2026-09-08 seansı tam da
04:00:00 damgasıyla geliyordu — yani kapanmış bir mumdan ayırt edilemez.
Guard var olduğu şeyi hiç yapmıyordu. Ters yönde de: Yahoo bazen gerçekten
bitmiş bir yarım seansı duvar saatiyle damgalıyor (2025-11-28, Şükran Günü
ertesi, 14:30 UTC) ve eski kural o **gerçek** seansı atıyordu.

Doğru kural mumun kendi takvim gününü borsanın saatine karşı okur: D günlük
mum, New York saatiyle D 17:00'ı geçince kesindir. Bu DST'yi kendiliğinden
halleder — kapanış yazın 21:00 UTC, kışın 22:00 UTC.

Neden önemli: yarım mumdan tahmin üretmek iki yerden birden sızdırır —
özellikler henüz olmamış bir seansı anlatır, **ve** `target_date` kapanmamış
bir seanstan hesaplanır, yani satır bir gün erken düşer; ertesi günün cron'u
da onu `unique(asset, target_date)` yüzünden çift sanıp atlar. `predict.py`
23:00 UTC'de (19:00 New York) çalıştığı için cron yolu zaten doğruydu; kural
elle tetiklenen her koşuyu düzeltiyor. `tests/test_data_hygiene.py` kilitliyor.

### Kalibratör kendi çıktısına fit edilemez

`predictions` tablosunda `tech_confidence_raw` / `ml_confidence_raw` /
`macro_confidence_raw` var ve `retrain.refit_calibrators` **yalnızca**
onları okur.

Hata şuydu: `predict.py` güveni kalibre ettikten **sonra** yazıyordu,
`retrain.py` ise aynı kolonu geri okuyup ona yeni bir eğri fit ediyordu.
İlk eğri oluştuktan sonra her gece bir önceki gecenin **çıktısına** fit
edilmiş bir eğri üretilecek, sonra o eğri **ham** girdiye uygulanacaktı.
İki farklı ölçek, hiçbir hata mesajı, her gece biraz daha bükülen pozisyon
boyutu. Henüz patlamamış olmasının tek sebebi
`calibration.MIN_RECORDS_TO_FIT`'in (180 çözülmüş satır) daha dolmamış
olmasıydı — yani ilk fit'ten **önce** düzeltilmesi gereken cinsten bir hata.

Eski satırlar (ham kolon yokken yazılanlar) fit'e **katılmıyor**, ikame
edilmiyor: karışık ölçekli bir örneklem, küçük bir örneklemden kötüdür.

`predict.insert_prediction` bu migration uygulanmamışsa satırı kolonsuz
yazıp yüksek sesle uyarır. Sebebi: PostgREST bilinmeyen bir anahtar için
**tüm** insert'i reddeder, ve `unique(asset, target_date)` yüzünden kaçan
gün bir daha geri gelmez.

### Öncü sürücüler gerçek, ama kontrol serisi olmadan kanıtlanamaz

`research/drivers.py` 16 seriyi iki kez ölçtü: aynı gün (açıklar, alınamaz)
ve ertesi gün (öncü, alınabilir). Üçü Bonferroni eşiğini geçti: `tip`
(t=+6,63), `ief` (t=+5,18), `vix` (t=−5,42).

TIP'in ertesi gün r=+0,088'i bir günlük tahmin için **fazla büyük** ve
şüpheliydi. Doğal şüphe takvim kaymasıydı: altın seansı 17:00 New York'ta,
tahvil ETF'leri 16:00'da kapanıyor, Yahoo altın mumunu 04:00 UTC'de
damgalıyor. Birleştirme bir gün kaysa, **eşzamanlı** bir ilişki
**öngörücü** diye etiketlenir ve harika görünür.

`research/lags.py` bunu öldürmek için yazıldı ve kontrol serisi kesin cevabı
verdi: **gümüş aynı gün r=+0,783, ertesi gün r=−0,016.** Devasa bir
eşzamanlı ilişki tek başına lag+1 kuyruğu üretmiyor. Hizalama doğru, TIP'in
kuyruğu gerçek. `dxy` ve `us10y` de tepe lag 0'da.

**VIX'in işareti hikâyenin tersi ve bu bilerek böyle**: VIX sıçraması ertesi
gün altın için **kötü**, aynı gün ilişkisi ise sıfır. Standart açıklama
zorunlu likidasyon. `indicators._score_vix` negatif işaretli; "güvenli
liman" sezgisiyle düzeltmeye kalkma, ölçüm bunu söylüyor.

### Ölçek sabitleri tahmin edilmez, ölçülür

`indicators.py`'deki yedi skorlayıcının hepsi bir ham büyüklüğü −1..1'e
sıkıştırıyor. İlk sürümde sabitler tahmindi ve ikisi sürekli kırpılıyordu:
**macd oturumların %44,9'unda, real_yield %49,1'inde doyuyordu** (medyan
|skor| 0,881 ve 0,976). Yarı zamanda ±1'e sabitlenmiş bir skor ölçüm değil
yazı-turadır; harmanın tartması gereken derecelendirmeyi yok eder.

Sabitler artık 25 yıllık panelde ölçülüp **90. yüzdelik ~1,0'e gelecek**
şekilde ayarlı (doyma %5,7-13,7, medyan |skor| 0,30-0,53).

`real_yield_chg`'de ayrıca bir **birim tutarsızlığı** vardı: `us10y.diff(5)`
puan cinsinden, `100 × breakeven_chg` ise ETF fiyat oranı. Bir tahvil fiyat
hareketini getiri hareketine çevirmek **süreye bölmek** demektir; TIP ve IEF
ikisi de ~7,5 yıl. Düz 100 ile çarpmak breakeven terimini 7,5x şişiriyordu
(ölçülen medyan büyüklük 0,321 vs tahvil teriminin 0,075) — yani "reel faiz
değişimi" aslında reel faizin değil, 4 kat baskın bir ETF oranının
değişimiydi. `BOND_ETF_DURATION_YEARS` bunun için var.

**Düzeltme yeni bir hata doğurdu ve o da ders**: süre düzeltmesi büyüklüğü
7,5x küçültünce eski bölen (6,0) terimi tamamen susturdu — medyan |skor|
0,009. Ağırlıklı bir bileşen sessizce hiçbir şey yapmıyordu. Bir ölçeği
değiştirdiğinde **doyma oranını VE medyan skoru birlikte** kontrol et; biri
tek başına yanıltıcı.

**Aynı terim üçüncü kez düzeltildi ve bu sefer pencere yanlıştı.**
`research/realrate.py`: reel faizin **1 günlük** değişimi ertesi gün
Bonferroni eşiğini her iki metalde de geçiyor (altın t=−4,74, gümüş
t=−3,65), üretimdeki **5 günlük** hâli hiçbirinde geçmiyor (t=−2,06,
t=−2,74). Bu projedeki ölçülmüş her öncü sürücü 1 günlük değişimdir
(`tip_chg`, `ief_chg`, `vix_chg`); `real_yield_chg` 5 gün üzerine kurulu
**tek** terimdi. `_score_real_yield` artık `real_yield_chg1`'i okuyor ve
`REAL_YIELD_SCALE` 0,17 → **0,078**.

İki incelik:
- **Kolonun adı korunup değeri değiştirilmedi.** `real_yield_chg` (5 gün)
  `ml_model.FEATURE_COLUMNS` içinde aynen duruyor; yeni pencere ayrı bir
  kolon. Adı koruyup değeri değiştirmek, `predict.py`'nin isim kontrolünün
  göremeyeceği **tek** özellik değişikliği türüdür — her kayıtlı model
  farklı dağılımlı bir kolonu hatasız puanlamaya devam ederdi.
- **Bedeli backtest'le ölçüldü ve gizlenmiyor:** Calmar farkı gürültü içinde
  (`technical` ortalama −0,003), ama **işlem sayısı neredeyse ikiye katlandı**
  (altın 377 → 659). 150 bp'de altın `technical` Calmar 0,20 → 0,18. Yine de
  değiştirildi, çünkü alternatif ölçülmüş içeriği olmayan bir terimi sırf
  sessiz olduğu için tutmaktı.

### Sinyal eğimi iki yönlü olmalı

`trading.SIGNAL_BASE_EXPOSURE = MAX_EXPOSURE - MAX_SIGNAL_TILT` (0,85).
Tavandan başlarsan yükseliş eğimi kırpılıp yok olur, düşüş eğimi ise hâlâ
keser — yani her sinyal portföyü, ne söylerse söylesin, sadece kesebilen
bir makineye dönüşür. İlk sürüm tam bunu yapıyordu:
`technical`/`ml`/`macro`/`claude` hepsi %100 pozisyon basıyordu.
`test_trading.test_signal_tilt_is_two_sided` bunu kilitliyor.

### Sert çıkış düşüşü artırır

`trading.TREND_OFF_EXPOSURE = 0.35`, sıfır değil. `research/defense.py`'de
düşüş-stopu varyantları maksimum düşüşü **kötüleştirdi** (%55,3 vs
al-ve-tut'un %44,4'ü): dipte satıp yukarıda geri alıyorlar. Kısmen yatırımda
kalmak toparlanmayı korur. XRP-Guess'in `STOP_LOSS_COOLDOWN_CANDLES`
dersinin (236 stop-loss'un 235'i 10 saat içinde tekrar tetikleniyordu) aynı
ailesi.

### Backtest üretim kodunu oynatır, kopyasını değil

`backtest.py` doğrudan `trading.compute_target_exposure()` ve
`compute_rebalance()` çağırır. `research/edge.py` `ml_model.build_estimator()`
çağırır. Stratejiyi yeniden yazan bir backtest, yeniden yazımı test eder.

Bu gerçek bir hatayı yakaladı: backtest sinyal yoluna `vol_20d` besliyordu
ama `trading.VOL_LOOKBACK_DAYS` 60. Yani canlıdan **farklı, daha gürültülü**
bir strateji test ediliyordu — kolon adının içine saklanmış bir sapma.
Düzeltince `voltarget` 440 işlemden **158'e** düştü ve Calmar 0,22→0,24.

### Maliyet tek bir sayı değil

`backtest.py` dört senaryoyu birden basar (2/10/40/150 bp gidiş-dönüş).
Fark belirleyici: ETF maliyetinde `voltarget`, `technical`, `ml` ve `macro`
al-ve-tut'u Calmar'da geçiyor; **banka gram altın maliyetinde (150 bp)
hiçbiri geçmiyor.** `macro` bileşeni bunun en net örneği — 19,5 yılda 2288
işlem yapıyor, 2 bp'de Calmar 0,27 (al-ve-tut 0,23), 150 bp'de 0,03.
Gerçek bir sinyal, üzerine para koymanın pahalı olduğu bir sinyal.

### Claude bileşeni backtest edilemez

6000 günlük geçmişi ücretli bir LLM çağrısıyla tekrar oynatmak hem pahalı
hem anlamsız (model o tarihleri zaten biliyor). Canlı-only. Bu sınır
`backtest.py`'nin raporunda açıkça basılıyor.

Model `claude_signal.MODEL`'de sabit (`claude-opus-5`). XRP-Guess maliyet
gerekçesiyle daha küçük bir model seçmişti; **o gerekçe burada geçerli
değil** çünkü orası günde 96, burası günde 1 çağrı yapıyor.

**Prompt dersi devralındı**: XRP-Guess'in sistem prompt'u "teknik sinyalin
yönünü tekrarlama" diyordu; niyeti papağanlığı önlemekti ama modeli
*ayrışmaya* itiyordu ve `technical` ölçülen avantajı olan tek bileşendi.
Canlı veri tutarlıydı: ilk 73 satırda %48 hemfikir, 73'ün 56'sında DOWN,
%37 isabet. Buradaki prompt açıkça "hemfikir olmak gayet iyi bir cevaptır"
diyor. **Ayrıca taban oranı prompt'ta söylüyor** — yoksa model 50/50'yi
nötr sanır ve "UP"ı bilgi taşımaz.

### Haber bileşeni: iki ders devralındı, sözlük yeniden yazıldı

XRP-Guess'in `news_signal.py`'si iki kez hata yaptı: (a) substring eşleşmesi
(`ban` → `banking` içinde yakalanıyordu), (b) skorun başlık **hacmiyle**
ölçeklenmesi. Her ikisinin düzeltmesi de burada: kelime-sınırı eşleşmesi,
**başlık başına tek oy**, toplam eşleşen ağırlığa normalize, ve belirgin
eğim yoksa **abstain**.

Ama sözlük tamamen farklı, çünkü **altın haberlerinin anlamı tonundan
bağımsız**: "Fed faiz indirdi" kulağa kötü gelir, altın için olumludur;
"güçlü istihdam verisi" kulağa iyi gelir, altın için olumsuzdur. Listeler
**altına etkiye** göre düzenlenmiştir, tona göre değil. Düz bir duygu
analizi bunların birkaçını ters okur.

Canlı doğrulama (2026-09-07): "Gold eases as strong US jobs data boosts Fed
rate-hike bets" başlığını doğru şekilde DÜŞÜŞ olarak okudu.

### Kanal Finans TŞ: bir insanın görüşü, bizim tahminimiz değil

**2026-09-08'de ikiye bölündü ve bunu anlamak önemli.** Bu bölümün geri
kalanı hâlâ geçerli (görüşün ne olduğu, direnç kuralı, zarar-kes yönü, seviye
korunumu) ama **YouTube'a giden kısım artık bu repoda değil.**

**Neden bölündü**: XAU-Guess ve XRP-Guess, aynı YouTube kanalını, aynı
makineden (aynı IP'den), her 15 dakikada bir **bağımsız** olarak izliyordu.
Aynı videonun transkripti YouTube'dan iki proje için ayrı ayrı, yani iki kez
çekiliyordu — aralıklı olarak bizi zaten engelleyen bir uç noktaya karşı
gereksiz bir ikiye katlama. Ölçüldü (2026-09-08): bu proje `kanal_finans_videos`
tablosunda **sıfır** başarılı satırla dururken, XRP-Guess'in 23 başarılı satırı
vardı, en sonuncusu bir gün önceden — yani engel kalıcı değil, aralıklı, ve iki
projenin toplam isteğini ikiye katlamak onu daha sık/uzun engele çeviriyor
olabilir (kesin nedensellik iddia edilemez, ama zamanlama örtüşüyor).

**Yeni bölünme**:

- **`../Kanal-Finans-Fetcher/fetcher.py`** (sibling repo, XRP-Guess'le
  PAYLAŞILAN) — RSS'i **bir kez** okur, her videonun transkriptini **bir kez**
  çeker, sonra **iki ayrı** Claude çağrısıyla (bu projenin ALTIN/GUMUS/GENEL +
  tema şeması, XRP-Guess'in XRP/BTC/ETH/KRIPTO şeması — gerçekten farklı
  sorular, birleştirilecek ortak bir şema yok) her iki projenin **kendi**
  Supabase'ine yazar. Her 30 dakikada bir çalışır. Geri çekilme artık **tek
  ve gerçekten paylaşılan** bir sayaç (`state/backoff.json`, yerel dosya,
  Supabase'de değil) — eskiden iki proje aynı videonun geri çekilmesini
  birbirinden bağımsız sayıyordu, yani her ikisinin toplamı tek bir paylaşılan
  sayaçtan daha sık deniyordu.
- **`backend/kanal_finans.py`** (burada, değişti) — artık YouTube'a **hiç**
  gitmiyor. Tek işi: fetcher'ın yazdığı `kanal_finans_mentions` satırlarından
  `applied_at is null` olanları okuyup portföye uygulamak. Bu yüzden **eski
  15 dakikalık takviminde kalabildi** — hatta öncesinden daha duyarlı oldu,
  çünkü artık bloklanabilen bir transkript çekişinin arkasında beklemiyor.

`mentions` (varlık başına ALTIN/GUMUS/GENEL görüş, duruş, al/tut/sat, ons
hedefi/zarar-kes/direnç) ve `themes` (SAVAS, ABD_POLITIKA, REZERV, DOLAR,
ENFLASYON, ARZ_TALEP, BORSA, TURKIYE — **bilerek işlem üretmez**, çıplak bir
"yükseliş"in bağlamla okunabilmesi için var) hâlâ aynı iki şey; sadece
**kim çıkardığı** değişti (fetcher), **kim uyguladığı** değişmedi
(`kanal_finans_trading.py`, dokunulmadı).

Tema sözlüğü **sabit ve küçük** tutuldu: açık uçlu bir "neden bahsetti"
alanı her videoda farklı bir taksonomi üretir ve zaman içinde hiçbir şey
sayılamaz.

**`ensemble.COMPONENTS`'e eklenmedi ve `predict.py` bu modülü hiç çağırmıyor.**
Burada bir tahmin üretmiyoruz, birinin ne dediğini raporluyoruz. Frontend'de
bu netleşsin diye modelin İngilizce "YÜKSELİŞ/DÜŞÜŞ" etiketlerinden bilerek
farklı, Türkçe "Olumlu/Olumsuz/Nötr" rozetleri kullanılıyor.

**Bir video ancak transkript VE o projenin Claude çıkarımı ikisi de başarılı
olunca** `kanal_finans_videos`'a yazılır (artık fetcher'da). Herhangi bir adım
başarısız olursa video hiç yazılmaz ve bir sonraki koşuda otomatik tekrar
denenir — takılan bir video geciker, kaybolmaz. Bir projenin çıkarımı
başarısız olup diğerininki başarılı olursa (nadir — Claude ayrı bir kaynak,
YouTube gibi bloklanmıyor), transkript zaten elde olduğu için o video bir
dahaki YouTube çekişini beklemeden **aynı koşuda** her iki proje için de
denenir; sadece başarısız kalan taraf bir sonraki koşuda YouTube'a yeniden
gitmeyi gerektirir.

**Direnç seviyesi bilerek otomatik satış tetiklemez.** XRP-Guess canlı
veride konuşmacının direnç kırılmasını bazen *alım fırsatı* olarak
yorumladığını gördü; sabit "direnç = kar al" kuralı tam da en spesifik
olduğu videolarda onu ters okurdu. Sadece zarar-kes otomatik tetikler, ve
`predict.py`'nin her günlük döngüsünde **sürekli** izlenir — bu çağrı
YouTube'a hiç gitmediği için Actions'ta sorunsuz çalışır.

**Zarar-kes/direnç prompt'undaki "hangi uç" kuralı ters yönlerdir ve
açıkça yazılmıştır**: zarar-keste EN YÜKSEK (fiyat düşerken oraya önce
değer), dirençte EN DÜŞÜK. XRP-Guess'te sadece "daha temkinli ucu al"
denmişti ve model karıştırdı — gerçek bir pozisyonda ~%1,8 fazla zarar.

**Yeni bir mention seviye vermezse önceki korunur.** Konuşmacı her videoda
seviyeyi tekrar etmiyor; "eksik = değişmedi", "eksik = iptal" değil. Tersi
her tekrar etmediği videoda zarar-kesi sessizce devre dışı bırakırdı.

### Günlük mail: sayfayla aynı kuralları söylemek zorunda

`daily_report.py` XRP-Guess'ten devralındı ama üç yeri **ölçüm yüzünden**
farklı, ve üçü de bu projenin merkezî bulgusundan geliyor:

1. **Başlık sayısı `edge_over_base`, isabet değil.** "YÜKSELİŞ, %62 güven"
   ile açılan bir mail sistemi her sabah abartır — güven, prior yüksekken
   zaten yüksektir. Ve en kötü hâl ayrı bir cümle alıyor: p_up 0,5'in üstünde
   ama taban oranın altındaysa model yükseliş der ve hiçbir şey yapmamaktan
   daha az iyimserdir. `frontend/app.js` ile **aynı üç durum**, aynı eşikler.
2. **`buyhold` kendi sütununda.** XRP-Guess'in maili stratejileri birbirine
   göre sıralayıp "bugün en çok kazanan"ı basıyordu — bu sessizce daha kolay
   bir soruyu cevaplar. Burada her portföy al-ve-tut'a karşı raporlanıyor ve
   **"HİÇBİRİ"** basılabilir, beklenen bir cevap.
3. **Hüküm için örneklem şartı var.** XRP günde 96 satır çözüyordu; bu, metal
   başına günde bir tane, üstelik 5 gün sonra. `MIN_ROWS_FOR_VERDICT = 60`
   arayüzdeki sabitin aynısı — sayfa ile mailin "model çalışıyor mu"da
   ayrışması ikisinden de kötü olurdu.

**Değerleme yine VADELİ fiyatla** (`fetch_data.get_live_price` → GC=F/SI=F),
spotla değil; `trades`'teki her dolum vadeli fiyattan gerçekleşti.

**İki farklı referanslı yüzde yan yana basılamaz.** İlk sürüm "Giriş
$4.395,90 / Şu an $4.442,50 (−%0,76)" yazıyordu: yüzde girişe göre değil, 24
saat öncesine göreydi ve bir yükseliş düşüş gibi okunuyordu. Pencerenin
başındaki fiyat normal bir sabah **bir önceki** seansın tahminidir (gecenin
tahmini pencere kapandıktan sonra yazılır), yani gerçekten başka bir fiyat.
Artık ikisi de kendi referansıyla ayrı satırda.

Mail **hiçbir şey yazmıyor** (workflow `contents: read`) ve `GMAIL_ADDRESS`
yoksa raporu basıp 0 ile çıkıyor — yani `python daily_report.py` yerel
önizleme olarak da kullanılabiliyor, eksik bir isteğe bağlı secret bozuk bir
boru hattı gibi görünmüyor.

### Abstain bir hata değil

Bir bileşen `confidence=0` döndürdüğünde o tur konuşmuyor demektir.
`predict.resolve_due_predictions` bu satırları `NULL` olarak puanlıyor,
**yanlış olarak değil**, ve `retrain.py` sicile katmıyor. `macro_signal` ve
`news_signal` çoğu zaman sessiz kalacak şekilde tasarlandı; bu doğru
davranış.

### Tahmin satırları idempotent

`predictions` tablosunda `unique(symbol, target_date)` var ve `predict.py`
pahalı hiçbir işe girmeden önce kontrol ediyor. Elle tetiklenen bir koşu
cron'la çakışsaydı aynı seans için iki satır yazılır, bileşen sicilleri çift
sayar ve dokuz portföyün `maybe_trade()`'i iki kez ateşlenirdi.

---

### Arayüz: renk varlığı taşır, ve etiketler ölçülmüş şeyi söylemeli

Sayfanın büyük kısmı **tek metal** gösterir (tahmin, piyasa durumu, bileşenler,
portföyler, sicil) ama sekme şeridi ve anlık fiyat kartları **ikisini birden**
gösterir. Metal rengi bu yüzden dekorasyon değil: altının $4.476'sı ile gümüşün
$66'sı karıştırılamaz, ama "%17 pozisyon" ile "+%2,4" karıştırılabilir — ve
sayfadaki sayıların çoğu bu türden.

- `#app[data-asset]` `--metal*` değişkenlerini yeniden bağlar; `.card.asset-scoped`
  taşıyan her bölüm onu okur. `renderAll()` sekme değişiminde `dataset.asset`'i
  yazar.
- **Anlık fiyat kartları sekmeyi TAKİP ETMEZ.** İkisi aynı anda ekranda olduğu
  için her biri `.metal-gold` / `.metal-silver` ile kendi paletini sabitler.
- Gümüş bilerek soğuk/mavimsidir. Nötr gri bu sıcak zeminde "devre dışı" gibi
  okunur, ikinci bir metal gibi değil.

**"Geçmiş Tahminler" başlığı yanlıştı ve bu bir etiket hatasından fazlasıydı.**
Tablodaki en yeni satır normalde hâlâ AÇIKTIR — hedef seansı gelmemiştir — yani
"geçmiş" başlığı altında **gelecek** bir tarih duruyordu (7 Eylül'de verilen
tahminin hedefi 11 Eylül). Panel artık `Tahmin Sicili`, satırlar hem **verildiği**
hem **hedef** tarihi taşıyor ve açık satırlar `tr.pending` ile boyanıyor. Çözülmüş
tahmin yokken özet bunun bir arıza değil, 5 günlük ufkun doğal sonucu olduğunu
söylüyor.

**Yön etiketi tek başına yanıltır ve en kötü hâli "YÜKSELİŞ + negatif fark".**
p_up 0,5'in üstünde ama taban oranın altındaysa model yükseliş der ve yine de
hiçbir şey yapmamaktan daha az iyimserdir (canlı örnek: gümüş p_up=0,514,
taban 0,539). `renderPrediction` bu durumu ayrı bir cümleyle yazıyor: "bu bir
alım sinyali değildir". Üç durum ayrı ele alınıyor — |fark| < 1 puan (sessiz),
YÜKSELİŞ + negatif fark (yukarıdaki), ve geri kalan.

**Arayüz `trading.REBALANCE_THRESHOLD`'u aynalıyor ve bu ayna ölçülerek
doğrulandı.** Portföy kutularındaki "sonraki işlem" satırı `compute_rebalance`
ile aynı kararı vermeli; beş sınır durumunda (tam hedefte / eşik altı / alım /
satım / nakitsiz) ikisi birebir aynı çıktı verdi. Eşiği bir tarafta değiştirip
diğerini unutmak, ekranda "ALACAK" yazarken hiçbir şey yapmayan bir sayfa üretir.
`kanalfinans` bu kuralın DIŞINDADIR — o hedef pozisyona göre değil, ayrık
AL/SAT ile çalışır (`kanal_finans_trading.decide_on_mention`), o yüzden kendi
metnini alır.

**Bileşen sicili ve işlem defteri ekranda — ikisi de zaten vardı, sadece
görünmüyordu.** `model_state`'in dört sayacı (UP çağrı/doğru, DOWN çağrı/doğru)
yalnızca `retrain.py`'nin gece konsolunda basılıyordu, yani kimsenin bakmadığı
yerde; oysa bu dosyanın kendi ifadesiyle "121 çağrının 121'i UP diyen bir
bileşen sinyal değil sabittir" ve bunu bir etki yüzdesinden göremezsiniz.
Tablo **ham sayaçları** ve her tarafın geçmesi gereken **bilgisizlik oranını**
(UP için taban, DOWN için 1−taban) gösteriyor; log-odds aritmetiği **bilerek**
JS'e kopyalanmadı — havuzlanmış sonucun zaten bir sütunu var ("Etki") ve bir
karar kuralını iki yerde tutmak `backtest.py`'nin var olma sebebinin tam tersi.

İşlem defteri bedava: `trades` ortalama maliyet için zaten sayfalanarak
**tamamen** indiriliyordu ve o hesaptan sonra atılıyordu. Cevapladığı soru
başka hiçbir panelde yok — "sistem son zamanlarda gerçekten bir şey yaptı mı".
Bir portföy kartı, pozisyonu dün de üç hafta önce de ayarlanmış olsa aynı
görünür.

**Sicil özeti artık örneklem küçükken hüküm vermiyor.** "Model hep-YÜKSELİŞ
demekten iyi" cümlesi 8 satırın üzerine basıldığında bir ölçüm değil bir yazı
turadır. Eşik 60 çözülmüş satır (~bir çeyrek), ve iki oran arasındaki fark
2 puandan küçükse "ayırt edilebilir değil" yazıyor. Aynı disiplin:
`research/ablation.py` negatif sonucun yanına testin gücünü yazıyor.

Ayrıca: `cold_start` kolonu 2026-09-08 migration'ından **önce** yazılmış
satırlarda NULL'dur ve o satırlar tanım gereği sicilin en eskisi, yani tam da
soğuk başlangıç dönemidir. Bu yüzden uyarı `row.cold_start !== false` ile
gösteriliyor — NULL'u "soğuk başlangıç değil" saymak, uyarıyı en çok ihtiyaç
duyan satırlarda susturur.

---

### Portföy değerlemesi SPOT değil VADELİ fiyatla yapılır

Sayfa iki ayrı fiyat serisi çeker ve yanlış işe yanlış seriyi vermek sessiz
bir ~%1 hatadır:

| Seri | Ne | Tazelik | Nerede kullanılır |
|---|---|---|---|
| `TVC:GOLD` / `TVC:SILVER` | spot | `streaming` (gerçek zamanlı), 7/24 | Anlık Fiyatlar kartları |
| `COMEX:GC1!` / `COMEX:SI1!` | ön vade vadeli | `delayed_streaming_600` (**10 dk gecikmeli**) | **portföy değerlemesi** |

2026-09-08'de ölçüldü: kayıtlı kapanış 4476,60 · GC1! 4442,30 (−%0,77) ·
TVC spot 4397,34 (−%1,77). Portföyleri **spotla** değerlemek her birine anında
~%1 zarar yazardı — ve bu zararı hiçbir piyasa hareketi üretmemiştir. Vadeli–spot
bazıdır (finansman + depolama), yani **birim değişimi**nin değer değişimi gibi
görünmesidir. Backend GC=F ile işlem yapıyor, `trades`'teki her dolum vadeli
fiyattan gerçekleşti ve gelecek her işlem de öyle olacak; değerleme de aynı
seride kalmalı. 10 dakikalık gecikme bunun bedelidir ve ekranda yazılıdır.

**`fetchTradingView` vadeli gelmezse spota DÜŞMEZ**, kayıtlı COMEX kapanışını
kullanır ve "canlı vadeli alınamadı" der. Buradaki cazip hata "elimizde spot
var, onu kullanalım"dır; test edildi ve $1000 yerine $983 gösteriyor.

`delayed` bayrağı yalnızca **spot** tickerlarından hesaplanır. Vadeli bacaklar
tanım gereği hep gecikmelidir; onları da hesaba katmak gerçek zamanlı spot
kartlarını kalıcı olarak "gecikmeli" damgalar ve rozeti işe yaramaz hâle
getirir.

### İki döngü: fiyatlar 2 sn, Supabase 5 dk

`refreshPrices` (5 sn) ve `loadData` (5 dk) ayrıdır. Supabase günde bir satır
üretiyor; onu saniyede bir çekmek aynı baytları tekrar indirmektir. Gün içinde
gerçekten kıpırdayan tek şey fiyattır — ve fiyat kıpırdayınca portföy değeri,
ima ettiği pozisyon ve dolayısıyla "sonraki işlem" satırı da kıpırdar, o yüzden
üçü aynı tikte yeniden çizilir.

**Ne kadar hızlı çekmeye değdiği ölçüldü (2026-09-08), tahmin edilmedi.**
Tarayıcının gördüğü uç nokta saniyelik bir akış değil; ~1 sn aralıkla 109
saniye örneklendiğinde her seri **11-22 saniyede bir** yeni değer üretiyor:

| Seri | Tik | Ortalama aralık |
|---|---|---|
| `TVC:GOLD` | 8 | 13,7 sn |
| `TVC:SILVER` | 10 | 10,9 sn |
| `COMEX:GC1!` | 5 | 21,9 sn |
| `FX_IDC:USDTRY` | 9 | 12,1 sn |

1 sn, 2 sn ve 5 sn'de **aynı** değer kümesine ulaşılıyor: her değer poll
aralığından çok daha uzun süre ekranda kaldığı için 5 sn zaten hiçbir tiki
kaçırmıyor. Yani hızlandırmak **bilgi değil gecikme** satın alır. 2 sn yine de
seçildi çünkü sayfanın "canlı" hissi bu gecikmedir — ama bedeli 2,5 kat istekle
değil, **Binance'i her turdan çıkararak** ödendi (`BINANCE_REFRESH_MS` 30 sn):

| | TradingView | Binance | Toplam |
|---|---|---|---|
| eski (5 sn, her turda Binance) | 720/sa | 1440/sa | 2160/sa |
| yeni (2 sn, Binance 30 sn'de) | 1800/sa | 240/sa | **2100/sa** |

Toplam yük düştü ama **TradingView'ün payı 2,5 katına çıktı** ve belgelenmemiş
uç nokta odur; gerekirse geri alınacak sayı `PRICE_REFRESH_MS`'tir.

**"TradingView düştü, yedeği hemen çek" dalı bir hataydı ve simülasyon yakaladı.**
`!binanceDue` zaten "önbellek 30 sn'den taze" demektir, dolayısıyla çekilecek
daha tazesi yoktur — ve kesinti tam da bu koşulun *her turda* sağlandığı andır.
Geri çekilme de devreye girmez, çünkü Binance cevap vermeye devam ediyordur.
Ölçülen: 60 saniyelik sahte kesintide Binance 240/sa yerine **3720/sa**. İlk tur
için de özel duruma gerek yok: `binanceFetchedAt` 0 başlar, yani ilk turda
zaten çekilir.

**Durağan bir sayı ile donmuş bir sayfa ayırt edilebilmeli.** USDTRY dakikada
~%0,004 oynuyor ve ~12 saniyede bir güncelleniyor, yani doğru çalışan bir sayfa
pariteyi çoğu zaman **değişmeden** gösterir. Bu yüzden not satırı hem son
kontrol saatini hem parite en son ne zaman *gerçekten değiştiğini* basıyor;
ikisi olmadan kullanıcı haklı olarak "takıldı" diye okur.

İki koruma var ve ikisi de bilinçli:
- **Gizli sekme istek atmaz** (`document.hidden`). Unutulmuş bir arka plan
  sekmesinin belgelenmemiş bir uç noktaya saatte 720 istek atmasını engeller.
  Sekmeye dönüldüğünde anında tazelenir.
- **Hata geometrik geri çekilir** (5→10→20→40→60 sn, tavan 60). Bu nezaket
  değil: `kanal_finans.RETRY_SCHEDULE`'ın backend'de kaydettiği dersin aynısı —
  bizi zaten reddeden bir uç noktayı dövmek, geçici engeli kalıcıya çevirmenin
  en garanti yoludur. İlk başarı sayacı sıfırlar.

### "Aldığı fiyat" ile "kâr/zarar" aynı sayı değildir ve fark komisyondur

`costBasisByStrategy` `trades`'i baştan oynatır ve **ortalama maliyet yöntemi**
kullanır: alış kendi fiyatından ons ekler, satış koşan ortalamadan ons düşer ve
ortalamayı değiştirmez. FIFO başka bir soruyu cevaplar ve oynaklık hedefli
portföyler kısmi satış yaptığı anda ayrışır.

Kutuda iki yüzde var ve **birbirini tutmaması doğrudur**:
- `o günden bu yana` = güncel fiyat / ortalama alış fiyatı − 1 (saf **fiyat**
  hareketi)
- üstteki büyük yüzde = gerçek kâr/zarar, **komisyon dahil**

Canlı doğrulama (2026-09-08): altında fark tam 5,0 bp, gümüşte tam 10,0 bp —
`assets.py`'deki `fee_rate` değerleriyle birebir. Gümüşte fiyat +%0,03 iken
portföy −%0,07'dir; aradaki tek şey komisyondur. Tek bir yüzde göstermek bu
ikisini karıştırır.

`trades` sınırsız büyür, o yüzden `apiAll` ile **sayfalanarak** çekilir.
Supabase ~1000 satırda sessizce keser; kesilmiş bir işlem defterinden hesaplanan
ortalama maliyet eksik değil, **yanlış** olurdu.

### Anlık fiyat kartları: gün oku KALICI, tik parlaması ANLIK

İkisi aynı görsel dilin (yeşil/kırmızı) iki ayrı iddiasıdır ve karıştırılmamalı:

- **Ok** = bugünkü fiyat, **TradingView'ün kendi günlük mumunun açılışına**
  göre yukarıda mı aşağıda mı. Bilerek önceki kapanışa göre değil — daha
  yaygın kural o olsa da istenen bu değildi, ve sessizce değiştirmedim.
  `columns` isteğine üçüncü alan olarak `"open"` eklendi (`readOpen`, hücre
  indeksi 2); gerçek veriyle doğrulandı: `TVC:GOLD` `[4398.66, "streaming",
  4409.76]` gibi dönüyor.
- **Parlama** = ekrandaki sayı **bir önceki tike göre** değişti mi, hangi
  yöne. Güne göre yukarıda olan bir metal tek bir tikte aşağı gidebilir —
  ikisi bağımsız ölçülüyor ve test edilirken de gerçekten ayrıştılar.

**Hiçbir yedek kaynağın (Binance) güvenilir bir "bugünkü açılışı" yok** —
Binance'in 24 saatlik ticker'ı kayan bir pencere, takvim günü değil, farklı
bir şeye aynı adı takmak olurdu. Bu yüzden TradingView düştüğünde ok da
kayboluyor, sessizce yanlış bir sayıya geçmiyor. Aynı şekilde günlük değişim
ekranda görünecek hassasiyette değilse (±%0,005 altı) ok basılmıyor — göremediği
bir büyüklüğü iddia eden bir okun kendisi abartıdır.

**Parlama, ham float değil GÖRÜNEN (yuvarlanmış) değere göre tetikleniyor.**
Besleme bazen ekranda hiç görünmeyen bir ondalıkta titrer; ham değere göre
tetiklemek okuyucunun göremediği bir "değişikliği" parlatırdı. `lastPaintedPrice`
son basılan yuvarlanmış string'i tutuyor, ilk boyamada `null` olduğu için ilk
tik hiç parlamıyor.

**CSS animasyonu yeniden tetiklemek için hile gerekmedi.** `renderLivePrices`
tüm `#live-prices` innerHTML'ini her 2 saniyede baştan kuruyor — yani değişen
ya da değişmeyen fark etmeksizin her kart zaten yepyeni bir DOM düğümü. Fark
sadece şurada: sınıf (`flash-up`/`flash-down`) yalnızca değişim varsa markup'a
giriyor. Değişmeyen tikte kart yine yeniden yaratılıyor ama sınıfsız, o yüzden
animasyon oynamıyor — ayrı bir "reflow zorla" veya benzersiz anahtar numarası
gerekmedi, çünkü innerHTML değişimi bunu zaten bedava sağlıyor.

Altı senaryo ile test edildi: ilk boyama (parlama yok), aynı yuvarlanmış değer
(parlama yok), yukarı tik, aşağı tik, açılış verisi eksik (ok yok), eşik altı
günlük değişim (ok yok) — hepsi beklendiği gibi çıktı.

---

## Geliştirme notları

- **Yeni bir varlık eklerken**: `assets.py`'ye giriş ekle, `research/panel.py`
  ile panelini kur, **`research/compare.py`'yi çalıştır** ve çıkan sayıları
  `assets.py`'ye işle. Ölçmeden sabit kopyalama. Ayrıca `supabase/schema.sql`
  içindeki `portfolios` ve `model_state` seed'lerine o varlığı ekle.
- **Testler** (`backend/tests/`, pytest): `cd backend && python -m pytest tests/ -v`.
  Çoğu test bir **ölçümü** kilitliyor — hangi bulguyu koruduğu docstring'inde
  yazılı. Ağ/DB gerektiren hiçbir şey yok, hepsi Actions'ta sırsız koşuyor.
  `test_predict_flow.py` istisna gibi görünür ama değil: `run_asset`'in
  **bağlantılarını** test ediyor, bileşenleri değil — sentetik bir panel ve
  sahte bir Supabase ile. Sebebi, oradaki hata sınıfının başka bekçisi
  olmaması: bir değerin yanlış tüketiciye verilmesi hiçbir istisna üretmez,
  kod incelemesinde doğru okunur ve (kalibrasyon örneğinde) görünür hâle
  gelmesi 180 çözülmüş satır sürer. Canlı sinyal *üreten* kodun testi hâlâ
  yok; o `backtest.py` + canlı izlemeyle doğrulanıyor.
- **Yeni bir strateji fikri gelmeden önce `backend/research/README.md`'yi
  oku.** Orada ölçülüp elenmiş **on bir** hipotez duruyor — oranla ilgili
  bir fikir 8. bölümde, Fed faiziyle ilgili olan 10. bölümde, reel faiz ve
  merkez bankası alımıyla ilgili olan 11. bölümde büyük ihtimalle zaten var.
- **`supabase/schema.sql` değiştiysen migration'ı kullanıcıya ver.** Repo
  kendi migration'ını uygulayamaz. Yeni bir kolon ekliyorsan
  `predict.PENDING_MIGRATION_COLUMNS`'a da ekle: PostgREST bilinmeyen bir
  anahtar için **tüm** insert'i reddeder ve `unique(asset, target_date)`
  yüzünden kaçırılan gün bir daha yazılamaz.
- **Bir özelliği/kolonu çıkarmadan önce eşleştirilmiş test yap.**
  `research/ablation.py` ve `research/ratio.py` bunun nasıl yapıldığını
  gösteriyor: `edge.walk_forward(..., features=..., label_values=...)` tek
  bir şeyi değiştirip aynı satırlarda puanlıyor, McNemar/eşli t farkın
  gürültüyü aşıp aşmadığını söylüyor. Tek bölmede permütasyon önemi
  **yetmez** — bu projede ikisi zaten her iki metalde de çelişti.
- **Negatif bir sonucu yazarken testin gücünü de yaz.** "Hiçbir şey
  geçmedi" ile "test görecek kadar güçlü değildi" zıt işler gerektirir.
  `ablation.min_detectable_ic` bu sayıyı üretiyor.
- Bir parametre değiştirirsen `backtest.py`'ı çalıştırıp etkisini **ölç**.
  Bu projede sezgiyle konmuş sayı yok.
- Supabase REST API varsayılan ~1000 satırla sınırlı döner; geniş sorgularda
  sayfalama gerekir (bkz. `retrain.fetch_resolved`).
- Doğrulama genelde `curl` ile Supabase REST API'sine doğrudan sorgu atarak
  yapılır — kullanıcıdan ekran görüntüsü istemeden önce bunu dene.
- `frontend/sw.js` network-first çalışır; frontend'de büyük bir davranış
  değişikliği yaptıysan `CACHE_NAME`'i artır.
- Git kimliği kullanıcının makinesinde ayarlı (`erdemdelibasi@gmail.com`) —
  Vercel bunu doğrulanmış GitHub e-postasıyla eşleştirip deploy'u
  bloklayabiliyor.
- **Bu repoya bağlı Vercel projesi TEK olmalı: `xau-guess`, kök dizini
  `frontend/`.** 2026-09-08'e kadar ikinci bir proje (`backend`) de bağlıydı
  ve **her push'ta hata maili üretiyordu** — `backend/` saf Python, Vercel'in
  orada sunacağı bir şey yok. Kurulum sırasında kök dizini yanlış seçilmiş
  bir denemeden kalmıştı ve **hiç başarılı olmamıştı**; sonradan silindi.
  Yanıltıcı yanı şu: `xau-guess` her seferinde başarılı olduğu ve site
  güncellendiği için "deploy failed" maili gerçek bir arızayı işaret
  ediyormuş gibi görünüyor, ama site tamamen sağlıklı.

  Teşhisi tahmin ederek değil şuradan yap — Vercel her projenin sonucunu
  GitHub'a commit status'ü olarak yazıyor:

  ```bash
  gh api repos/erdemdelibasi/XAU-Guess/commits/<sha>/status \
    --jq '.statuses[] | "\(.context) | \(.state)"'
  ```

  İki satır dönüyorsa iki proje bağlı demektir. Sadece siteyi açıp "çalışıyor"
  demek yetmez; çalışan projeyi görüp patlayanı kaçırırsın.

## Ton / dil

- Kullanıcıyla iletişim Türkçe; kod/tanımlayıcılar ve kod yorumları İngilizce.
- Uygulama bir yatırım tavsiyesi aracı değildir — bu uyarı README ve UI'da
  görünür kalmalı.
- **Olumsuz sonuçları gizleme.** Bu projenin değeri neyin işe yaramadığını
  dürüstçe ölçmüş olmasında. Bir strateji al-ve-tut'a yeniliyorsa ekranda
  öyle görünmeli.
