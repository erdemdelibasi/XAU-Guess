# Araştırma tezgâhı

Canlı sistemden **tamamen ayrık**. Buradaki hiçbir dosya `predict.py`,
`retrain.py` ya da herhangi bir workflow tarafından çağrılmaz; hiçbiri
Supabase'e yazmaz. Amacı tek: canlı sisteme dokunmadan önce bir hipotezi
ölçüp elemek.

Bu tezgâh XRP-Guess'teki kardeşinden devralındı ve aynı disiplini uygular.
Fark şu: orada tezgâh proje kurulduktan **sonra**, "neden hiçbir şey işe
yaramıyor" sorusuna cevap ararken doğdu. Burada **önce** kuruldu ve altının
mimarisini o belirledi.

## Disiplin

Projenin defalarca öğrendiği kural: **aynı pencerede seçilip aynı pencerede
puanlanan bir sayı hiçbir şey ifade etmez.**

- Pencere zamana göre ikiye bölünür. Parametre **yalnızca ilk yarıda**
  seçilir, o **tek** konfigürasyon ikinci yarıda bir kez çalıştırılır.
  Basılan diğer her şey şeffaflık içindir, sonradan seçim yapmak için değil.
- Sonuç her zaman **maliyet merdiveniyle** basılır (2 / 10 / 40 / 150 bp
  gidiş-dönüş). Ucuz basamak "sinyal var mı", pahalı basamak "normal bir
  aracı kurumu olan biri bunu elinde tutabilir mi" sorusunu ayırır.
- Bu metallerde ek bir ölçüt daha zorunlu: **her sayı hem %50'ye hem
  "hep YUKARI" tabanına karşı** basılır. Altın 5 işlem gününde %55,7,
  gümüş %53,9 ihtimalle yükseliyor; %50'yi geçmek burada hiçbir şey
  kanıtlamaz.

## Dosyalar

| Dosya | Ne yapar |
|---|---|
| `panel.py` | Her metal için 25 yıllık + 14 makro + 8 **aday** serilik günlük panel kurar, `panel_<varlık>.json`'a önbelleğe alır (~1 dk, gitignore'da). Adaylar (`CANDIDATE_SYMBOLS`) canlı yolda **yok** — 12. bölüm |
| `wall.py` | Başabaş duvarı: ufka ve maliyete göre gereken yön isabeti |
| `drivers.py` | 26 serinin eşzamanlı (açıklayan) vs öncü (tahmin eden) etkisi, **her iki metal için**; negatiflerin yanına testin gücünü de basar |
| `lags.py` | Bir "öncü" sürücü gerçekten öncü mü, yoksa takvim kayması mı |
| `edge.py` | Yürüyen-ileri yön testi: 1/5/20 günlük ufuklarda, üç ölçüte karşı |
| `defense.py` | Yön tahmin etmeden düşüşü azaltabilir miyiz (trend + oynaklık kuralları) |
| `tilt.py` | Model yön seçemiyorsa, pozisyon **boyutunu** eğebilir mi |
| `season.py` | Altının takvim etkileri (ay, hafta günü, ay dönümü) |
| `compare.py` | Gümüşü altına karşı ölçer; `assets.py`'deki her sayı buradan gelir |
| `ratio.py` | Altın/gümüş oranı: ortalamaya dönüş, rotasyon, çift tutma, ve `gs_ratio_z`'nin modele katkısı |
| `ablation.py` | ML bileşeni taban orana neden takılıyor — etiket mi, özellikler mi |
| `fedcycle.py` | Fed faiz kararları: olay, rejim ve sürpriz — üçü ayrı ayrı |
| `realrate.py` | Gerçek reel faiz (FRED DFII10) vs TIP/IEF vekili; merkez bankası alımının ölçülebilir izi |
| `impliedvol.py` | GVZ (altının ima edilen oynaklığı) gerçekleşen oynaklığı üretimdeki tahminciden daha iyi kestiriyor mu, ve bu Calmar'a çevrilebiliyor mu |
| `vixterm.py` | `vix3m` `vix`'in yerini almali mi -- ML ozelligi ve makro bileseni ayri ayri, eslestirilmis A/B |
| `instrument.py` | Tüm skorbord `GLD`/`IAU`/`SLV` üzerinde: bu depodaki kenar, gerçekten alınabilen enstrümanda da var mı — ortak pencere ve sabit komisyonla |
| `miners.py` | `GDX`/`^HUI` madenci öncülüğü: bilgi hangi günde yaşıyor, üretim özellik setine katıyor mu, maliyet merdiveninin neresinde ölüyor — üç kontrollü |
| `pooled.py` | Bağlayıcı kısıt gözlem sayısıysa: iki metali havuzlayıp eğitmek IC'yi artırıyor mu — üç kollu (üretim / normalleştirilmiş / havuz) |
| `flow.py` | Kırılım rejimi: emir akışı (CMF vekili), çapalı VWAP, hacim profili + altı osilatör onayı. Önce hacim serisinin kendisini üç testle **iki satıcıda** sınar (Yahoo vs TradingView), sonra kuralı ön-kayıtlı baraja karşı puanlar — iki metal, iki enstrüman |

```bash
cd backend/research
python panel.py --rebuild   # bir kez, veriyi kurar (~30 sn)
python wall.py              # once bunu oku
python drivers.py
python lags.py
python edge.py              # ~3 dk
python defense.py
python tilt.py              # edge.py'nin sinyallerini onbellekler
python season.py
python compare.py           # gumus eklendiginde/degistiginde
python ratio.py             # ~4 dk (icinde 4 yuruyen-ileri kosusu var)
python ablation.py          # ~12 dk (16 yuruyen-ileri kosusu)
python fedcycle.py          # ~4 dk  (FRED gerekir)
python realrate.py          # ~6 dk  (FRED gerekir)
python impliedvol.py        # ~30 sn (GVZ; panel yeniden kurulmus olmali)
python vixterm.py           # ~6 dk  (vix3m vix'in yerini almali mi)
python pooled.py            # ~25 dk (havuzlanmis cok-varlikli egitim)
python miners.py            # ~11 dk (madenci onculugu: ufuk + A/B + maliyet)
python instrument.py        # ~5 dk  (ayni skorbord ETF uzerinde)
python flow.py              # ~2 dk  (kirilim rejimi: akis + AVWAP + hacim profili)
```

`panel.py` argümansız çalıştırılınca **her iki metal için de** panel kurar
(`panel_gold.json`, `panel_silver.json`). Diğer dosyalar varsayılan olarak
altını okur; `backtest.py silver` gibi bir argümanla gümüşe çevrilebilir.

**FRED artık erişilebiliyor — ama güvenilir değil.** CLAUDE.md 2026-09-07'de
`fred.stlouisfed.org`'u ulaşılamaz diye kaydetmişti (tekrarlanan 60 sn zaman
aşımı, aynı anda her Yahoo çağrısı geçerken). 2026-09-08'de aynı makineden
her seri 1,2 sn altında geldi ve arada kodda hiçbir şey değişmedi. Dürüst
okuma "engel kalktı" değil, **"bu host burada aralıklı olarak engelli"**.
Son iki dosya FRED'i serbestçe kullanıyor; **canlı tahmin yolu kullanmıyor
ve kullanmamalı** — ağ havasına göre var olup yok olan bir özellik kolonu,
kayıtlı modelin özellik listesini bir sonraki koşuyla uyumsuz hâle getirir
(bkz. `predict.py`'nin isim kontrolü). 11. bölüm bunun bir bedeli olmadığını
da ölçtü: vekil, gerçek seriden ayırt edilemiyor.

---

## 1. Temel bulgu: altının duvarı XRP'ninkinden 7,3 kat alçak

`wall.py`. Başabaş yön isabeti = %50 + (tek yön maliyet / ortalama |hareket|).
Bu, modelin kalitesiyle ilgisi olmayan aritmetik bir kimliktir.

| Varlık / ufuk | Ort. hareket | Gidiş-dönüş | Başabaş | Gereken avantaj |
|---|---|---|---|---|
| XRP, 15 dakika | %0,219 | 20 bp | **%95,7** | +45,7 puan |
| Altın, 1 gün | %0,803 | 10 bp | **%56,2** | +6,2 puan |
| Altın, 5 gün | %1,881 | 10 bp | **%52,7** | +2,7 puan |
| Altın, 20 gün | %3,773 | 10 bp | **%51,3** | +1,3 puan |

Sebep model değil aritmetik: hareket 3,7x büyük, maliyet 2x ucuz.
**XRP-Guess'i bitiren duvar burada aşılabilir bir eşik.** Projenin
5 günlük ufku bu tablodan seçildi — cron sıklığından değil.

## 2. Altının gerçek makro sürücüleri var, ama çoğu alınamaz

`drivers.py` + `lags.py`. Her seri iki kez ölçüldü: aynı gün (açıklar,
alınamaz) ve ertesi gün (öncü, alınabilir).

**Eşzamanlı ilişkiler gerçek ve güçlü** — gümüş r=+0,783, dolar endeksi
r=−0,401, bakır r=+0,333. Hepsi tamamen alınamaz: bugünkü doların kapanışını
öğrendiğinde bugünkü altının kapanışını da öğrenmiş olursun.

**Test yarısında Bonferroni eşiğini (|t|>3,29) geçen ve iki yarıda işareti
tutan üç seri:**

| Seri | lag 0 (aynı gün) | lag +1 (ertesi gün) | t |
|---|---|---|---|
| `tip` (enflasyona endeksli tahvil ETF) | +0,206 | **+0,088** | +6,63 |
| `ief` (nominal tahvil ETF) | +0,164 | **+0,066** | +5,18 |
| `vix` (korku endeksi) | −0,008 | **−0,068** | −5,42 |

`lags.py`'nin işi bunların takvim kayması olmadığını kanıtlamaktı ve
kontrol serisi bunu kesin olarak yapıyor: **gümüşün aynı gün r=+0,783 iken
ertesi gün r=−0,016** — yani devasa bir eşzamanlı ilişki tek başına lag+1
kuyruğu **üretmiyor**. Demek ki TIP'in kuyruğu gerçek.

**VIX en temizi ve en şaşırtıcısı**: aynı gün ilişkisi sıfır, ertesi gün
belirgin ve **negatif**. Yani VIX sıçraması ertesi gün altın için kötü —
"güvenli liman" hikâyesinin tersi. Standart açıklama zorunlu likidasyon:
gerçek bir panikte altın hâlâ satılabilen likit şeydir, önce teminat için
satılır, alıcısı sonra gelir.

## 3. Yön tahmini şansı yeniyor, al-ve-tut'u yenmiyor

`edge.py`. Yürüyen-ileri, örneklem dışı, 63 günde bir yeniden fit.
**Projenin merkezî bulgusu budur.**

| Ufuk | Model | İsabet | vs %50 | vs hep-YUKARI | vs duvar |
|---|---|---|---|---|---|
| 1 gün | ML | %52,85 | +2,85p (z=+3,99) | −0,04p | −3,38p |
| 1 gün | Harman | %53,12 | +3,12p (z=+4,36) | +0,22p | −3,11p |
| **5 gün** | **ML** | **%53,26** | **+3,26p (z=+2,04\*)** | **−1,96p** | **+0,60p** |
| 5 gün | Harman | %53,89 | +3,89p (z=+2,44\*) | −1,33p | +1,24p |
| 20 gün | ML | %51,05 | +1,05p (z=+0,33\*) | −5,31p | −0,28p |

\* örtüşme düzeltmeli z (ufuk h'de ardışık tahminler h−1 gün paylaşır).

Okunuşu: **model 5 günlük ufukta maliyet duvarını aşıyor ama hiçbir ufukta
"hep YUKARI" demeyi yenmiyor.** Brier beceri skoru her ufukta negatif —
olasılıklar sabit taban oranı söylemekten daha kötü.

Sadece %50'ye baksaydık "z=+4,56, anlamlı avantaj!" diye kutlardık. Dürüst
tabana karşı model hiçbir şey katmıyor.

## 4. Model pozisyon boyutunu da eğemiyor

`tilt.py`. Madde 3'ün doğal devamı: model taraf seçemiyorsa, sürekli-uzun
bir pozisyonun **büyüklüğünü** ayarlayabilir mi?

    pozisyon = clip(TABAN + EĞİM × sinyal, 0, 1)

**Hayır.** Sadece-ML ızgarası eğitim yarısında zorlanmadan **EĞİM = 0,0**
seçti — yani veri, modelin boyutlandırmaya da bir şey katmadığını kendisi
söyledi. Harman ızgarası düz bir yüzeyden (her yerde 0,13-0,15) EĞİM=0,4
seçti, yani gürültü seçti; testte katkısı +0,011 Calmar, −0,029 Sharpe.

**Metodolojik uyarı (bu dosya keşfetti):** *Calmar TABAN'ı sıralayamaz.*
Pozisyonu sabit bir k ile ölçeklemek hem YBG'yi hem maksimum düşüşü ~k ile
ölçekler, oran değişmez — ölçüldü: sabit %50 pozisyon Calmar 0,58, al-ve-tut
0,59. Aramanın TABAN ekseni neredeyse hiçbir şey ölçmüyordu. Gelecekte
buraya benzer bir ızgara kurarsan bunu bil.

## 5. İşe yarayan tek şey: oynaklığa tepki veren pozisyon boyutlandırma

`defense.py`. Yön tahmininden tamamen vazgeçip sadece **daha iyi tutmayı**
dener.

Tek bölmeli test disiplini işini yaptı ve aşırı uydurmayı yakaladı:
eğitimde Calmar'ı en yüksek varyant (EMA50/200, Calmar 0,54 vs al-ve-tut
0,37) **testte çöktü** (0,20 vs 0,40). XRP'deki kesitsel momentum dersinin
birebir tekrarı.

Ama tek bölme yanıltıcıydı: test yarısı (2014-2026) altının 1200$→4400$
koşusu. Böyle bir pencerede piyasadan çıkan her kural kaybeder. **Yıllık
yeniden-seçimli yürüyen-ileri** (her yıl, önceki 5 yıla bakarak seç) her iki
rejimi de örneklem dışına koyar:

| 19,9 yıl, tamamen örneklem dışı | YBG | Oynaklık | Sharpe | Maks düşüş | Calmar |
|---|---|---|---|---|---|
| Yürüyen-ileri seçim | %8,5 | %13,4 | **0,64** | **%30,1** | **0,28** |
| Al-ve-tut | %10,6 | %18,3 | 0,58 | %44,4 | 0,24 |

**Riske göre geçiyor, mutlak getiride geçmiyor.** 2,1 puan yıllık getiri
karşılığında maksimum düşüş 44,4'ten 30,1'e iniyor.

**Neden bu işe yarıyor da yön tahmini yaramıyor**: oynaklık hedefleme
hiçbir şey **tahmin etmiyor**. Gerçekleşen oynaklık güçlü şekilde
otokorelasyonludur — çalkantılı bir haftayı çalkantılı bir hafta izler — yani
son oynaklığa göre pozisyon ölçeklemek gerçekten kalıcı bir şeye tepki
vermektir. `defense.py`'nin kazancını asla "demek ki model iyi" diye okuma;
bunlar ayrı iki makine.

### Rejim ayrıştırması — takas burada görünüyor

| Dönem | Al-ve-tut | EMA50/200 | Oynaklık hedefi %15 |
|---|---|---|---|
| 2001-2011 boğa | %+21,3 / düşüş %29,7 | %+19,1 / **%23,4** | %+19,5 / **%18,5** |
| **2011-2015 ayı** | **%−12,3 / düşüş %43,9** | **%−1,7 / %8,3** | %−11,2 / %40,7 |
| 2016-2019 yatay | %+6,0 / %17,4 | %+3,0 / %17,5 | %+5,6 / %17,3 |
| 2019-2026 boğa | %+17,8 / %25,1 | %+9,9 / %31,3 | %+16,6 / **%19,8** |

Trend filtresi 2011-2015 ayısında düşüşü **%43,9'dan %8,3'e** indirmiş
(−35,5 puan) ve getiriyi 10,7 puan iyileştirmiş; 2019-2026 boğasında ise
7,8 puan getiri yemiş. Sigorta tam olarak böyle görünür.

**Düşüş-stopu kuralları düşüşü KÖTÜLEŞTİRDİ** (%55,3 vs %44,4): dipte satıp
yukarıda geri alıyorlar. `trading.TREND_OFF_EXPOSURE`'ın sıfır değil 0,35
olmasının sebebi budur.

## 6. Mevsimsellik: hiçbir şey ayakta kalmıyor

`season.py`. Altın, mevsimsellik folklorunun en çok sevdiği varlık (Hint
düğün sezonu, Çin Yeni Yılı) ve hikâyeler en azından fiziksel olarak makul.

**Sonuç: 0/12 ay, 0/5 hafta günü, 0/2 ay dönümü kovası Bonferroni eşiğini
geçiyor.** İşaret tutarlılığı aylarda 6/12 — tam olarak şansın beklediği.
Eğitimde seçilen en iyi ay (Kasım) testte yıllık **−%0,5** getirdi.

**Bu dosya bir test tasarım hatası yakalayıp düzeltti ve kayıt önemli.**
İlk sürüm her kovayı **sıfıra** karşı test ediyordu. Altın zaten yukarı
sürüklendiği için neredeyse her kova pozitif çıkıyor ve t-değeri
mevsimselliği değil **örneklem boyutunu** ölçüyordu: "ay ortası" kovası
t=3,24 ile "anlamlı", "ay dönümü" t=1,45 ile değil — oysa ortalamaları
%0,0515 ve %0,0487, yani ayırt edilemez. Tek fark biri 5056 gün, diğeri
1215 gün içeriyordu. Doğru null hipotezle (**ortalama bir güne** karşı) her
ikisi de doğru şekilde sıfıra çöküyor. Hatalı sürüm 3 "anlamlı" etki iddia
ediyordu.

---

## Kapsam uyarısı

Yukarıdakiler "hiçbir şey işe yaramaz" demek değil. **Günlük OHLCV + kamuya
açık makro veriyle, bu kurulum ailesinde** böyle demek.

Test edilmemiş ve bu tezgâhla test de edilemeyecek olanlar:
- **CFTC COT pozisyon verisi** (haftalık, ücretsiz — ölçülmedi, gerçek bir
  boşluk)
- **Merkez bankası alımları** (WGC verisi, üç aylık gecikmeli)
- **ETF akışları** (GLD holdings günlük yayımlanıyor)
- **Vadeli eğri şekli** (contango/backwardation, sürekli seri gerekiyor)
- Piyasa yapıcılık, emir defteri mikroyapısı — bunlar tahmin değil altyapı
  oyunlarıdır.

Ayrıca bu panelin 25 yılı altın için **olağanüstü bir boğa** (270$ → 4400$,
yıllık %11,8). Al-ve-tut'un bu kadar güçlü görünmesinin bir kısmı budur ve
gelecek için garanti değildir. Savunma kurallarının bedeli boğada ödenir,
karşılığı ayıda alınır; 5. maddedeki rejim tablosu bu takası açıkça
gösteriyor.


---

## 7. Gümüş: aynı oyun değil (`compare.py`)

Gümüş eklendiğinde ilk yapılan şey onu altına karşı ölçmek oldu, çünkü
"varlık ekle" tam olarak tek satırlık bir ayar değişikliği gibi görünüp
öyle olmayan türden bir iştir. `ensemble.py` her bileşenin becerisini
`base_rate_up`'a karşı ölçüyor, `trading.py` pozisyonu
`target_volatility`'ye karşı boyutlandırıyor — altının sayılarını gümüşe
kopyalamak, gümüşün tüm skorbordunu sessizce yeniden tabanlar.

### Veri kalitesi: gümüşün düz mumları da gerçek

Gümüş panelinde **1532 düz mum (%24,4)**, altında 683 (%10,9) var. İki
katından fazla, o yüzden altın için verilen "tut" kararı gümüş için
yeniden soruldu — bu kez SLV'ye karşı:

| Varlık | Düz oran | Düz mum r | Normal mum r | Düz \|fark\| | Normal \|fark\| |
|---|---|---|---|---|---|
| Altın | %10,9 | 0,737 | 0,892 | %0,175 | %0,213 |
| Gümüş | %24,4 | **0,894** | 0,896 | %0,353 | %0,430 |

Gümüşün düz mumları **altınınkinden bile temiz** — normal mumlardan
ayırt edilemiyorlar. Tutuluyorlar.

### Fiyat davranışı: aynı getiri, iki katı acı

| | YBG | Oynaklık | Maks düşüş | Sharpe (al-tut) |
|---|---|---|---|---|
| Altın | %11,8 | %18,1 | %44,4 | 0,56 |
| Gümüş | %11,7 | **%33,7** | **%75,8** | **0,25** |

25 yılda neredeyse **aynı getiri**, ama **1,86 kat oynaklık** ve
**%75,8 maksimum düşüş**. Bu tek satır `assets.SILVER.target_volatility`'yi
belirledi: altının %15'lik bütçesi gümüşe uygulansaydı gümüş kalıcı olarak
tam pozisyonun üçte birinde takılı kalırdı — bu "oynaklık hedefleme" değil,
"daha az gümüş tut" olurdu ve hiç test edilmemiştir. Ölçülen oranla
ölçeklendi: %28.

### Taban oranlar farklı

5 işlem gününde: **altın %55,7, gümüş %53,9.** `ensemble.py`'nin
`base_rate` parametresi bu yüzden var. 1,8 puanlık fark küçük görünür ama
hem havuzun başladığı önsel hem de her bileşenin ölçüldüğü referans odur —
yani yanlış olanı kullanmak iki yerden birden yanlılık enjekte eder.

> **Bu arada altının kendi sabiti de burada düzeltildi.** Kodda 0,552
> yazıyordu; `wall.py`'nin tablosundan yanlış satır okunmuştu. Gerçek değer
> 0,557. Yarım puan, ama tüm sistemin kalibre edildiği tek sayıda.

### Sürücüler kısmen ortak

| Varlık | Sürücü | Eşzamanlı r | Öncü r (test) | t | Bonferroni |
|---|---|---|---|---|---|
| Altın | tip | +0,206 | +0,1205 | +6,79 | **geçti** |
| Altın | ief | +0,164 | +0,0700 | +3,92 | **geçti** |
| Altın | vix | −0,008 | −0,0635 | −3,56 | **geçti** |
| Gümüş | tip | +0,152 | +0,0895 | +5,03 | **geçti** |
| Gümüş | ief | +0,056 | +0,0458 | +2,56 | geçemedi |
| Gümüş | vix | −0,111 | −0,0813 | −4,56 | **geçti** |

**`ief` gümüşü öncülemiyor.** Bu yüzden `assets.SILVER.leading_drivers`
sadece `("tip", "vix")` ve `macro_signal` üç yerine iki terim üzerinden
normalize ediyor. Öncülemeyen bir seriyi taşımak bedava değildir — kanıtın
yerine gürültü koyan ağırlıklı bir terim ekler.

Not: gümüşün VIX'i altından farklı olarak **eşzamanlı** da negatif
(−0,111 vs −0,008). Gümüş daha çok bir risk varlığı gibi davranıyor.

### Backtest: gümüşte hiçbir şey daha kolay değil

19,5 yıl, gümüşün kendi maliyet varsayımıyla (20 bp gidiş-dönüş):

| Strateji | YBG | Sharpe | Maks düşüş | Calmar | İşlem |
|---|---|---|---|---|---|
| `macro` | %9,2 | 0,31 | %65,9 | **0,14** | 2051 |
| `technical` | %8,3 | 0,28 | %68,1 | 0,12 | 389 |
| `voltarget` | %8,2 | 0,31 | %69,5 | 0,12 | 169 |
| `ml` | %7,9 | 0,26 | %68,8 | 0,11 | 408 |
| **`buyhold`** | **%8,6** | 0,25 | %75,8 | 0,11 | 1 |
| `ensemble` | %5,9 | **0,32** | **%59,3** | 0,10 | 442 |

Altındaki tabloyla aynı şekil: birkaç strateji Calmar'da al-ve-tut'u
kıl payı geçiyor, hiçbiri getiride geçmiyor, ve `ensemble` düşüşü belirgin
şekilde azaltıp (%75,8 → %59,3) getirinin üçte birini ödüyor.

---

## 8. Altın/gümüş oranı: ölçüldü, 60 testin sıfırı geçti (`ratio.py`)

Bu bölüm uzun süre "ölçülmemiş, cazip ve tehlikeli" diye duruyordu. Artık
ölçüldü.

Sorunun saf hâli bir tuzak, iki nedenle:

1. **Tüm-örneklem ortalaması geleceği okumaktır.** Oran 2011'de 32, 2020'de
   126 gördü. 2011'de "uzun vadeli ortalamayı" bilen biri onu geleceğe
   bakarak biliyordu. Buradaki her test **kayan 250 günlük z** kullanıyor.
   Uyarının kendisi veride duruyor: panelin ilk yarısının medyanı **60,3**,
   ikinci yarısının **78,7**. "Ortalama" sabit bir sayı değil, kaymış bir
   seviye.
2. **Dönüş iki bacaktan gelebilir, biri bize kapalı.** log(oran) değişimi
   tam olarak altının log getirisi eksi gümüşünkü — yani "oran döner" bir
   **uzun/kısa** iddiasıdır. Bu sistem kısa pozisyon almıyor ve almayacak.
   Yüksek oran altın **düşerek** düzeliyorsa sadece-uzun bir defter bunu
   toplayamaz; toplayabileceği tek kanal gümüşün **yükselmesi**.

### Ortalamaya dönüş var mı?

AR(1) yarı-ömrü: tamamında **258 gün**, ilk yarıda 162, ikinci yarıda 94.
Yarı-ömür bir yıl mertebesindeyse **5 günlük karar penceremizde oran
pratikte sabittir** — doğru olsa bile bize bir şey söylemez.

### 60 hücrelik tarama

Oranın beş ayrı hâli (250g z, 1250g z, 20g momentum, 60g momentum, 250g
yüzdelik sırası) × üç hedef (spread, altın bacağı, gümüş bacağı) × dört
ufuk (1/5/20/60g) = **60 test, tek bir aile**. Eşik önceden ilan edildi:
Bonferroni |t| > 3,34.

**Geçen hücre sayısı: 0/60.**

İki ayrıntı sonucun *neden* böyle olduğunu anlatıyor:

- **Spread hücrelerinin yirmisi de negatif** — yani dönüşün *işareti*
  doğru, sadece büyüklüğü yok. En güçlüsü z1250/60g: r=−0,278, t=−2,03.
  Eşiğin altında, ve zaten uzun/kısa bir işlem.
- **Her iki bacak da POZİTİF.** Yüksek oran, ardından **hem altının hem
  gümüşün yükselmesini** öncülüyor. Bu ortalamaya dönüş değil; oranın kriz
  zirvelerinde tepe yapıp iki metalin birlikte toparlanması. Hikâyenin
  öngördüğü yapının tersi.

### Sadece-uzun rotasyon: kontrol grubu ne olduğunu gösteriyor

"z yüksekse gümüş tut, düşükse altın" kuralı, 25 yıl, gerçek maliyetle:

| Strateji | YBG | Oynaklık | Sharpe | Maks düşüş | Calmar |
|---|---|---|---|---|---|
| hep altın | %11,8 | %18,1 | **0,65** | **%44,4** | **0,27** |
| hep gümüş | %11,7 | %33,7 | 0,35 | %75,8 | 0,15 |
| rotasyon z>1,0 (**ham**) | **%13,9** | %25,6 | 0,54 | %58,5 | 0,24 |
| rotasyon z>1,0 (oynaklık eşitli) | %9,4 | %17,9 | 0,53 | %42,6 | 0,22 |

Ham rotasyon YBG'de altını 2,1 puan geçiyor ve **bu tam olarak tuzak.**
Gümüş 1,86 kat oynak, dolayısıyla gümüşte geçirilen her gün daha fazla risk
demek; yükselen bir örneklemde bu tek başına getiriyi şişirir. Oynaklık
eşitlendiğinde kural **her boyutta** altının altına düşüyor. Kontrol grubu
olmadan bu satır "rotasyon işe yarıyor" diye okunurdu.

### Peki çifti birlikte tutmak?

Ayrı bir soru: zamanlama değil, çeşitlendirme. Tahmin edilecek bir şey yok,
dolayısıyla yanılacak bir şey de yok.

| Portföy | YBG | Oynaklık | Sharpe | Maks düşüş | Calmar |
|---|---|---|---|---|---|
| hep altın | %11,8 | %18,1 | **0,65** | **%44,4** | **0,27** |
| 50/50, aylık denge | %12,4 | %24,6 | 0,50 | %57,4 | 0,22 |
| ters-oynaklık, aylık denge | **%12,5** | %22,1 | 0,57 | %53,7 | 0,23 |

Yine aynı şekil: çift daha çok getiri veriyor, orantısız daha çok risk
alarak. Risk-paritesi ağırlıkları bile altını **tek başına** geçemiyor.
(Not: 50/50 sanıldığı gibi tarafsız değil — gümüş 1,86 kat oynak olduğu için
eşit dolar bölüşümü zaten üçte iki gümüş riskidir.)

### `gs_ratio_z` modelde ne yapıyor?

`ml_model.FEATURE_COLUMNS` içinde duruyor. İki test yapıldı ve **ikisi
birbiriyle çelişti**, ki asıl bulgu bu:

| | permütasyon önemi (tek bölme) | yürüyen-ileri A/B |
|---|---|---|
| Altın | +0,19p (faydalı, sıra 12/27) | çıkarınca **+0,78p** (zararlıymış) |
| Gümüş | −1,67p (en zararlı, sıra 25/25) | çıkarınca **−0,20p** (faydalıymış) |

Eşleştirilmiş McNemar: altın **p=0,489**, gümüş **p=0,935**, gürültü bandı
±2,26p. İki testin her iki metalde de **işaret bakımından çelişmesi**,
etkinin gürültü olduğunun ölçülmüş hâlidir.

**Karar: hiçbir şey değişmedi.** p=0,49'luk bir farka dayanarak kolon
çıkarmak, tam olarak bu tezgâhın önlemek için var olduğu şeydir.
`gs_ratio_z` yerinde kaldı — ama artık *neden* orada olduğu değil, **ne
yapmadığı** yazılı.

Oran arayüzde gösterilmeye devam ediyor, çünkü kullanıcı ona bakıyor. Yeni
olan: yanında **tarihsel konumu ve ölçüm sonucu** da yazıyor
(`predictions.gs_ratio`, `gs_ratio_z` — yalnızca gösterim, hiçbir strateji
okumuyor).

---

## 9. ML bileşeni neden taban orana takılıyor (`ablation.py`)

`edge.py` olguyu kurdu: model şansı yeniyor, "hep YUKARI"yı yenmiyor. Bu
dosya **neden** diye soruyor, çünkü iki aday açıklama zıt işler gerektirir:

- **A) Etiket.** Altının eğitim etiketlerinin %55,8'i 1. Log-loss'u küçülten
  bir sınıflandırıcı önce marjinali öğrenir; her yere 0,557 demek zaten
  neredeyse optimaldir. Bu okumaya göre model taban oranı **yenemiyor**
  değil, sadakatle **yeniden üretiyor**. Çözüm sürüklemesi çıkarılmış bir
  etiket olurdu — ki `ensemble.py`'nin zaten istediği şekil bu: bileşenleri
  taban orana karşı olabilirlik oranıyla havuzluyor.
- **B) Özellikler.** 27 kolonda 5 günlük ufukta yön bilgisi yok ve hiçbir
  yeniden etiketleme onu var edemez.

Ölçüt **bilgi katsayısı (IC)**: model olasılığı ile gerçekleşen ileri
getirinin korelasyonu. Doğruluk etiketler arası kıyaslanamaz (her etiketin
kendi tabanı var), IC kıyaslanabilir. 14 karşılaştırma önceden ilan edildi.

### A) Etiket tasarımı — kendi en iyi fikrim çürüdü

| Etiket | eğitimde 1 oranı | IC | t | p (L0'a karşı) |
|---|---|---|---|---|
| L0 ham yön (üretim) | 0,558 | **+0,0554** | 1,73 | — |
| L1 medyan sürükleme üstü | 0,512 | −0,0040 | −0,12 | 0,054 |
| L2 ortalama sürükleme üstü | 0,526 | +0,0163 | 0,50 | 0,252 |
| L3 büyük yükseliş (>0,5σ) | 0,348 | −0,0043 | −0,13 | 0,174 |

L1 tam istediğim şeyi yaptı: etiketi temiz bir %51,2'ye dengeledi. Ve IC
**+0,055'ten −0,004'e** düştü. Sürükleme çıkarıldığında geriye **hiçbir şey**
kalmıyor.

**Yani cevap A değil, B.** Model taban oranı yeniden üretmiyor; taban oranın
kendisi öğrenilebilir olan tek şey. Altının +0,055'lik IC'si de büyük ölçüde
"her şey yükselir" bilgisidir, "bu koşullarda yükselir" değil.

### B) Özellik seti — hiçbir grup diğerinden farklı değil

| Set | kolon (altın/gümüş) | IC altın | p | IC gümüş | p |
|---|---|---|---|---|---|
| F0 tam set (üretim) | 27 / 25 | +0,0554 | — | −0,0152 | — |
| F1 5-günlük makro yok | 22 / 21 | +0,0506 | 0,760 | −0,0042 | 0,349 |
| F2 bağlam bloğu yok | 20 / 18 | +0,0586 | 0,894 | −0,0089 | 0,745 |
| F3 sadece fiyat | 13 / 13 | +0,0303 | 0,451 | −0,0280 | 0,607 |
| F4 sadece makro | 14 / 12 | **+0,0610** | 0,964 | +0,0244 | 0,309 |

F4 (sadece makro, 14 kolon) altında en yüksek IC'yi veriyor — ve p=0,964.
Yarı sayıda kolonla aynı sonuç, ama **farkın kendisi ölçülemiyor**, o yüzden
seçilmiyor. Bu satırı "F4'e geçelim" diye okumak tam olarak N içinden en
iyisini seçmektir.

**Gümüşün IC'si neredeyse her varyantta negatif** — gümüş modelinin bilgi
taşımadığı, bu tezgâhın gümüş hakkında söylediği her şeyle tutarlı.

### Negatifin sınırı — bu tablo olmadan yukarısı okunmamalı

| | değer |
|---|---|
| Satır sayısı | 5704 |
| Ufuk (örtüşme) | 5 gün → etkin örnek ~1140 |
| Bonferroni eşiği | \|t\| > 2,91 |
| **Ayırt edilebilen en küçük IC** | **0,086** |
| Altında ölçülen IC | 0,055 |

**Ölçülen değer, ayırt edilebilir eşiğin altında.** Yani bu çalışma
"IC > 0,086 değil" diyebiliyor, "IC = 0" diyemiyor. 0,05'lik gerçek bir IC
bu işte saygıdeğer bir sayıdır ve **bu örneklem onu asla göremezdi**.

Doğru okuma: *"Bu ailede büyük bir etki yok; küçük bir etki varsa 25 yıllık
günlük veri onu kanıtlayamaz."* Yapılacak iş daha fazla özellik denemek
değil, **daha çok bağımsız gözlem** — ki bu da canlı kayıt biriktirmek
demektir, tam olarak sistemin şu an yaptığı şey.


---

## 10. Fed faiz kararları: üç ayrı iddia, üçü de geçemedi (`fedcycle.py`)

"Fed indirince altın çıkar" bu varlık hakkında en çok tekrar edilen cümle ve
**yanlışlanamayacak** bir biçimde tekrar ediliyor: ne zaman, ne kadar, neye
karşı söylemiyor. Bu dosya onu üç ayrı, ayrı ayrı kanıt gerektiren iddiaya
bölüyor.

Olay listesi **hafızadan yazılmadı**: `fetch_data.get_fed_target_rate()`
DFEDTAR'ı (tek hedef, 2008-12-15'e kadar) DFEDTARL/DFEDTARU'nun **orta
noktasına** ekliyor. Orta nokta önemli — üst banda eklemek 2008-12-16'da
FOMC'nin hiç yapmadığı 12,5 baz puanlık bir "indirim" basardı. Panelde
**64 politika değişimi** var (27 indirim, 37 artış).

### 1) Olay: indirimden sonra gerçekten yükseliyor

| | Altın +1..+20 gün | Gümüş +1..+20 gün |
|---|---|---|
| İNDİRİM sonrası | **%+2,71** (n=26), sürükleme üzeri t=+1,19 | **%+5,60** (n=26), t=+1,91 |
| ARTIŞ sonrası | %+0,90 (n=37), t=−0,14 | %+1,43 (n=37), t=+0,06 |

Yön hikâyeyle uyumlu ve büyüklük küçük değil. Ama t değerleri eşiğin
uzağında ve **kıyas sıfır değil sürüklemedir**: altının ortalama 20 günü
zaten %+1,02, gümüşünki %+1,34. İndirim sonrası fazlalık bunun üstündeki
kısımdır.

### 2) Rejim: taban oran rejime göre değişiyor mu? — asıl soru

Bu bölüm kod değiştirebilecek olandı, çünkü `ensemble.py` **her** bileşenin
becerisini `base_rate_up`'ın tek bir sayısına karşı ölçüyor. Taban oran
aslında iki farklı sayıysa, her bileşenin "becerisi" kısmen rejim
artefaktıdır.

Altın, 5 günlük ufuk, test yarısı (taban %55,7):

| Rejim | P(yük.) eğitim | P(yük.) test | fark | z | görülebilir en küçük fark |
|---|---|---|---|---|---|
| GEVŞEME | 0,546 | 0,596 | +3,9p | +1,05 | 11,7p |
| SIKILAŞTIRMA | 0,603 | 0,533 | −2,4p | −0,84 | 9,1p |
| BEKLEME | 0,569 | 0,518 | −3,9p | −0,95 | 13,0p |

**24 rejim hücresinin 0'ı geçti.** İşaretler tutarlı (gevşemede yukarı,
beklemede aşağı, her iki metalde de) ama sıkılaştırma iki yarı arasında
işaret değiştiriyor ve hiçbir hücre eşiğe yaklaşmıyor.

**Son kolon bu tablonun en önemli kısmı.** 5 günlük ufukta örtüşme
düzeltmesinden sonra bu alt örneklemlerin ayırt edebileceği en küçük sapma
**9-13 puan**, 60 günlük ufukta **31-45 puan**. Ölçülen sapmalar 2-7 puan.
Yani bu çalışma "rejim etkisi yok" **diyemiyor**; "varsa 10 puandan küçük"
diyebiliyor. `ablation.py`'nin IC sınırıyla aynı cinsten bir sınır.

### 3) Sürpriz: kararın kendisi değil, şaşırtma miktarı

Kararın ne olacağı haftalar önce fiyatlı; alınabilir olan varsa sürprizdir.
Vekil: 5 yıllık getirinin (^FVX) olay günündeki değişimi. Tepki **bir sonraki
kapanıştan** ölçülüyor — olay günü kapanışı kararı zaten içerir.

**8 hücrenin 0'ı geçti.** Eğitim yarısında beklenen negatif işaret var
(altın 1g r=−0,32), test yarısında **işaret dönüyor** (+0,14). n=31 olay,
yani bu test zaten çok zayıf ve öyle olduğu yazılı.

### 4) Kolon kararı: `policy_tilt` eklenmedi

Vekil önce doğrulandı: ^IRX'in (13 haftalık bono, anahtarsız) 126 günlük
eğimi FRED'in gerçek Fed duruşuyla **%93,7 uyuşuyor**. Yani politika duruşunu
FRED'siz taşımak mümkün — soru onu taşımaya değip değmediği.

Eşleştirilmiş yürüyen-ileri A/B, tek değişen kolon:

| | kolon | IC | doğruluk | p (eşli) |
|---|---|---|---|---|
| Altın, üretim | 27 | +0,0595 | 0,5197 | — |
| Altın, + `policy_tilt` | 28 | +0,0590 | 0,5210 | **0,947** |
| Gümüş, üretim | 25 | −0,0160 | 0,5088 | — |
| Gümüş, + `policy_tilt` | 26 | −0,0270 | 0,5047 | **0,377** |

**Eklenmedi.** p=0,95 ve p=0,38 ile bir kolon eklemek, `ratio.py`'nin
p=0,49'la kolon çıkarmayı reddetmesiyle tam olarak aynı karardır.

### Bu bölümün doğru okunuşu

"Faiz önemsiz" **değil**. Faizin metallere etkisi eşzamanlı olarak devasa
(`drivers.py`: tip t=+6,63; 11. bölümde reel faizin aynı gün r=−0,30).
Bu çalışmanın söylediği, o etkinin **günlük karar penceresinde ayrıca
alınabilir bir şey bırakmadığı**: politika yönü zaten fiyatlanmış hâlde
tahvil serilerinin içinde geliyor ve model `tip_chg`, `ief_chg`, `us10y_chg`
üzerinden onu zaten okuyor.

---

## 11. Reel faiz vekili ve merkez bankası izi (`realrate.py`)

### Vekil ne kadar iyi? — iddiaydı, artık ölçüm

`indicators.py` reel faizi iki ETF'ten yeniden kuruyor ve kodda "şeklini
yakalar, seviyesini değil" yazıyordu. Bu bir **varsayımdı**. FRED'in DFII10'u
elimizdeyken ölçüldü:

| Karşılaştırma | r |
|---|---|
| SEVİYE: DFII10 vs TIP/IEF oranı | +0,592 |
| 5 günlük DEĞİŞİM: DFII10 vs `real_yield_chg` | **+0,929** |

Ölçek de tutuyor: 5 günlük değişimin std sapması gerçek seride 0,1136 puan,
vekilde 0,1158 — **1,02x**. Kodda yazan iddia doğruymuş.

**Ve gerçek seri modele bir şey katmıyor**: `real_yield_chg`'i DFII10'un
kendisiyle değiştiren eşleştirilmiş A/B altında IC +0,0646 → +0,0643,
**p=0,984**. Vekil bedava — bu, FRED'e bağımlı olmamayı bir eksiklik olmaktan
çıkarıyor.

### Asıl bulgu vekilde değil, PENCEREDE

İlk sürüm bu bölümü yanlış kurdu ve kayıt önemli: gerçek seri **1 günlük**
farkla, vekil ise üretimdeki **5 günlük** hâliyle karşılaştırıldı. 1 günlük
fark dünkü habere çok daha duyarlıdır, dolayısıyla ertesi gün korelasyonu
doğal olarak yüksek çıkar — ölçülen şey serinin kalitesi değil, pencere
uzunluğu olurdu. Pencereler eşitlendiğinde:

| Seri | ertesi gün r (test) | t | eşik 2,96 |
|---|---|---|---|
| Altın, DFII10 **1 gün** | −0,1035 | −5,67 | **geçti** |
| Altın, TIP/IEF vekili **1 gün** | −0,0866 | −4,74 | **geçti** |
| Altın, DFII10 5 gün | −0,0300 | −1,63 | geçemedi |
| Altın, TIP/IEF vekili **5 gün (üretim)** | −0,0377 | −2,06 | geçemedi |
| Gümüş, TIP/IEF vekili **1 gün** | −0,0668 | −3,65 | **geçti** |
| Gümüş, TIP/IEF vekili **5 gün (üretim)** | −0,0501 | −2,74 | geçemedi |

**Üretimdeki pencere yanlıştı.** Bu projedeki ölçülmüş her öncü sürücü
1 günlük değişimdir (`tip_chg`, `ief_chg`, `vix_chg` — `drivers.py`);
`real_yield_chg` 5 gün üzerine kurulu **tek** terimdi ve kimse kontrol
etmemişti.

**Model tarafında değişiklik YOK, skorlayıcı tarafında VAR:**

- ML: eşleştirilmiş A/B'de fark ölçülemedi (altın p=0,875, gümüş p=0,529).
  Beklenen sonuç — model zaten `us10y_chg`, `tip_chg`, `ief_chg` taşıyor ve
  1 günlük reel faiz değişimi bunların neredeyse doğrusal bileşkesi.
  `ml_model.FEATURE_COLUMNS` **değişmedi**. Kolonun adını koruyup değerini
  değiştirmek, `predict.py`'nin isim kontrolünün göremeyeceği tek özellik
  değişikliği türüdür — her kayıtlı model farklı dağılımlı bir kolonu
  hatasız şekilde puanlamaya devam ederdi.
- `indicators._score_real_yield` artık `real_yield_chg1`'i okuyor ve
  `REAL_YIELD_SCALE` 0,17 → **0,078** (p90 eşleşmeli). Ölçek pencereyle
  **birlikte** değişmek zorundaydı: 0,17 ile 1 günlük değişim seansların
  %1,1'inde doyuyor, medyan |skor| 0,161 — yani terim yeniden sessizleşirdi.
  Bu, projenin daha önce bir kez düştüğü tuzağın aynısı.

**Bedeli ölçüldü ve gizlenmiyor.** Backtest, tam maliyet merdiveni, iki metal:
Calmar ortalama **−0,003** (`technical`) ve **−0,002** (`ensemble`) — yani
hiçbir şey, ±0,02 bandında. Ama **işlem sayısı neredeyse ikiye katlandı**
(altın `technical` 377 → 659, gümüş 379 → 718), çünkü 1 günlük değişim çok
daha sık işaret değiştiriyor. 150 bp banka basamağında bu gerçek hasar:
altın `technical` Calmar 0,20 → 0,18.

Yine de değiştirildi ve gerekçe denetlenebilir olmalı: 5 günlük terimin
**hiçbir metalde ölçülmüş öncülüğü yok**. Geri almak, ölçülmüş içeriği
olmayan ağırlıklı bir terimi sırf sessiz olduğu için tutmak olurdu. Özet yine
bu projenin defalarca vardığı yer: **gerçek ama üzerine para koymanın pahalı
olduğu bir sinyal.**

### Merkez bankası alımı: ölçemediğimiz şey ve ölçebildiğimiz şey

**Ölçemediğimiz**: gerçek rezerv tonajı. Dünya Altın Konseyi verisi üç aylık,
haftalarca gecikmeli ve kayıt duvarının arkasında; günlük, anahtarsız bir
serisi **yok** ve bu proje piyasa verisi için anahtar kullanmıyor. FRED'de de
aranıp bulunamadı. Bunu "izliyoruz" demek yanlış olurdu.

**Ölçebildiğimiz**: böyle bir alıcının bırakacağı **iz**. Fiyata duyarsız,
büyük ve ısrarlı bir alıcı varsa altın kendi makro sürücülerinin
açıkladığından fazla yükselir — ve bu bir artıktır. Her gün 250 seanslık
pencerede `getiri ~ a + b1·reel faiz değişimi + b2·dolar getirisi` fit
ediliyor.

| Yıl | Yıllık artık | Reel faiz betası | Gerçekleşen |
|---|---|---|---|
| 2017 | %3,1 | −0,081 | %13,3 |
| 2020 | %17,9 | **−0,073** | %24,3 |
| 2022 | %14,3 | −0,055 | %0,8 |
| 2023 | %12,8 | −0,034 | %13,4 |
| 2024 | %22,8 | −0,034 | %25,4 |
| 2025 | %34,3 | −0,010 | %51,9 |
| 2026 | %37,8 | **+0,001** | %5,7 |

Beta 2020'de −0,073 iken 2026'da **+0,001**: "altın reel faizden koptu"
iddiasının ölçülmüş hâli budur. Aynı dönemde açıklanamayan sürükleme
%12,8'den %37,8'e çıkıyor.

**Ama kopma ile alım aynı şey değildir**, ve bu bölümün en önemli cümlesi
şu: **artık, modelin açıklamadığı HER ŞEYdir** — ETF akışları, eksik bir
değişken, ya da iki faktörlü modelin kendisinin yanlış olması dahil. Merkez
bankası alımıyla **uyumludur**; onu **kanıtlamaz**.

**Ve alınabilir değil.** Artığın ileri getiriyi öncüleyip öncülemediği ayrıca
soruldu: 8 hücrenin **0'ı** geçti (en yükseği altın 60g: r=+0,145, t=+1,00).
"Artık büyümüş" bilgisi bir sonraki hafta için bir şey söylemiyor. Yine aynı
şekil: gerçek, açıklayıcı, alınamaz.

---

## 12. Yeni veri kaynakları: iki bulgu, biri beklenmedik (`impliedvol.py`, `drivers.py`)

2026-09-10'da dokuz yeni kamuya açık Yahoo serisi tezgâha alındı: `^GVZ`,
`^MOVE`, `GDX`, `^HUI`, `CNY=X`, `INR=X`, `HYG`, `^VIX3M`, `BTC-USD`.

**Hiçbiri `fetch_data.MACRO_SYMBOLS`'e eklenmedi.** O sözlük canlı yolu da
besliyor (`predict.py` her koşuda her girdiyi çekiyor); kapıdan geçmemiş bir
seriyi oraya koymak günlük bir istek ve sessiz bir arıza yüzeyi satın alıp
karşılığında hiçbir şey vermiyor. Adaylar `research/panel.CANDIDATE_SYMBOLS`
içinde yaşıyor ve terfi yolu tek: `drivers.py`'nin Bonferroni eşiği **ve**
`lags.py`'nin hizalama taraması.

`GLD`/`SLV` bilerek listeye alınmadı — metalin kendisi oldukları için yeni
bilgi taşımazlar, sadece çoklu-test sayacını şişirirlerdi.

### GVZ yön taşımıyor — ve bu zaten iddia değildi

Ne `gvz` ne de ondan türetilen `vrp` (varyans risk primi, `gvz − 100×rv60`)
yön kapısını geçti. Lag taraması nedenini gösteriyor: `gvz` lag 0'da +0,042,
lag +1'de −0,017; `vrp` lag 0'da +0,088, lag +1'de −0,016. İma edilen
oynaklık bir **büyüklük** serisidir, yön serisi değil. Bunu yön testinden
geçirip "bir şey çıkmadı" demek yanlış soruyu sormak olurdu.

### GVZ oynaklığı ÇOK daha iyi tahmin ediyor — ölçüldü, tartışmasız

Asıl soru şuydu: bu projenin **çalıştığı ölçülmüş tek mekanizması** (oynaklığa
tepki veren pozisyon boyutlandırma, bkz. 5. bölüm) geçmişe bakan bir sayıyla
besleniyor (`predict.py:399`, son 60 günün std sapması). Piyasanın kendi
ileriye dönük tahmini daha mı iyi?

Altın, TEST yarısı (2017-07 → 2026-09), gelecek 60 günün gerçekleşen oynaklığı:

| tahminci | r | RMSE |
|---|---|---|
| geçmiş rv60 (**üretim**) | 0,501 | 6,29p |
| GVZ (ölçeklenmiş) | **0,588** | **5,34p** |

Ve asıl test **kapsama (encompassing)** testiydi, çünkü ikisi birbirleriyle
zaten r=0,85 korelasyonlu — "GVZ tek başına daha iyi" neredeyse garanti ve
neredeyse anlamsız. `gelecek_vol ~ a·rv60 + b·GVZ` ortak uydurmasında,
**örtüşmeyen** alt örneklemde (her 60. satır, n=38): **t(b)=+3,12, t(a)=+0,14**.
Yani GVZ yanına konduğunda üretimdeki tahminci **hiçbir şey katmıyor**.
20 günlük ufukta daha da keskin: t(b)=+9,21 iken rv60'ın katsayısı **negatife**
dönüyor (a=−0,20, t=−3,57).

Ölçek tuzağı da baştan ölçüldü: GVZ'nin eğitim yarısında ölçülen ima/gerçekleşen
oranı **1,1162** (varyans risk primi). Ham GVZ'yi `trading.vol_scale`'e vermek
her pozisyonu kalıcı olarak ~1/1,116 ile çarpardı — bu oynaklık hedeflemesi
değil "**%10 daha az altın tut**"tur, `assets.py`'nin gümüşün
`target_volatility`'si için belgelediği arızanın aynısı.

### Ama üretime GİRMEDİ, ve girmeme sebebi bu bölümün asıl dersi

Daha iyi tahmin, ticaret kuralında daha iyi sonuç demek değil.
`vol_tahmini = (1−w)·rv60 + w·GVZ` ızgarası (w ∈ {0; 0,25; 0,5; 0,75; 1}, **w=0
üretimin kendisi ve ızgaranın içinde**) iki mekanik strateji için koşturuldu:

| altın, `voltarget` | w=0 | 0,25 | 0,50 | 0,75 | 1,00 |
|---|---|---|---|---|---|
| **EĞİTİM** Calmar | **0,086** | 0,082 | 0,075 | 0,068 | 0,057 |
| **TEST** Calmar | 0,703 | 0,741 | 0,772 | 0,797 | **0,818** |

İki yarı ızgarayı **tam ters** sıralıyor. Eğitim yarısı w büyüdükçe monoton
kötüleşiyor, test yarısı monoton iyileşiyor — Spearman **−1,00**.

Bu, bu tezgâhın standart kuralının ("eğitimde seç, testte bir kez doğrula")
**yanlış cevap verdiği** bir durum: test yarısındaki iyileşme bir doğrulama
değil, ayrılmış veriden cevabı okumaktır. Bölme soruyu çözmedi, bir **rejim
değişimini ikiye ayırdı** — eğitim yarısı altının 2011-2015 ayısını, test
yarısı 2017-2026 boğasını taşıyor, ve w hangi rejime düştüğüne göre puan
alıyor.

Bu yüzden koruma **script'in içine** yazıldı, tabloyu okuyanın yakalamasına
bırakılmadı: eğitim ve test Calmar sıralamaları arasındaki Spearman ≤ 0 ise
hiçbir şey benimsenmiyor. Uydurulmuş bir eşik değil — "iki yarı en azından
yönde anlaşsın" bir örneklem dışı kontrolden istenebilecek en zayıf şey.

Dört hücrenin üçünde koruma ateşledi (altın `voltarget` −1,00, altın
`defensive` −0,70, gümüş `voltarget` −0,90). Geçen tek hücre gümüş
`defensive` (+0,70, w=0,50, test +0,031 Calmar) — ve o da benimsenmedi:
gümüş burada **açıkça ikincil** bir kontrol (GVZ altının ima edilen
oynaklığıdır; `^VXSLV` yayından kalkmış, Yahoo tek satır döndürüyor), seçim
0,020 vs 0,012 gibi ikisi de sıfıra yakın eğitim Calmar'ları arasında
yapılmış, ve birincil varlık aynı testte iki stratejide birden kalmış.
**Dört hücrenin birini almak tam olarak bu tezgâhın önlemek için var olduğu
şeydir.**

Doğru okuma: **GVZ oynaklığı daha iyi tahmin ediyor, ama bu tahmin üstünlüğü
bu ızgarada Calmar'a çevrilebilir hâlde değil.** 5. bölümün kazancı
oynaklığın *otokorelasyonundan* geliyor; daha iyi bir oynaklık tahmini, o
kazancın kaynağını daha da iyileştirmek zorunda değil.

### Beklenmedik olan: altın madencileri metali ÖNCÜLÜYOR

Yön kapısının düşük beklentili kolu bir şey buldu ve dört ayrı öldürme
denemesinden sağ çıktı. `GDX` ve `^HUI`, **her iki metalde de**, örneklem
dışı test yarısında Bonferroni eşiğini geçti:

| | altın TEST r | t | gümüş TEST r | t |
|---|---|---|---|---|
| `gdx` | +0,1091 | +6,14 | +0,1000 | +5,63 |
| `hui` | +0,0984 | +5,54 | +0,0981 | +5,52 |

Dört öldürme denemesi ve hepsinin sonucu:

1. **Hizalama (`lags.py`).** Tepe lag 0'da (+0,667), lag +1'de +0,150, lag +2'de
   ~0. Temiz bir sönüm, ve **negatif laglarda ağırlık yok** (lag −1: −0,041).
   Bu önemliydi: madenciler 16:00 New York'ta, altın 17:00'da kapanıyor — yani
   altının kapanışı daha taze, ve mekanik olarak beklenen şekil altının
   madenciyi öncülemesiydi. O şekil yok.
2. **Kontrol serisi.** Gümüşün altınla eşzamanlı ilişkisi **daha büyük**
   (+0,783 vs +0,667) ve lag +1'i −0,016. Devasa bir eşzamanlı ilişki tek
   başına lag +1 kuyruğu üretmiyor — 2. bölümün TIP için kurduğu argümanın
   aynısı, burada tersine çevrilemez.
3. **Kendi getirisi kontrolü — belirleyici olan bu.** GDX'in günlük getirisi
   büyük ölçüde altının kendi getirisidir, dolayısıyla lag +1 okuması altının
   **kendi** otokorelasyonu olabilirdi. Bugünkü altın getirisi sabitlendiğinde
   ilişki **zayıflamıyor, GÜÇLENİYOR**: ham r=+0,109 → kısmi r=**+0,179**
   (t=+10,20). Tahmin eden şey madencinin altından **ayrışan** kısmı.
4. **Düz mum artefaktı.** Altının kapanışı bazen sadece bir uzlaşma basımıdır
   (test yarısında %5,2); o günlerde GDX gerçekten altının kapanışında olmayan
   bilgi taşır ve "tahmin" ediyormuş gibi görünürdü. Etki normal mumlarda
   +0,1796, düz mumlarda +0,1817 — **fark yok**, ve örneklemin %95'i normal.

**Yine de üretime girmedi ve girmemeli.** Ölçülen şey **1 günlük** ufukta bir
korelasyondur; bu sistemin ufku **5 gün** (`ml_model.HORIZON_DAYS`), ve
`wall.py` 1 günlük ufkun başabaş isabetini %56,2 diye ölçmüştü — bu projedeki
en yüksek duvar. Bir korelasyonun duvarı aştığı gösterilmedi. Eksik olan üç
test: (a) 5 günlük ufukta ayakta kalıyor mu, (b) maliyet merdiveninin
neresinde ölüyor, (c) `edge.walk_forward`'ın eşleştirilmiş A/B'sinde üretim
özellik setine bir şey katıyor mu. Üçü de kendi fazını hak ediyor.

Bu, `README`'deki on iki bölümün **yön tarafında güçlü şekilde pozitif çıkan
ilki** — ve tam da bu yüzden en şüpheli davranılması gereken bulgu.

### Ek: `vix3m` `vix`'in yerini almalı mı? — hayır (`vixterm.py`)

Yukarıdaki tarama beklenmedik bir yan ürün verdi: `^VIX3M` **iki metalde de**
`vix`'ten daha yüksek t aldı (altın −3,68 vs −3,58; gümüş −4,95 vs −4,57).
Yeni bir sürücü değil — lag profili `vix`'inkiyle aynı şekilde, işareti aynı,
hikâyesi aynı. Makul okuma, aynı sinyalin daha az gürültüyle ölçülmüş hâli
olmasıydı: 30 günlük ima edilen oynaklığa yakın vadede ne varsa o hâkim,
90 günlüğe çok daha az.

Yani soru "vix3m ekleyelim mi" değil, "**vix3m, vix'in yerini almalı mı**"ydı —
ve bu bir takas, yani eşleştirilmiş A/B gerektirir.

**İki tüketici ayrı ayrı test edildi**, çünkü `vix` bu sistemde iki ayrı yerde
yaşıyor: `ml_model.FEATURE_COLUMNS`'ta bir kolon (`vix_chg`, `vix_chg5`) ve
`macro_signal`'da ağırlıklı bir oy. Biri iyileşip diğeri kötüleşebilirdi ve
tek bir harman sayı bunu gizlerdi.

Ufuk **5 gün** (üretimde çalışan ufuk), her iki kol da ortak pencerede
(2006-07 → 2026-09) ve **aynı satırlarda**:

| varlık | kol | üretim IC | aday IC | fark | p |
|---|---|---|---|---|---|
| altın | ML özelliği | +0,0239 | +0,0229 | −0,0010 | 0,910 |
| altın | makro bileşeni | +0,0412 | +0,0426 | +0,0014 | 0,771 |
| gümüş | ML özelliği | +0,0060 | +0,0097 | +0,0038 | 0,804 |
| gümüş | makro bileşeni | +0,0472 | +0,0471 | −0,0001 | 0,956 |

**Dört hücrenin dördü de ayırt edilemiyor**, ve işaretler hücreler arasında
çelişiyor (altın ML'de aday daha kötü, altın makroda daha iyi; gümüşte tam
tersi). Bu, gürültünün imzasıdır.

`drivers.py`'deki üstünlüğün neden çevrilmediği de açık: orada ölçülen
**1 günlük** ham korelasyondu; burada ölçülen, üretimin fiilen kullandığı
**5 günlük** ufukta, gerçek tüketicilerin içinden geçen katkı.

**İki bedel ayrıca ölçüldü ve ikisi de takasın aleyhine:**

- **Geçmiş.** `^VIX3M` 2006-07'de başlıyor, `^VIX` panelin tamamını kapsıyor.
  Ve `ml_model.prepare_training_frame` NaN taşıyan satırı **düşürüyor** — yani
  takas her eğitim koşusundan **1205 seansı (%19,2)** sessizce çıkarırdı.
  Ayırt edilemeyen bir IC farkının yanında bu net bir kayıptır, ve
  `ablation.py`'nin kendi sonucu bu projede bağlayıcı kısıtın **bağımsız
  gözlem sayısı** olduğunu söylüyor.
- **Ölçek.** `VIX_SCALE` sabitleri VIX'in kendi günlük değişim dağılımında
  ölçülmüş. 3 aylık endeks tanım gereği günde daha az oynuyor: eğitim
  yarısında p90 `vix_chg`=2,617 iken `vix3m_chg`=1,787. Ham takas, ağırlıklı
  bir terimi 1,46 kat sessizleştirirdi — `real_yield_chg`'in üçüncü kez
  düzeltilmesine yol açan arızanın aynısı. (Testte bu, `vix3m_chg`'i VIX'in
  ölçeğine taşıyıp **gerçek** `_vix_score`'u değiştirmeden çalıştırarak
  giderildi; girdi ikame edildi, kod değil.)

**Testin gücü de yazılı:** bu örneklemin sıfırdan ayırt edebileceği en küçük
IC 0,0879, ölçülen farklar ise 0,001-0,004. Yani çalışma "fark yok" demiyor,
"**varsa bu örneklemin göremeyeceği kadar küçük**" diyor — ve %19,2 geçmiş
kaybı karşılığında alınacak bir şey değil.

Tek üretim değişikliği bir doğruluk düzeltmesi oldu: `indicators.LEVEL_SERIES`.
Seviye serilerinin farkı, fiyat serilerinin getirisi alınır; bu ayrım daha önce
`("vix", "us10y")` diye gömülü bir listeydi, yani `vix3m` istense **yüzde
değişimi** hesaplanırdı — bir oynaklık endeksinin yüzde değişimi başka bir
niceliktir ve VIX için ölçülmüş bir sabitle puanlanırdı. Üretimin gördüğü
kolonlar değişmedi (altın 27, gümüş 25 özellik).

---

### Ek (2026-09-17): "ama rv60 hiçbir şey katmıyor, o hâlde w=1,0" — hayır

Bu bölümü okuyan herkesin aklına gelen bir sonraki adım şu: *kapsama testi
rv60'ın GVZ'nin yanında hiçbir şey katmadığını söylüyor (t=+0,14), o hâlde
dürüst ağırlık 1,0'dır — üstelik bu bir Calmar'a bakılarak seçilmiş parametre
değil, tahmin kalitesinden türetilmiş bir çıkarımdır.* Argüman güçlü duruyor ve
**dairesel**: dayandığı olgu **test yarısında** ölçüldü, Calmar da orada
okunacaktı. Yani w=1,0 test verisinde seçilip test verisinde doğrulanırdı.

`impliedvol.part1_training` bu boşluğu kapatmak için eklendi: aynı kapsama
testi, **eğitim yarısında** — seçimin serbest olduğu tek yer. Ön-kayıt önce
yazıldı: *ufuk 60'ta, örtüşmeyen alt örneklemde GVZ'nin katsayısı ayakta kalır
(|t|>2, b>0) ve rv60'ınki kalmazsa, w=1,0 yalnızca tahmin kalitesine bakılarak
a priori seçilmiş sayılır.*

| yarı | a (rv60) | t(a) | b (GVZ) | t(b) | n (örtüşmeyen) |
|---|---|---|---|---|---|
| test (12. bölümün tablosu) | +0,067 | +0,14 | +0,680 | **+3,12** | 38 |
| **eğitim (yeni)** | −0,003 | +0,87 | +0,648 | **+1,50** | 38 |

**Seçim yok: eğitim yarısında GVZ de eşiği geçmiyor.** İkisi de geçmiyor —
yani o yarı soruyu ne lehte ne aleyhte cevaplayabiliyor. Üretim `rv60`'ta
kaldı.

**Ve asıl bulgu bu tablonun kendisinde:** GVZ'nin tahmin üstünlüğü de,
Calmar ızgarasının sıralaması da **yarıya bağlı**. İkisi aynı şeyin iki
belirtisi ve o şey sütunun en sağında yazıyor: 4.595 günlük pencere, 60 günlük
ufukta **yarı başına ~38 bağımsız gözlem** demek. 7. ve 13. bölümlerin
"çözüm daha çok özellik değil, daha çok **bağımsız** gözlem" cümlesinin
oynaklık tarafındaki karşılığı — ve burada daha da sert, çünkü ufuk uzadıkça
bağımsız pencere sayısı doğrudan bölünüyor.

> **Para sütunu da eklendi ve üçüncü bir şey söylüyor.** Test yarısını olduğu
> gibi kabul edip seçim sorununu tamamen görmezden gelsek bile, `voltarget`
> için $10.000'lik hesapta 9 yılda: w=0 **$33.012**, w=0,50 **$34.001**,
> w=1,00 **$33.555**. Calmar w ile tekdüze artarken (0,703 → 0,818) **para
> w=0,50'de tepe yapıp geri düşüyor** — 17. bölümün dersi bu çalışmanın
> içinde. Tüm ızgaranın açtığı aralık **$989**, ki aynı bölüm $1.413'ü
> "gürültü mesafesinde" diye kaydetmişti.

## 13. Bağlayıcı kısıta saldırı: havuzlanmış çok-varlıklı eğitim (`pooled.py`)

9. bölümün sonucu bu deponun en çok alıntılanan ama en az üzerine gidilen
cümlesiydi: **"çözüm daha çok özellik değil, daha çok bağımsız gözlem."**
Ondan sonraki her hipotez — GVZ ve GDX dahil — yine **özellik** tarafındaydı.
Bu bölüm kısıtın kendisine bakıyor.

Aritmetik ölçüldü, varsayılmadı: altın 5706, gümüş 5707 eğitilebilir satır.
5 günlük ufukta örtüşme yüzünden etkin bağımsız gözlem varlık başına ~1141;
havuzlanınca ~2282. Tespit tabanı **0,0895 → 0,0634**.

### Ön şart: özelliklerin 10'u varlık ölçeğine bağlıydı

Havuzlanmış bir ağaç ancak bir eşik iki metalde aynı şeyi ifade ediyorsa
bölebilir. p90 |değer| oranı (gümüş/altın):

| uyuşan | oran | UYUŞMAYAN | oran |
|---|---|---|---|
| `rsi14`, `bb_pct`, `donchian_pct`, `vol_ratio` | 0,98-1,02 | `macd_hist` | **0,03** |
| tüm makro kolonlar | **1,00** | `ema9_21`, `px_sma200`, `px_ema50` | 1,74-1,79 |
| | | `return_1d/5d/20d/60d` | 1,81-1,84 |
| | | `vol_20d` | 1,93 |
| | | `counterpart_chg` | 0,55 |

Uyuşmayanlar **tek bir sayıyla** ayrışıyor (~1,8) ve o sayı `assets.py`'nin
zaten ölçtüğü "gümüş 1,86 kat oynak"tır. `macd_hist` ise 0,03, çünkü ham fiyat
biriminde (altın ~$4400, gümüş ~$66) — bugün zararsız çünkü her metalin kendi
modeli var, havuzda ölümcül.

Bu yüzden havuz özellik seti her fiyat türevli kolonu o varlığın **kendi**
kayan oynaklığına (`vol_60d`) bölüyor. **Bu, `assets.py`'nin kuralını
çiğnemiyor, uyguluyor**: yasak olan altının sayısını gümüşe kopyalamak; burada
yapılan her varlığı kendi ölçüsüyle ortak zemine taşımak.

**Varlık kimliği bilerek özellik yapılmadı.** Ağacın ondan öğreneceği ilk şey
"altınsa daha çok YUKARI de" olurdu — yani 9. bölümün "öğrenilebilir olan tek
şey" dediği taban oranı havuzun içine geri sokmak.

### Üç kol, ve ortadaki pazarlık konusu değil

| kol | özellikler | eğitim verisi |
|---|---|---|
| A | üretim | sadece hedef |
| B | normalleştirilmiş | sadece hedef |
| C | normalleştirilmiş | hedef + diğer metal |

B olmadan C−A farkı "havuzlama" ile "normalleştirme"yi karıştırırdı.

| hedef | kol | n | IC | t | isabet |
|---|---|---|---|---|---|
| altın | A üretim/tek | 4893 | +0,0596 | +1,87 | %51,99 |
| altın | B normal/tek | 4892 | **+0,1040** | **+3,27** | %51,94 |
| altın | C normal/HAVUZ | 4892 | +0,0713 | +2,23 | %50,96 |
| gümüş | A üretim/tek | 4894 | −0,0160 | −0,50 | %50,88 |
| gümüş | B normal/tek | 4892 | +0,0065 | +0,20 | %50,37 |
| gümüş | C normal/HAVUZ | 4892 | +0,0046 | +0,14 | %51,10 |

Eşleştirilmiş karşılaştırmalar (aynı satırlar, örtüşme düzeltmeli):

| soru | altın | gümüş |
|---|---|---|
| B vs A (normalleştirme zarar mı) | +0,0444, p=0,122 | +0,0225, p=0,423 |
| **C vs B (HAVUZLAMA ekliyor mu)** | **−0,0327, p=0,101** | **−0,0019, p=0,937** |
| C vs A (paket üretimi geçiyor mu) | +0,0117, p=0,826 | +0,0206, p=0,529 |

### Cevap: havuzlama eklemedi

Asıl soruda işaret **iki metalde de negatif** (altında −0,033, gümüşte
−0,002). Yani 2 kat gözlem IC'yi artırmadı; altında düşürdü.

**Ve "modeli aç bıraktık" mazereti önceden kapatıldı.** Havuz kolu 2 kat
veriyle eğitiliyor ama kapasitesi `hyperparams.py`'de **sadece altın**
üzerinde seçilmişti. Tek bir ön-kayıtlı teşhis koşusu (arama değil,
`max_depth=4`) her iki metalde de **kötüleştirdi**: altın +0,0713 → +0,0609
(p=0,965), gümüş +0,0046 → +0,0042 (p=0,985). Havuzun başarısızlığı bir
kapasite sorunu değil.

Doğru okuma: **9. bölümün "daha çok gözlem" tezi 2x'te doğrulanmadı.** Bu
tezi çürütmüyor — tespit tabanı 0,063'e indi ama ölçülen farklar hâlâ onun
çok altında — ama "sadece daha fazla satır ver" biçiminin işe yaramadığını
söylüyor. Gümüşün satırları altın hakkında yeni bir şey öğretmiyor; iki metal
zaten aynı gün r=+0,78 hareket ediyor, yani **bağımsız gözlem eklemiyorlar,
büyük ölçüde aynı gözlemi tekrar ediyorlar.** Bu, ölçülmeden önce görülebilir
bir itirazdı ve şimdi sayısı var.

### Beklenmedik yan bulgu: normalleştirmenin kendisi (ve neden yine de alınmadı)

Altında B kolu, IC'yi +0,0596'dan **+0,1040**'a çıkardı — t=+3,27, yani hem
çoklu-test eşiğini (2,807) hem de tespit tabanını (0,0895) **tek başına**
geçiyor, ve bu deponun altında ölçtüğü en yüksek IC.

Yine de üretime alınmadı, iki ayrı sebeple ve ikisi de yeterli:

1. **Eşleştirilmiş fark anlamlı değil** (p=0,122). B'nin IC'sinin sıfırdan
   ayrılması ile B'nin A'dan ayrılması **farklı iki sorudur**; ikincisi
   geçmedi.
2. **Gümüşte tekrar etmiyor** (+0,0065, t=+0,20). Bir metalde çıkıp diğerinde
   çıkmayan sonuç `gs_ratio_z`'nin çelişkisiyle aynı kategoridedir.

Ayrıca gümüş için B kolu yalnızca normalleştirmeyi değil, sürücü
**birleşimini** de taşıyor (`ief_chg` gümüşün üretim setinde yok, havuz tek
bir ortak özellik vektörü gerektiriyor) — yani o hücrede B vs A saf bir
normalleştirme testi bile değil. C vs B ikisinden de arınmış.

**Bu, ileride güçlü bir örneklemle tekrar sorulmaya değer tek açık uçtur.**
Ama p=0,12 ve tek metal, bu tezgâhta bir karar değildir.

---

## 14. Madenciler: bilgi gerçek, ama sadece 1 günlük (`miners.py`)

12. bölüm `GDX`/`^HUI`'yi **AÇIK** bırakmış ve eksik üç testi adıyla yazmıştı:
(a) 5 günlük ufukta ayakta kalıyor mu, (b) maliyet merdiveninin neresinde
ölüyor, (c) `edge.walk_forward`'ın eşleştirilmiş A/B'sinde üretim özellik
setine bir şey katıyor mu. Bu bölüm o üç testtir.

**32 test önceden ilan edildi** (2 metal × 2 seri × 6 ufuk = 24 korelasyon,
2 metal × 2 ufuk × 2 aday kol = 8 eşleştirilmiş A/B), eşik |t| > 3,29.
Ortak pencere 2006-05 → 2026-09 (5105 gün); `GDX` 2006'da başladığı için
**1168 seans (%18,6) bedel**, ve `ml_model.prepare_training_frame` NaN satırı
düşürdüğü için üretime girerse bu bedel her eğitim koşusunda da ödenirdi.

### (a) Ölmüyor — SEYRELİYOR, ve bu ayrım her şeyi belirliyor

Kümülatif bir ufuk tablosu "5 günde kayboldu" ile "5 güne yayıldı"yı ayırt
edemez, ve ikisi **zıt işler** gerektirir. Bu yüzden her t+k gününün getirisi
**tek başına** ölçüldü (pencereler örtüşmüyor):

| gün t+k | altın ham r | kısmi r | t | gümüş kısmi r | t |
|---|---|---|---|---|---|
| **+1** | +0,1506 | **+0,2058** | **+15,02** | **+0,2271** | **+16,65** |
| +2 | −0,0265 | −0,0117 | −0,84 | −0,0222 | −1,59 |
| +3 | −0,0004 | −0,0149 | −1,06 | +0,0227 | +1,62 |
| +4 | +0,0155 | +0,0355 | +2,53 | +0,0210 | +1,50 |
| +5 | +0,0271 | +0,0250 | +1,79 | +0,0111 | +0,79 |
| +6..+10 | — | hepsi \|t\|<2,8 | — | hepsi \|t\|<2,0 | — |

(kısmi = metalin **kendi** aynı gün getirisi sabit tutularak; 12. bölümün 3.
öldürme testi, artık her ufukta)

Bütün ağırlık **t+1'de**, ve t+2'den itibaren hiçbir şey yok. Yani 5 günlük
kümülatif korelasyonun düşük çıkması bir **ölüm değil, aritmetik bir
seyrelmedir**: dört günlük ilgisiz gürültü aynı bilginin üzerine biniyor.
Kümülatif tablo bunu doğruluyor — altın kısmi r ufuk 1'de +0,1793, ufuk 5'te
+0,1214, ufuk 20'de +0,0700 (t=+0,78).

### (c) 1 günlük ufukta ML setine büyük katkı, 5 günlük ufukta hiç

`edge.walk_forward`, aynı satırlar, aynı refit takvimi, tek değişen kolon
listesi:

| varlık | ufuk | ÜRETİM IC | +GDX IC | fark | p | +HUI farkı | p |
|---|---|---|---|---|---|---|---|
| altın | **1** | +0,0447 | **+0,1416** | **+0,0970** | **0,000** | **+0,0876** | **0,000** |
| gümüş | **1** | +0,0731 | **+0,1604** | **+0,0872** | **0,000** | **+0,0791** | **0,000** |
| altın | 5 | +0,0057 | +0,0310 | +0,0252 | 0,129 | +0,0124 | 0,367 |
| gümüş | 5 | −0,0031 | −0,0022 | +0,0009 | 0,995 | +0,0042 | 0,665 |

1 günlük ufukta **dört hücrenin dördü de** Bonferroni eşiğini (0,05/32 =
0,0016) geçiyor, aynı işaretle, iki metalde ve iki seride birden. +0,1416,
bu deponun bugüne kadar ölçtüğü **en yüksek IC** (önceki en yüksek 13.
bölümün alınmamış +0,1040'ıydı, üretim +0,055).

5 günlük ufukta ise fark ayırt edilemiyor — **ama testin gücü de yazılı**:
o örneklemin görebileceği en küçük IC 0,1025, ölçülen fark 0,025. Yani
"katkı yok" değil, "**bu ufukta bu örneklemin göremeyeceği kadar seyrelmiş**".

### (b) Maliyet merdiveni — ve üç kontrol olmadan bu tablo okunamaz

İki ön-kayıtlı kural, `trading.compute_rebalance` üzerinden (kopya değil):
`saf` = madenci yükseldiyse tam pozisyon, düştüyse nakit (**bir öneri değil,
üst sınır**); `uretim egimi` = `trading.compute_target_exposure`'ın sinyal
dalının kendisi, 0,85 tabanı etrafında ±0,15 iki yönlü eğim, ölçeği eğitim
yarısının p90'ı.

**Her iki kural da al-ve-tut'tan daha az metal tutuyor** (%85 ve ~%50), ve
daha az tutmak tek başına oynaklığı ve düşüşü küçültür — yani **gürültüyle
bile** Calmar'ı yükseltirdi. Bu, `assets.py`'nin gümüşün `target_volatility`'si
için belgelediği "**daha az altın tut**" arızasının aynısıdır. Üç kontrol
bu yüzden zorunlu:

| kontrol | ne yapar | ne eler |
|---|---|---|
| `[sabit ort]` | o kuralın **ortalama** pozisyonunda sabit durur, hiç zamanlama yok | "kazanç daha az metal tutmaktan geliyor" |
| `[bayat]` | aynı kural, **5 gün eski** madenci verisiyle: aynı dağılım, aynı devir hızı, aynı komisyon, sıfır bilgi | "kazanç devir hızından / bir backtest artefaktından geliyor" |
| `[kendi mom]` | aynı kural, metalin **kendi** `return_1d`'siyle — bedava sinyal | "GDX aslında altının kendi momentumunun vekili" |

**Üçü de geçildi, istisnasız.** `[sabit ort]` her hücrede al-ve-tut'la aynı
(±0,02) — yani "daha az tut" açıklaması sıfır. `[bayat]` ve `[kendi mom]`
ise al-ve-tut'un **altında**: altında `saf [kendi mom]` Calmar 0,018,
al-ve-tut 0,219. Altının kendi 1 günlük momentumu hiçbir şey kazandırmıyor;
kazandıran şey madencinin altından **ayrışan** kısmı — 12. bölümün kısmi
korelasyon bulgusunun ekonomik karşılığı.

`uretim egimi` kolunun al-ve-tut'a karşı Calmar farkı (48 hücrenin hepsinde
`−BAYAT` ve `−KENDI` **pozitif**):

| maliyet | altın TAM | altın TEST | gümüş TAM | gümüş TEST |
|---|---|---|---|---|
| COMEX 2bp | +0,147 | +0,148 | +0,150 | +0,149 |
| **ETF 10bp** | **+0,100** | **+0,097** | **+0,126** | **+0,125** |
| gümüş varsayılanı 20bp | — | — | **+0,097** | **+0,097** |
| Perakende 40bp | −0,042 | −0,092 | +0,044 | +0,041 |
| **Banka 150bp** | **−0,264** | **−0,525** | **−0,121** | **−0,217** |

**Merdivende öldüğü yer yazılı: altın 10bp ile 40bp arasında, gümüş 40bp ile
150bp arasında.** Kullanıcının gerçek enstrümanı banka gram altınsa (150bp)
bu sinyal **orada para kazandırmaz** — ve bu, 7. bölümün `macro` bileşeni
için ölçtüğü şeyin aynısıdır: gerçek bir sinyal, üzerine para koymanın
pahalı olduğu bir sinyal.

### Hizalama bir kez daha denetlendi

Bu büyüklükte bir sonucu tek başına açıklayabilecek tek hipotez bir günlük
join kayması. İki bağımsız kontrol: `lags.py`'nin tepe noktası **lag 0'da**
(+0,667), lag +1'de +0,150, lag −1'de −0,041 — bir gün kaymış bir join'de
tepe +1'de olurdu, orada değil. Ve `fetch_data.align_on_gold` yalnızca
`reindex(...).ffill()` yapıyor, yani **sadece geriye bakıyor**; bir gelecek
değeri erken bir satıra çekemez.

### Hüküm: üretime GİRMEDİ, ve girmeme sebebi ilan edilmiş şartın kendisi

Benimseme şartı **sonuçlara bakılmadan önce** iki maddeydi: (1) Bölüm 2'de
katkı, aynı yönde, iki metalde de; **VE** (2) Bölüm 3'te al-ve-tut'u geçmek,
iki yarıda da.

- **Şart 2 geçti**, üç kontrolü birden geçerek, her varlığın kendi canlı
  maliyet basamağında.
- **Şart 1, 5 günlük ufukta geçmedi** (p=0,13 / p=0,99). 1 günlük ufukta
  geçti, hem de fazlasıyla.

Şart, iki **ayrı** benimseme yolunu (5 günlük ML kolonu / bağımsız 1 günlük
bileşen) tek bir koşula bağlıyordu. Sonucu **gördükten sonra** onu ikiye
ayırmak, tam olarak bu tezgâhın önlemek için var olduğu şeydir — `gs_ratio_z`
ve GVZ ızgarasında olduğu gibi. Bu yüzden burada hiçbir üretim dosyası
değişmedi.

**Ama bu negatif bir bulgu değil.** Bilgi gerçek, artefakt değil (üç kontrol),
üretim setine katkısı ölçüldü, ve ETF maliyetinde paraya çevrilebiliyor. Tek
sorun şu: **1 günlük**, ve bu sistemin bütün mimarisi 5 gün üzerine kurulu —
ufuk `wall.py` ile ölçülerek seçilmişti ve 1 günlük duvar bu projedeki en
yüksek duvardır (%56,2).

Yani bu, bu depoda **yön tarafında ilk kez gerçek bir üretim değişikliğini
hak eden** bulgudur; ama hak ettiği değişiklik, ilan edilmiş şartın yazıldığı
değişiklik değil. Ayrı bir faz, kendi ön-kaydı ve kendi koşusuyla gerekiyor —
ve o fazın ödemesi gereken üç somut bedel şunlar: `GDX` canlı yola
(`fetch_data.MACRO_SYMBOLS`) girer, panelin %18,6'sı eğitimden düşer, ve
5 günlük tek ufuk varsayımı kırılır.

### Sonrası: Faz 5b — ayrı bir faz, ayrı bir ön-kayıt, ve bu sefer üretime girdi

Yukarıdaki hüküm ("hiçbir üretim dosyası değişmedi") o commit için doğruydu
ve öyle kalıyor. Bulguyu üretime taşımak, kendi barajını **kendi sonuçlarına
bakmadan önce** ilan eden ayrı bir faz olarak yapıldı.

**Sonuçlara bakılmadan sabitlenen üç karar**, gerekçeleri puan değil:

1. **`GDX`, `^HUI` değil.** İkisi dört hücrede de 0,01 IC içinde ölçüldü, yani
   bu bir performans seçimi **olamaz**. Gerekçe veri güvenilirliği: GDX işlem
   gören bir ETF, `^HUI` bir endeks — ve bu proje `^VXSLV`'yi tam olarak buna
   kaybetti (Yahoo tek satır döndürüyor). HUI belgelenmiş yedek olarak aday
   listesinde kaldı; ikisini birden göndermek canlı bağımlılığı bedavaya ikiye
   katlamak olurdu.
2. **Strateji, ensemble bileşeni değil.** Gerekçe yukarıda ölçülü: ufuk 1 gün,
   `ensemble.combine()` 5 günlük tahmin havuzluyor.
3. **`predictions` tablosuna yeni kolon yok** — migration tek bir `portfolios`
   insert'ine indi.

**Ölçek sabiti (`GDX_SCALE`), kod yazılmadan önce ölçüldü.** `|gdx_chg|`'in
p90'ı **iki panelde de beşinci haneye kadar aynı** (0,03973) — aynı seriyi
okuyorlar — yani `BOND_SCALE`/`VIX_SCALE` gibi modül sabiti, `assets.py`'ye
girmesi gereken bir şey değil. Bu, tahmin edilmedi, `compare.py`'nin
fiyat-türevli ölçekler için yaptığı testin aynısıyla ayrıldı.

`GDX_SCALE = 25,0` (= 1/p90) ve CLAUDE.md'nin zorunlu kıldığı **ikili**
kontrol — doyma oranı VE medyan |skor| birlikte:

| dönem | doyma | medyan \|skor\| | p90 \|skor\| |
|---|---|---|---|
| tam panel | %9,9 | 0,349 | 0,993 |
| eğitim yarısı | %12,3 | 0,402 | 1,000 |
| test yarısı | %7,4 | 0,310 | 0,907 |

Altı sayının altısı da diğer skorlayıcıların aralığında (doyma %5,7-13,7,
medyan 0,30-0,53), **ve iki yarıda da**. Tek başına doyma oranına bakmak
`real_yield_chg`'in medyan |skor|'u 0,009'a düşerken doymanın iyi görünmesine
yol açan arızanın kapısıdır.

**Kabul barajı, ilan edildiği hâliyle:** *`miners`, `buyhold`'u Calmar'da
hem 2bp hem 10bp basamağında, her iki metalde de geçecek. 40bp/150bp şart
değil — orada öldüğü zaten ölçüldü. Geçmezse tam geri alma.*

`python backtest.py`, 19,5 yıl (2007-03 → 2026-09), 4898 test günü:

| maliyet | altın `miners` | altın al-tut | fark | gümüş `miners` | gümüş al-tut | fark |
|---|---|---|---|---|---|---|
| COMEX 2bp | **0,38** | 0,23 | **+0,14** | **0,27** | 0,12 | **+0,15** |
| **ETF 10bp** | **0,32** | 0,23 | **+0,09** | **0,24** | 0,12 | **+0,12** |
| Perakende 40bp | 0,17 | 0,23 | −0,06 | 0,15 | 0,12 | +0,04 |
| Banka 150bp | −0,05 | 0,23 | −0,28 | −0,02 | 0,12 | −0,14 |

**Baraj geçildi**, dört hücrenin dördünde. Ve bu, `miners.py`'nin Bölüm 3'ünde
ölçülen sayılarla bağımsız olarak uyuşuyor (orada altın +0,100 / gümüş +0,126,
burada +0,09 / +0,12) — **farklı kod yolu, aynı cevap**, yani Bölüm 3'ün
kendi kural uygulaması ile üretimin `compute_target_exposure`'ı ayrışmıyor.
Zaten ayrışmamalıydı: sinyal stratejilerinin dalı tam olarak
`0,85 + 0,15×signed`'dir ve Bölüm 3 bunu bilerek taklit etmişti.

Altının ETF basamağında **iki tarafı birden** iyileştiriyor: YBG %10,8 vs
%10,3 **ve** maksimum düşüş %33,2 vs %44,4. Yani bu, 5. bölümün oynaklık
hedeflemesi gibi "getiriyi acıyla takas eden" bir kazanç değil.

**Ama yılda ~165 işlem yapıyor** (19,5 yılda 3225), ve merdivenin çökme sebebi
tam olarak budur: 150bp'de $1000'lık deftere **$2078 komisyon**. Banka gram
altınında bu sinyal para kaybettirir, ve ekranda öyle yazıyor.

**Üretim yüzeyi bilerek küçük tutuldu:** yeni `backend/miners_signal.py`,
`fetch_data.MACRO_SYMBOLS`'e `gdx`, `indicators.SIGNAL_ONLY_SERIES`,
`trading.STRATEGIES`, `predict.py`'nin strateji sözlüğü, `backtest.py`'nin
skor kolonu, `daily_report`/`app.js` etiketleri, ve `schema.sql`'de tek bir
portföy satırı. **Model hiç değişmedi** — özellik sayıları (altın 27, gümüş
25) ve eğitilebilir satır sayıları (5706/5707) birebir aynı, çünkü `gdx_chg`
`FEATURE_COLUMNS`'a girmedi.

Mevcut bir test bu işi yaparken **gerçek bir hata yakaladı**:
`test_daily_report.test_every_portfolio_that_exists_is_reported` kırmızı
yandı — yeni portföy günlük mailden sessizce düşecekti. Tam olarak o testin
var olma sebebi.

---

## 15. Sabit komisyon: cevabı sinyal değil, hesap büyüklüğü belirliyor (`backtest.py`)

Bu depodaki her maliyet sayısı **baz puan** cinsindeydi, yani işlem büyüklüğüyle
orantılı. Gerçek bir ETF aracı kurumu ise çoğu zaman **işlem başına sabit dolar**
alır, ve bu bambaşka bir şeklin maliyetidir: oransal ücret hesap büyüklüğüne
görünmezdir, sabit ücret ise **başka hiçbir şeye** bağlı değildir.

`backtest.Portfolio.step` artık isteğe bağlı bir `flat_fee` alıyor (varsayılan
0,0, yani yukarıdaki hiçbir sayı değişmedi) ve `flat_fee_ladder()` bunu
**işlem başına $1,50 + 1 bp makas** ile hesap büyüklüğüne karşı süpürüyor.

**Süpürmenin neden tam olduğu:** bu simülasyonda sabit ücret dışındaki her şey
ölçek-değişmezdir — yeniden dengeleme kararı bir **oran** okur, işlem
büyüklükleri defterin bir kesridir, oransal ücret işlemin bir kesridir.
Dolayısıyla $N nakitle ve $1,50 ücretle koşmak, standart $1000'lık defteri
$1,50 × 1000/N ücretle koşmakla **birebir aynıdır**. Kod ücreti süpürüyor,
başlangıç nakdini değil, böylece her özkaynak eğrisi raporun geri kalanıyla
aynı birimde kalıyor.

### Altın, 19,5 yıl, Calmar

| strateji | $1.000 | $5.000 | $25.000 | $100.000 | $500.000 |
|---|---|---|---|---|---|
| **`miners`** | **İFLAS** | 0,235 | **0,350** | **0,370** | **0,375** |
| `macro` | **İFLAS** | 0,186 | 0,257 | 0,270 | 0,273 |
| `voltarget` | 0,216 | 0,237 | 0,241 | 0,242 | 0,242 |
| `ml` | 0,172 | 0,231 | 0,243 | 0,245 | 0,246 |
| **`buyhold`** | **0,231** | 0,231 | 0,231 | 0,231 | 0,231 |
| `technical` | 0,118 | 0,215 | 0,232 | 0,236 | 0,237 |
| *efektif bp (tek yön)* | *170,6* | *11,7* | *2,6* | *1,4* | *1,1* |

Gümüş aynı şekli veriyor: `miners` $1.000'de iflas, $5.000'de 0,197 (al-tut
0,115), $25.000'de 0,254.

**`buyhold` her sütunda aynı** — bir kez işlem yapıyor, yani komisyon ona
dokunmuyor. Kıyas ölçütünün sabit kalması bu tablonun okunabilmesinin sebebi.

### İki tuzak, ikisi de ölçülerek yakalandı

**1. `nan` bir veri eksikliği değil, bir iflastır.** Sabit ücret bir defteri
**eksiye** düşürebilir — küçük bir satışta $1,50 gelirin kendisini aşar — ve
hiçbir oransal basamak bunu yapamaz. `metrics()` orada `nan` döndürüyordu
(negatif bir oranın kesirli kuvveti) ve `nan` basmak, silinmiş bir hesabı
"veri yok" diye raporlamak olurdu. `BUST` sentinel'i bunun için var, ve
`nan`-güvenli `_beats()` olmadan tablo "`miners` hiçbir yerde geçmiyor"
diyordu — geçtiği apaçık görünürken.

**2. Sezgisel bp çevirisi YANLIŞ, ve üç kat yanlış.** $1,50'yi mümkün olan
**en küçük** işleme bölmek cazip: `REBALANCE_THRESHOLD` %5, yani $5.000'lik
hesapta en küçük işlem $250, $1,50/$250 = 60 bp. Bu hesaba göre `miners`
$5.000'de al-ve-tut'a **kaybetmeliydi** (oransal merdivende 20 bp tek yönde
kaybediyor). Ölçüldüğünde efektif maliyet **11,7 bp**. Sebep: işlemler o
tabanda kalmıyor — pozisyon 0,70 ile 1,00 arasında salınıyor **ve defter
19,5 yılda bileşikleniyor**, yani geç işlemler çok daha büyük. Tablo bu yüzden
efektif bp'yi kendisi basıyor: okuyucunun bu çıkarımı yapmasına bırakılamaz.

### Doğrulama: iki merdiven aynı yerde buluşuyor

$500.000'de efektif maliyet 1,1 bp, yani neredeyse maliyetsiz — ve oradaki
`miners` Calmar'ı **0,375**, oransal merdivenin COMEX 2bp basamağındaki
**0,38** ile aynı. İki bağımsız maliyet modeli aynı sınıra yakınsıyor;
yakınsamasaydı biri hatalı olurdu.

### Sonuç

**Bu bir sinyal eşiği değil, bir hesap büyüklüğü eşiğidir.** Aynı sinyal,
aynı 3225 işlem, aynı 19,5 yıl:

- **$1.000** — komisyon defteri yiyor, **iflas**. `macro` da aynı kaderi
  paylaşıyor; ikisi de bu sistemin en çok işlem yapan stratejileri.
- **$5.000** — kıl payı geçiyor (0,235 vs 0,231). Alınmaya değmez.
- **$25.000** — net (0,350 vs 0,231).
- **$100.000+** — maliyetsiz sınıra oturuyor.

Ve buradan çıkan asıl iş sinyali iyileştirmek değil: `miners` yılda **165 kez**
işlem yapıyor ve bu sayının kendisi ölçülmüş bir tercih değil,
`REBALANCE_THRESHOLD = 0,05`'in yan ürünü. Maliyet-farkında bir yeniden
dengeleme eşiği — işlem beklenen kazancından pahalıysa işlem yapma — bu
tablonun tamamını sola kaydırırdı. Ölçülmedi, ve ölçülene kadar iddia
edilmiyor.

---

## 16. Madenci öncülüğü büyük ölçüde bir SEANS SINIRI etkisi (`miners.py` 4. bölüm)

14. ve 15. bölümlerin tamamı `GC=F` ve `SI=F` üzerinde ölçüldü — **COMEX vadeli
kontratları, yani hiçbir perakende hesabın tutamayacağı enstrümanlar.** Soru
"peki gerçekten alabildiğim şeyde ne oluyor" diye sorulduğunda cevap net çıktı
ve **14. bölümün pratik değerini ortadan kaldırıyor.**

### Ölçüm

| | lag 0 (eşzamanlı) | **lag +1 (tahmin eden)** | toplam |
|---|---|---|---|
| `GC=F` vadeli | +0,667 | **+0,150** | 0,817 |
| `GLD` ETF | +0,766 | **+0,040** | 0,806 |
| `IAU` ETF | +0,764 | +0,045 | 0,809 |
| `SI=F` vadeli | +0,595 | **+0,161** | 0,756 |
| `SLV` ETF | +0,699 | **+0,071** | 0,770 |

**Toplam korunuyor; değişen sadece bölünme.** Bu, tahmin edici bilginin değil,
bir **faz kaymasının** imzasıdır — ve iki metalde, üç ETF'te birden aynı yönde.

### Mekanizma

`GC=F`'in günlük mumu ~23 saat sürüyor: önceki gün 18:00 New York'ta başlıyor,
17:00'da bitiyor. `GDX`'inki 09:30–16:00. İki mum **aynı fazda değil.**
Vadelinin t+1 mumu, GDX kapandıktan **iki saat sonra** başlıyor — dolayısıyla
GDX'in t günündeki hareketine verilen tepkinin bir kısmı mekanik olarak
vadelinin t+1 mumuna düşüyor ve gün çözünürlüğünde **öncülük gibi okunuyor.**
GLD ise GDX ile **aynı anda**, 16:00'da kapanıyor; o yüzden aynı bilgi lag 0'da
kalıyor (+0,766) ve ertesi güne pek bir şey artmıyor (+0,040).

**`lags.py` bunu göremezdi ve bu bir kusur değil, kapsam farkı.** O dosya bir
**tam gün** takvim kayması arıyor ve doğru cevap veriyor (tepe lag 0'da, negatif
laglarda ağırlık yok). Burada olan şey **kısmi seans örtüşmesi** — gün
çözünürlüklü hiçbir tarama için görünür değil. `drivers.py`'nin kendi
docstring'indeki uyarının ("eşzamanlı korelasyon sinyal değildir") daha ince
taneli hâli.

### Ekonomik sonuç: satın alınabilir enstrümanda kazanç YOK

Üretimdeki `miners` kuralı, ETF'in **kendi** kapanışları üzerinde, işlem başına
$1,50 + 1 bp ile (20,3 yıl):

| GLD, hesap | `miners` son değer | al-ve-tut | fark |
|---|---|---|---|
| $5.000 | $12.096 | $30.370 | **−$18.274** |
| **$10.000** | **$37.964** | **$60.749** | **−$22.785** |
| $25.000 | $115.561 | $151.885 | −$36.324 |
| $100.000 | $503.696 | $607.568 | −$103.872 |

`IAU` aynı. `SLV` kısmen ayakta: $10.000'de berabere ($47.037 vs $46.535),
$25.000'de öne geçiyor ($143.041 vs $116.348) — gümüşün ETF lag+1'i (+0,071)
altınınkinin (+0,040) neredeyse iki katı olduğu için.

Gider oranı **modellenmedi** ve buna gerek yok: her iki kol da yatırımda
kaldıkları süreyle orantılı ödüyor, yani karşılaştırmada büyük ölçüde
sadeleşiyor — ve sadeleşmediği yerde `miners`'ın lehine (ortalama %85 pozisyon
vs %100).

### Üretimde ne değişti, ne değişmedi

**Strateji kaldırılmadı.** 14. bölümün ölçümü kendi şartlarında geçerli: bu
sistemin kâğıt portföyleri vadeli fiyatla değerleniyor (`fetch_data.get_live_price`
→ GC=F/SI=F) ve `backtest.py` de öyle. Vadeli işlem yapabilen biri için kazanç
gerçek. Ön-kayıtlı bir barajı, sonradan gelen bir bilgiyle geriye dönük iptal
etmek de bu tezgâhın kuralı değil.

**Ama arayüz metni değişti, çünkü yanlış okumaya davet ediyordu.** Kart artık
"ETF maliyetinde al-ve-tut'u geçiyor" demiyor — kazancın vadeli kontrata özgü
olduğunu, ETF'lerde kaybolduğunu ve **satın alınabilir bir strateji olmadığını**
söylüyor. Günlük mail de `miners` al-ve-tut'u geçtiği her hafta aynı dipnotu
basıyor; yoksa mail onu her iyi haftada birinci sıraya koyup tam olarak yanlış
sonuca davet ederdi.

### Bu, tek bir stratejiden büyük bir soru açıyor

**Bu depodaki HER strateji `GC=F`/`SI=F` üzerinde ölçüldü.** `miners` için
enstrüman farkının belirleyici olduğu artık ölçülü. Diğerleri için
ölçülmedi — ve beklenti farklı: `voltarget`'ın kazancı oynaklığın
otokorelasyonundan geliyor, ki bu enstrümandan bağımsız bir özellik;
`miners`'ınki ise doğrudan bir saat farkıydı. Ama "beklenti" bu tezgâhta bir
cevap değil. **Açık soru: `voltarget`, `technical`, `ml`, `macro` ve `ensemble`
GLD/IAU/SLV üzerinde al-ve-tut'u geçmeye devam ediyor mu?** Cevaplanana kadar
bu README'deki hiçbir Calmar sayısı "perakende bir hesapta böyle olurdu" diye
okunmamalı.

---

## 17. Tüm skorbord, alınabilir enstrüman üzerinde (`instrument.py`)

16. bölüm `miners` için enstrümanın belirleyici olduğunu gösterdi ve açık bir
soru bıraktı: **bu depodaki her sayı `GC=F`/`SI=F` üzerinde ölçüldü, ve hiçbir
perakende hesap COMEX vadeli kontratı tutamaz.** Bu bölüm skorbordun tamamını
`GLD`, `IAU` ve `SLV` üzerinde yeniden koşuyor.

**Ön-kayıt:** *"geçer" = ETF üzerinde, $10.000 hesapta, işlem başına $1,50 sabit
komisyonla al-ve-tut'u Calmar'da geçmek.* Her strateji her rungda raporlanır.

### İki metodolojik şart, ikisi de sonucu değiştiriyordu

**1. Sabitler devralınmadı, yeniden ölçüldü.** `assets.py`'nin bütün mesajı bu.
Üç fiyat ölçeği de bir **oran** normalize ediyor, o yüzden GLD'nin $403'ü ile
GC=F'in $4384'ü arasındaki 10 kat fark tanım gereği önemsiz — ama o oranların
oynaklığı ampirik bir soru, ve cevabı ölçüldü:

| seri | macd | ema_cross | sma200 | yıllık oynaklık | taban oran |
|---|---|---|---|---|---|
| `GC=F` | 173,1 | 51,9 | 6,53 | %18,1 | 0,557 |
| `GLD` | 171,9 | 50,8 | 6,25 | %18,3 | 0,553 |
| `IAU` | 170,8 | 50,7 | 6,22 | %18,3 | 0,548 |

Neredeyse birebir — **yani ETF farklı bir seri değil.** Bu önemli: aşağıdaki
farklar serinin kendi dinamiğinden değil, sinyallerle **ilişkisinden** geliyor.
(Ölçüm ayrıca üretimdeki 172,0/51,5/6,5 değerlerini yeniden üretiyor, yani
yöntem `compare.py` ile tutarlı.)

**`target_volatility` bilerek DEĞİŞTİRİLMEDİ** ve bu ayrımı kaçırmak
karşılaştırmayı sessizce geçersiz kılardı: o bir ölçüm değil, bir **risk
tercihi**. Altın %18,1 gerçekleştirip %15 hedefliyor, gümüş %33,7 gerçekleştirip
%28 — ikisi de gerçekleşenin ~%83'ü. Her seriye kendi oynaklığını hedefletmek
`voltarget`'ı iki sütunda **farklı bir strateji** yapardı.

**2. Ortak pencere zorunlu.** Serbest bırakılınca vadeli sütun 19,5 yıl, ETF
sütunu 16,1 yıl kapsıyordu — yani vadeli sütun 2008-2011 altın patlamasını
içeriyor, ETF sütunu içermiyor, ve bu **tek başına** al-ve-tut'un Calmar'ını
0,177'den 0,231'e çıkarıyordu. O iki sütunu karşılaştırmak **takvimi ölçüp
enstrüman diye raporlamak** olurdu. Her şey 2010-07-19 → 2026-09-09'a kısıtlı.

### Sonuç: Calmar sıralaması enstrümanla köklü şekilde değişiyor

$10.000 rungunda al-ve-tut'u geçenler:

| | vadeli | ETF |
|---|---|---|
| **altın** | `voltarget`, `ml`, `miners` | `voltarget`, `trend`, `defensive`, `ensemble` |
| **gümüş** | `voltarget`, `technical`, `macro`, `miners` | `voltarget`, `trend`, `defensive`, `ensemble`, `technical` |

- **Düşenler:** `miners` (iki metalde de — 16. bölümü ortak pencerede
  doğruluyor), `ml` (altın), `macro` (gümüş).
- **Sadece ETF'te geçenler:** `trend`, `defensive`, `ensemble` — üç ETF'te de.
- **Her yerde geçen tek strateji: `voltarget`.**

`voltarget`'ın enstrümandan bağımsız çıkması 5. maddenin en güçlü
doğrulamasıdır: kazancı oynaklığın **otokorelasyonundan** geliyor, ki bu
serinin kendi özelliğidir, bir saat farkı değil. `miners`'ınki bir saatti ve
saat değişince gitti.

### Ama Calmar para değildir, ve bu bölümün asıl uyarısı bu

GLD, $10.000, 16,1 yıl, işlem başına $1,50:

| strateji | son değer | YBG | Sharpe | maks düşüş | Calmar | işlem | komisyon |
|---|---|---|---|---|---|---|---|
| `voltarget` | **$36.257** | %8,3 | 0,59 | %39,2 | 0,212 | 131 | $215 |
| `defensive` | $29.815 | %7,0 | 0,60 | %33,6 | 0,209 | 234 | $476 |
| `ensemble` | $25.772 | %6,0 | 0,60 | %29,8 | 0,203 | 427 | $760 |
| **`buyhold`** | **$34.844** | %8,0 | 0,48 | %45,6 | 0,177 | 1 | $2 |
| `miners` | $20.990 | %4,7 | 0,33 | %44,7 | 0,105 | 2646 | $4.345 |

**Calmar'da al-ve-tut'u geçen dört stratejinin üçü, PARADA ondan geride.**
`defensive` ve `ensemble` Calmar'ı düşüşü keserek kazanıyor, para kazanarak
değil — 16 yılda sırasıyla $5.029 ve $9.072 daha **az** bitiriyorlar.

Geriye tek bir aday kalıyor ve onun da iddiası mütevazı: **`voltarget` 16 yılda
al-ve-tut'tan $1.413 fazla** (+%4, yani gürültü mesafesinde) ama maksimum düşüşü
%45,6'dan **%39,2'ye**, Sharpe'ı 0,48'den **0,59**'a taşıyor. Ve bunu **yılda
~8 işlemle** yapıyor ($215 toplam komisyon), yani elle uygulanabilir ve sabit
komisyona neredeyse duyarsız.

### Gümüş defteri de ölçüldü, ve aynı şeyi iddia etmiyor

SLV, $10.000, 16,1 yıl, işlem başına $1,50 (aynı pencere, `slv_books`):

| strateji | son değer | YBG | Sharpe | maks düşüş | Calmar | işlem | komisyon |
|---|---|---|---|---|---|---|---|
| `voltarget` | **$35.023** | %8,1 | 0,32 | %70,8 | 0,114 | 114 | $187 |
| `defensive` | $34.140 | %7,9 | 0,39 | %60,4 | 0,131 | 229 | $474 |
| **`buyhold`** | $33.286 | %7,7 | 0,24 | %76,3 | 0,101 | 1 | $2 |
| `trend` | $32.205 | %7,5 | 0,29 | %64,3 | 0,117 | 149 | $349 |

Aynı şekil, çok daha sert zeminde. **Gümüşün al-ve-tut düşüşü %76,3**, altınınki
%45,6 — `assets.py`'nin 25 yıllık tablosu canlı bir defterde. `voltarget`'ın
kestiği beş puan, altındaki altı puandan daha **büyük bir yaranın** üzerinde,
ve parada fark yine gürültü ($1.737).

Bir fark var: `defensive` burada al-ve-tut'u **hem** Calmar'da **hem** parada
geçiyor (GLD'de parada geride kalıyordu) — ama 229 işlemle ve tek bir sütunda,
yani bu bölümün kendi uyarısına tabi: 0,03'lük bir Calmar farkı tek başına
karar gerekçesi değildir.

**Dürüst özet: bu depoda $10.000'lik bir GLD ya da SLV hesabında al-ve-tut'tan
anlamlı şekilde daha fazla PARA kazandıran hiçbir şey yok.** Olan şey, aynı parayı
belirgin şekilde daha az acıyla kazandıran bir mekanizma — ve o mekanizma
5. maddenin en baştan beri söylediği şey.

### Açık uçlar

- `trend`/`defensive`/`ensemble` ETF'te **mutlak olarak** da iyileşiyor
  (`defensive` 0,172 → 0,208), sadece daha alçak bir bara karşı kazanmıyorlar.
  Sebebi ölçülmedi. Makul hipotez, ETF'in gece seansı olmaması ve boşlukların
  günlük mumun içinde farklı dağılması — ama bu bir hipotez, ölçüm değil.
- Bu bölümde Calmar farkları için anlamlılık testi **yok**. Üç ETF'te ve iki
  metalde tutarlı olması bu tezgâhın istediği tekrarlamadır, ama 0,03'lük bir
  Calmar farkı tek başına bir karar gerekçesi değildir.

---

## 18. Kırılım rejimi: emir akışı, çapalı VWAP, hacim profili (`flow.py`)

Talep açıktı: **bir kırılımda pozisyona gir, trend gerçekten kırılana ya da bir
stop seviyesine çarpana kadar tut.** Kararı üç şey versin — order flow, anchored
VWAP, volume profile — RSI/MACD/CCI/momentum/stokastik/Fibonacci da onaylasın.

Bu, bu depodaki her şeyden **yapısal olarak farklı** bir makine. Diğer her
strateji her seans sürekli bir pozisyonu yeniden nişanlıyor; bu kural bir
pozisyon alıp haftalarca içinde oturuyor. Dolayısıyla IC ile ya da 5 günlük
isabetle puanlanamaz: soru "yarın ne olacak" değil, **"aldığı pozisyon, kendi
çıkışına kadar tutulduğunda metali geçiyor mu"**.

> **Bu bölüm İKİ FAZ ve ÜÇ KOŞU taşıyor; hiçbiri silinmedi.** Aşağıdaki Bölüm
> 0–5 **Faz 1**'dir: sinyal `GLD`/`SLV` üzerinde kuruldu, çünkü Yahoo vadeli
> hacmi sunamıyordu. **Faz 2** aynı soruyu ikinci bir satıcıya sordu ve
> sinyali `COMEX:GC1!`/`SI1!`'e taşıdı. **Faz 2, 2026-09-17'de yeniden
> koşuldu**, çünkü ilk koşumdaki "bir tam seans gecikme" fiilen uygulanmıyordu
> — TradingView günlük barı seansın **açıldığı** günle damgalıyor, Yahoo
> kapandığı işlem günüyle, ve iki hata birbirini götürüyordu. Üç koşunun da
> hükmü aynı yönde; ama sayılar değişti ve **altının Calmar üstünlüğü
> kayboldu**. **Üretimde çalışan, yeniden koşulmuş Faz 2'dir.**

### Ön-kayıtlı baraj — sonuçlara bakılmadan ÖNCE yazıldı

17. bölümün `SURVIVES` tanımı, artı aynı bölümün var olma sebebi olan para şartı:

> **(1)** Alınabilir enstrümanda (GLD/SLV), $10.000 rungunda, örneklem dışı
> ikinci yarıda, **iki metalde de** Calmar'da al-ve-tut'u geçmek, **VE**
> **(2)** hiçbir metalde son sermayede al-ve-tut'un **%25 altına düşmemek**.

(2) şu yüzden var: **Calmar para değildir.** `voltarget` ölçülen her sütunda
Calmar'da al-ve-tut'u geçiyor ve 16 yılda $10.000'lik bir hesapta $1.413 fark
yaratıyor — gürültü. Zamanın %70'ini nakitte geçiren bir kural güzel bir Calmar
basıp metalin on yıllık sürüklenmesini sessizce geri verebilir, ve sadece
Calmar'ı basan bir arayüz bunu bir zafer diye ilan eder.

---

### Bölüm 0 — önce şunu ölç: bu projenin hacim serisi var mı? (Faz 1)

Order flow ve volume profile hacim enstrümanlarıdır. **Vadeli tarafta bu proje
kullanılabilir bir hacim serisine sahip değil**, ve iki seri **iki farklı
şekilde** düşüyor — bu yüzden `part0` üç test koşuyor. Tek test koşulsaydı
ikisinden birine temiz kâğıt verirdi:

**(A) Aynı oturum** — aynı sembol, iki farklı aralıkla ardarda. Dördü de geçiyor
(korelasyon 1,000). Bu, bu kontrolün "bariz" hâlidir ve **hiçbir şey yakalamaz.**

**(B) Oturumlar arası** — bugünün çekişi, diskteki panel anlık görüntüsüne karşı
(günler önce alınmış, **aynı 250 tarih**):

| sembol | aynı % | korelasyon | medyan (o gün) | medyan (bugün) |
|---|---|---|---|---|
| `GC=F` | **%3,6** | **−0,101** | 622 | 170.868 |
| `SI=F` | %99,6 | 1,000 | 182 | 182 |

**(C) Seviye makul mü** — istenen derinliğe göre medyan hacim:

| sembol | 2 yıl | 5 yıl | 10 yıl | 16 yıl | 25 yıl | sıfır gün (25y) |
|---|---|---|---|---|---|---|
| `GC=F` | 181.246 | 180.944 | 146.910 | **670** | **219** | 296 |
| `SI=F` | **124** | **66** | **54** | **51** | **40** | **627** |
| `GLD` | 9.275.400 | 7.439.100 | 7.614.000 | 8.059.050 | 7.939.600 | **0** |
| `SLV` | 21.713.100 | 20.091.200 | 16.482.000 | 13.764.250 | 11.327.700 | **0** |

**Okuma:** `GC=F` (B)'de düşüyor — aynı tarih, günler arayla iki farklı sayı.
Üzerine kurulan bir değer alanı her yeniden kurulumda **başka türlü** çıkar,
hiçbir yerde hata vermeden. (C) aynı arızanın derinlik eksenindeki hâli: altının
son yılları gerçek hacmi döner, derin geçmişi yüzleri. `SI=F` yalnızca (C)'de
düşüyor ama **her derinlikte**: COMEX gümüşü günde ~60 bin kontrat işliyor.

Bu yüzden Faz 1'de `flow_signal.py` **hacimle ilgili her şeyi ETF serisinden
okudu** (altın için GLD, gümüş için SLV) ve metali kendi fiyatıyla işledi.
(Faz 2 bunu değiştirdi — aşağıya bakın.) Deponun
sinyal girdisiyle enstrümanının bilerek ayrıldığı **tek** yer burasıdır — ve
16. bölümün dersi yüzünden Bölüm 4 kuralı **iki enstrümanda birden** koşuyor.

> **"Order flow" burada bir vekildir ve ismin kayması yasaktır.** Gerçek emir
> akışı tiktir: alış/satış kaldırmaları, bekleyen emir büyüklüğü, print başına
> delta. Bu projenin bir tik kaynağı yok ve olacak bir yolu da yok. Günlük
> mumun desteklediği şey kapanışın gün aralığındaki konumunun hacimle
> ağırlıklandırılmasıdır — yani **Chaikin para akışı**. Gerçek bir ölçüdür
> (günü kimin kapattığını söyler), emir defteri değildir, ve bu cümle olmadan
> arayüzde "emir akışı" yazmak ölçülenden fazlasını iddia etmektir.

---

### Bölüm 2 — dokuz enstrümanın hiçbiri tek başına yön taşımıyor (Faz 1)

Her enstrüman uzun/boş duruma indirgendi, ve **o varlığın kendi taban oranına**
karşı puanlandı (%50'ye karşı değil — bu metallerde %50'yi geçmek hiçbir şey
kanıtlamaz). Örtüşme düzeltmesiyle, 5 ve 20 günlük ufuklarda, iki metalde:

**36 hücrenin sıfırı** Bonferroni eşiğini geçti. Daha çarpıcısı: **hiçbiri
|t| = 1'e bile ulaşmadı.** En büyük mutlak t değeri 0,80.

| altın, 5 gün (taban %55,6) | isabet | fark | t |
|---|---|---|---|
| VAH kırılımı | %57,7 | +2,1p | 0,75 |
| akış (CMF>0) | %56,6 | +1,1p | 0,54 |
| AVWAP üstü | %55,7 | +0,1p | 0,09 |
| MOM>0 | %55,1 | −0,5p | −0,24 |

| gümüş, 5 gün (taban %52,3) | isabet | fark | t |
|---|---|---|---|
| CCI>100 | %54,7 | +2,4p | 0,75 |
| MOM>0 | %52,9 | +0,6p | 0,29 |
| VAH kırılımı | %52,3 | +0,1p | 0,02 |
| AVWAP üstü | %51,8 | −0,4p | −0,24 |

20 günlük ufukta altının VAH kırılımı +3,0 puan, gümüşünki **−5,2 puan** —
işaret metaller arasında ters dönüyor, ki bu tam olarak gürültünün imzasıdır.

**Ama bu tablo kuralı ölçmüyor, bileşenlerini ölçüyor** ve ayrımı yapmak şart:
bir kırılım kuralının iddiası "her uzun gün ortalamadan iyidir" değil, "tuttuğu
pozisyon, çıkışına kadar metali geçer"dir. Onu Bölüm 4 ölçüyor.

---

### Bölüm 3 — parametre seçimi, YALNIZCA ilk yarıda (Faz 1)

Üç parametre süpürüldü (giriş için gereken onay sayısı, stop genişliği, boşta
pozisyon), **18 hücre**. Altı osilatörün eşikleri süpürülmedi ve bu bilinçli: üç
yönlü bir ızgaranın üstüne altı yönlü bir eşik ızgarası koymak, saf gürültüde
kazanan bulmaya yetecek kadar büyük bir arama uzayıdır.

**İki metal farklı konfigürasyon seçti, ve farkın yönü öngörülebilir olandı:**

| | onay | stop | boşta | eğitim Calmar |
|---|---|---|---|---|
| altın (2005-05 → 2016-01) | ≥2 | **2,0σ** | **0,35** | 0,239 |
| gümüş (2006-10 → 2016-09) | ≥2 | **3,0σ** | **0,00** | 0,418 |

Gümüş altının **1,86 katı** oynak, yani 2σ'lık bir stop daha vahşi bir hayvanın
boynunda daha kısa bir tasmadır ve gürültüyle tetiklenir. Altının 2,0/0,35 çifti
gümüşün ızgarasında **18 hücrenin 14.'sü**. `assets.py`'de ayrı ayrı duruyorlar
(`BreakoutParams`), ve `test_flow_signal.py` ikisinin ayrı kalmasını kilitliyor.

Boşta pozisyonun iki metalde ters çıkması da anlamlı: altında **sert çıkış
kaybediyor** (0,231 vs 0,239), yani `trading.TREND_OFF_EXPOSURE = 0,35`'in
kaydettiği asimetri burada da görünüyor; gümüşte sert çıkış kazanıyor.

---

### Bölüm 4 — tek konfigürasyon, ikinci yarıda, bir kez (Faz 1)

**Altın** (GLD, 2016-2026, 64 giriş, zamanın %27'sinde pozisyonda, ortalama
tutuş 11 seans):

| basamak | kırılım | al-ve-tut |
|---|---|---|
| COMEX 2bp | 0,576 | 0,495 |
| **ETF 10bp** | **0,549** | 0,495 |
| Perakende 40bp | 0,452 | 0,495 |
| Banka 150bp | 0,154 | 0,495 |

**Gümüş** (SLV, 2016-2026, 38 giriş, %27, ortalama tutuş 18 seans):

| basamak | kırılım | al-ve-tut |
|---|---|---|
| COMEX 2bp | 0,119 | 0,232 |
| ETF 10bp | 0,110 | 0,232 |
| Banka 150bp | −0,009 | 0,232 |

Vadeli sütun aynı şekli veriyor (altın 0,588 vs 0,552; gümüş 0,148 vs 0,249),
yani **16. bölümün faz kayması burada yok** — kural zaten ETF serisinden
okuduğu için `miners`'ın düştüğü tuzağa yapısal olarak düşemiyor.

### Bölüm 5 — hüküm (Faz 1)

| metal | Calmar | al-tut | (1) | son $ | al-tut $ | fark | (2) |
|---|---|---|---|---|---|---|---|
| Altın | **0,566** | 0,495 | **EVET** | $24.556 | $37.163 | **−%33,9** | HAYIR |
| Gümüş | 0,116 | 0,232 | HAYIR | $16.488 | $31.275 | **−%47,3** | HAYIR |

**Baraj geçilemedi, ve iki farklı sebeple.** Gümüş her iki ölçüde de kaybetti.
Altın Calmar'da kazandı — düşüşü %27,6'dan %15,5'e indiriyor, bu depodaki en
büyük düşüş kesintisi — ama **$10.000'lik bir hesapta on yılda $12.607 daha az
para** bıraktı. Bu, 17. bölümün sayısının ($1.413) dokuz katı; "kazanılan şey
para değil sükûnet" cümlesi burada artık bir savunma değil, bir maliyettir.

**Sonuç:** `breakout` **`trading.STRATEGIES`'e girmedi**, `portfolios`'ta satırı
yok, `ensemble.COMPONENTS`'te yok, `ml_model.FEATURE_COLUMNS`'ta kolonu yok.
Üretime giren tek şey **bir panel** (`track_breakout.py` → `breakout_state` →
arayüzdeki `Kırılım Takibi` kartı) ve kartın üzerinde ölçüm tablosu yazıyor.
(Kartın bugün bastığı sayılar **Faz 2**'ninkilerdir — aşağıya bakın.)

`miners` emsalinin tersidir: orada sinyal gerçekti ve **üzerine para koymak**
pahalıydı; burada kural işliyor ve **doğrudan al-ve-tut'tan kötü**. İkisinde de
ekrana çıkan şey ölçümün kendisi.

### Neden panel yine de gönderildi

Üç sebep, ve hiçbiri "emek harcandı" değil:

1. **Durum gerçek bir tarif.** "Fiyat değer alanının %3 üstünde, AVWAP altında,
   akış negatif" cümlesi, bu kural hiç işlem yapmasa da piyasanın okunabilir bir
   tanımıdır. Sayfadaki hiçbir panel bunu söylemiyordu.
2. **Seviye bir sayı değildir.** "Fiyat $392, değer alanı $405'te bitiyor" bir
   aritmetik; aynı iki işaret tek eksende bir bakış.
3. **Değeri olumsuz ölçülmüş bir şeyi göstermek bu projenin işi.** `buyhold`
   ekranda gerçek bir portföy, `miners` kıyas rozetiyle duruyor; ölçülüp
   elenmiş bir kuralı görünmez kılmak bu disiplinin tersidir.


---

### Faz 2 — kaynak değişti, hüküm değişmedi (2026-09-16)

Faz 1'in panelinin ödediği bedel şuydu: **ons altın izleyen biri seviyeleri GLD
dolarında okuyordu** ($404,96). Sebep Bölüm 0'ın bulgusuydu — Yahoo vadeli hacmi
sunamıyor. Ama o bulgu "vadelinin hacmi yok" demek değildi; COMEX altında günde
~200 bin kontrat işliyor. Doğru soru "**bu satıcı** sunamıyor" idi, ve ikinci bir
satıcıya sorulmamıştı.

#### Bölüm 0, ikinci satıcı: TradingView

Aynı üç test, artık iki kaynakta. Ve önce spot, çünkü "ons altın" en doğrudan
XAU/USD demek:

| seri | 500 barda medyan hacim |
|---|---|
| `TVC:GOLD` | **0** |
| `TVC:SILVER` | **0** |
| `FX_IDC:XAUUSD` | **0** |
| `OANDA:XAUUSD` | 574.434 |
| `OANDA:XAGUSD` | 179.253 |

**Spot altının hacmi yok, ve bu bir satıcı sorunu değil.** XAU/USD tezgâh üstü
bir piyasadır; konsolide bir tape yoktur. OANDA bir sayı döner ve o sayı yanlış
olandır — tek bir perakende aracı kurumun kendi müşterilerinin tikleri. İkinci
bir aracı kurum başka bir sayı verirdi, ve hiçbiri "piyasa nerede işlem gördü"
olmazdı. Bir hacim profili tam olarak o iddiadır.

Vadeliye gelince:

| test | Yahoo `GC=F` | Yahoo `SI=F` | TV `COMEX:GC1!` | TV `COMEX:SI1!` |
|---|---|---|---|---|
| A) aynı oturum | geçer | geçer | geçer | geçer |
| B) aynı tarih, başka gün | **%3,6, r=−0,10** | geçer | geçer | geçer |
| C) seviye makul mü | 25 yılda **219** | **40–124** | 153.214–201.064 | 45.674–64.000 |

Ve yalnızca ikinci bir kaynağın cevaplayabileceği dördüncü soru:

| metal | hacim kor. | medyan TV | medyan Yahoo (taze) | kapanış kor. |
|---|---|---|---|---|
| altın | 0,619 | **176.514** | **176.343** | 0,9895 |
| gümüş | 0,001 | **57.776** | **168** | 0,9819 |

Altında iki bağımsız satıcı **seviyede** örtüşüyor — yani ikisi de aynı niceliği
ölçüyor. Gümüşte örtüşmüyor ve asıl mesele o: üç mertebelik bir uyumsuzluk
hangisinin yanlış olduğunu söyler. Günlük korelasyonun 0,619'da kalması ayrı bir
şey ve kayıt altına alınmalı: iki satıcının **sürekli kontrat dikişi** aynı değil
(kapanışlarda medyan mutlak fark %0,88). Bu, deponun zaten bildiği ve
CLAUDE.md'de kayıtlı olan farkın aynısı — arayüz `GC1!`'e marklıyor, backend
`GC=F` ile dolduruyor.

**Üstelik COMEX kontratı zaten `$/ons` kote ediliyor.** Yani kaynak değişimi iki
şeyi birden çözüyor: gerçek hacim, ve okuyucunun istediği birim.

#### İkinci ön-kayıt

Yeni veri kaynağı yeni bir deneydir; Faz 1'in hükmü devralınmaz. Baraj **aynı
bırakıldı**, değişen kurgu:

> Sinyal `COMEX:GC1!`/`SI1!` üzerinde kurulur. Alınabilir bacak sinyali
> `GLD`/`SLV`'ye **tam bir seans gecikmeyle** uygular: vadelinin mumu New York
> 17:00'da, ETF'inki 16:00'da kapanıyor, yani gecikmesiz bir ETF bacağı
> traderın sahip olmadığı bir saatlik bilgiyi harcardı — 16. bölümün `miners`
> altında bulduğu seans sınırı etkisinin aynısı, ve gün çözünürlüğünde
> görünmezi. Gecikme yalnızca **aleyhte** yanılabilir.
>
> Parametre süpürmesi **aynı kurgu üzerinde**, yalnızca eğitim yarısında
> puanlanır; seçim ile hüküm iki ayrı şeyi ölçmesin.
>
> Kıyas için bir vadeli-üstünde-vadeli sütunu basılır. **Hüküm o değildir**:
> hiçbir perakende hesap COMEX kontratı tutamaz.

#### Sonuç: aynı cevap, biraz daha kötü

| metal | Calmar | al-tut | (1) | son $ | al-tut $ | fark | (2) |
|---|---|---|---|---|---|---|---|
| Altın | **0,520** | 0,463 | **EVET** | $20.548 | $35.284 | **−%41,8** | HAYIR |
| Gümüş | 0,154 | 0,236 | HAYIR | $17.996 | $32.715 | **−%45,0** | HAYIR |

Faz 1'de altının para açığı %33,9'du, şimdi %41,8. **İki satıcı, iki enstrüman,
aynı cevap** — ve bu, iki koşunun her birinden ayrı ayrı daha değerli: başarısızlık
kuralın, bir veri artefaktının değil.

Üç yan bulgu:

- **İki metal artık AYNI parametreleri seçti** (onay≥2, 2,0σ, sert çıkış).
  *(Bu bulgu yeniden koşumda düştü: hizalama düzelince gümüş onay≥4'e,
  iki metal birden 0,35 tabana geçti. Aşağıya bakın.)*
  Faz 1'de gümüş 3,0σ ve gold 0,35 taban seçmişti. Gerçek COMEX hacmi ETF'inkinin
  yerine geçince iki ızgara aynı hücreye oturdu. **Ayrı ayrı ölçülmüş aynı sayılar
  sorun değildir; kopyalanmış aynı sayılar sorundur**, ve ikisi dışarıdan ayırt
  edilemez — ölçüm bu yüzden her birinin yanındaki yorumda duruyor.
  `test_flow_signal.py`'nin "ikisi farklı olmalı" testi bu yüzden **düştü ve
  yeniden yazıldı**: bir ölçümün sonucunu çiviyle tutturan bir bekçi, ölçüm
  yeniden koşulduğunda — yani tam susması gereken anda — kırılır.
- **Gecikmeli ETF bacağı, vadeli bacağından İYİ** (altında Calmar 0,531 vs
  0,429, 2bp'de). Beklenmedik ve açıklanmadı; makul hipotez sinyalin oluştuğu
  mumun kendisinde işlem yapmamanın bir maliyeti olmadığı, ama bu bir hipotez.
  **Açıklaması 2026-09-17'de bulundu ve hipotez değildi: gecikme yoktu.**
  "Muhafazakâr olması gereken bacağın kazanması" gizli bir ileri bakışın
  dışarıdan göründüğü şeydir — bir sonraki sefere bu, açıklanmayı bekleyen
  bir merak değil, **doğrudan bir hizalama şüphesi** olarak okunmalı.
- **Bölüm 2'de `akış` işaret değiştirdi**: GLD'de +1,1 puan, COMEX'te −1,3 puan
  (altın, 5 gün). Enstrüman değişince işaretin dönmesi, o hücrenin gürültü
  olduğunun ayrı bir kanıtı.

#### Faz 2 yeniden koşuldu (2026-09-17): ilan edilen gecikme uygulanmıyordu

**Arıza tek bir satırdaydı, iki yerde birden hasar verdi ve ikisi birbirini
gizledi.** `tv_history.daily()` TradingView'in ham damgasını olduğu gibi
kullanıyordu. TradingView günlük vadeli barı seansın **açıldığı** anla
damgalıyor (NY 18:00); Yahoo ve CME **kapandığı işlem günüyle**. Aynı değerler,
bir gün kaymış etiket:

| kapanış | Yahoo `GC=F` | TV `COMEX:GC1!` |
|---|---|---|
| 4.332,8 | 2026-09-15 | 2026-09-14 |
| 4.387,5 | 2026-09-16 | 2026-09-15 |
| 4.408,2 | 2026-09-17 | 2026-09-16 |

Üç sonucu oldu:

1. **`drop_forming_bar` hiçbir şey düşürmüyordu.** Guard, barın kendi takvim
   gününü borsanın saatine karşı okuyor; açılış damgalı bir bar için o test
   **bir tam seans erken**. Canlı ölçüldü (2026-09-17 12:51 UTC, seans açıkken):
   **0 satır düştü**. Yani `track_breakout.py` her gece **bir saatlik yarım
   barı** son kapanmış seans diye yayımlıyordu — `breakout_state`'in
   2026-09-16 satırı **4.309,1** taşıyor, o seansın gerçek kapanışı **4.408,2**
   — ve 2026-09-16'dan beri defter kararını da onun üzerinde veriyordu. Pencere
   her koşuda yeniden yazıldığı için panel ertesi gün kendini düzeltiyor;
   **bir dolum düzelmez.** Bu, 25 yıllık panelde aynı hatayı önlemek için
   yazılmış guard'ın, ikinci satıcı kapısından geri gelmiş hâli.
2. **Alınabilir bacağın "bir tam seans gecikmesi" yoktu.** `flow_frame` ETF
   kapanışını barın etiket gününe bağlıyor; açılış damgasına bağlanınca bu,
   vadeli bar daha **başlamadan önceki** ETF kapanışı oluyor — ve `lagged()`'in
   bir satırlık kayması hatayı tam olarak geri alıyordu. Net etki: NY 17:00'da
   bilinen sinyal, **aynı günün 16:00 ETF kapanışında** işleniyordu. 16. bölümün
   `miners` altında bulduğu seans sınırı artefaktının ta kendisi, bu kez onu
   önlemek için yazılmış önlemin içinde.
3. **"İki satıcının sürekli kontrat dikişi farklı" bulgusu artefaktmış.** Ham
   tarihlerle eşleştirilmiş iki seri arasındaki fark günlük getirinin kendisidir
   (altında medyan %1,04); doğru hizalandığında **altın %0,000** (250 seans),
   gümüş **%0,457** — yani gümüşte gerçek bir dikiş farkı var, altında yok.
   `lags.py`'nin var olma sebebi olan hatanın aynısı, bu kez iki satıcı arasında.

**Düzeltme tek yerde:** `tv_history.to_trade_dates()` damgayı seansın kapandığı
işlem gününün NY gece yarısına taşıyor — `fetch_data`'nın tamamlanmış bir Yahoo
barını damgaladığı yerin aynısı. Böylece guard, ETF birleştirmesi, `session_date`
etiketleri ve iki satıcılı her karşılaştırma aynı anda düzeliyor.
`tests/test_data_hygiene.py` beş testle kilitliyor: akşam damgası kayar, gündüz
damgası kaymaz, DST sınırında tarih bozulmaz, damga Yahoo'nunkiyle aynı biçimde
gelir, ve **oluşmakta olan bar düşer**.

##### Yeniden koşum: aynı ön-kayıt, aynı bölme, gerçek gecikme

| metal | seçilen konfigürasyon | Calmar | al-tut | (1) | son $ | al-tut $ | fark | (2) |
|---|---|---|---|---|---|---|---|---|
| Altın | onay≥2, 2,0σ, boşta %35 | 0,452 | 0,460 | **HAYIR** | $22.151 | $35.012 | **−%36,7** | HAYIR |
| Gümüş | onay≥4, 2,0σ, boşta %35 | 0,146 | 0,230 | **HAYIR** | $18.811 | $31.935 | **−%41,1** | HAYIR |

**Altının Calmar üstünlüğü ileri bakıştan geliyormuş.** İlk koşumda (1)'i
geçiyordu (0,520 vs 0,463); gecikme gerçekten uygulandığında 0,452 vs 0,460.
Bu kural artık **iki metalde de, iki ölçüde de** al-ve-tut'un gerisinde — Faz
1'den bu yana ilk kez hiçbir hücrede kazanmıyor. Para açığı ise **azaldı**
(%41,8 → %36,7): ileri bakış Calmar'ı şişirirken parayı şişirmiyordu, çünkü
kazandırdığı şey iyi zamanlanmış çıkışlardı.

Parametreler de değişti ve bir önceki koşumun yan bulgusunu düşürdü: **iki metal
artık aynı hücrede değil** (gümüş dört onay istiyor, altın iki), ve **ikisi de
sert çıkışı bırakıp %35 tabanı seçti** — `trading.TREND_OFF_EXPOSURE`'ın 0,35
olmasıyla aynı aile, `defense.py`'nin ölçtüğü "dipte tamamen satmak düşüşü
artırır" bulgusu.

##### Defter, ölçülen konfigürasyonu koşmuyor — ve bu ekranda yazılı

Süpürme boşta %35 seçti; `breakout_trading.py` ise tam giriş / tam çıkış, çünkü
"kırılana kadar tut" bir kesir olarak ifade edilemiyor. Yani $1.000'lık defter,
barajın yargıladığı kuralın **sert çıkış kardeşini** koşuyor. Aynı test yarısında,
aynı rungda ölçüldü (`flow.py` Bölüm 5, baraja **dahil değil**):

| metal | defterin varyantı | al-tut | son $ | al-tut $ | fark |
|---|---|---|---|---|---|
| Altın | 0,341 | 0,460 | $17.072 | $35.012 | **−%51,2** |
| Gümüş | 0,053 | 0,230 | $12.995 | $31.935 | **−%59,3** |

Defterin kutusunun altındaki cümle bu tabloyu basıyor. Alternatif — kartın
hükmünü defterin yanında da göstermek — defterin koşmadığı bir kuralın sayısını
onun performansı gibi okutmak olurdu; bu kartın var olma sebebinin tam tersi.
Barajın hangi varyantı yargıladığı **değiştirilmedi**: iki kardeşten iyi olanı
sonradan seçmek, ön-kaydın önlemek için var olduğu şeydir.

##### Ders: iki hata birbirini götürdüğünde ortaya bir *sonuç* çıkar

Tek başına her biri fark edilirdi — yayımlanan yarım bar bir gün içinde göze
çarpardı, gecikmesiz bir bacak ise "çok iyi" görünürdü. Birlikte, **makul bir
tablo** ürettiler. Gösterge, ilk koşumun "açıklanamadı" diye kaydettiği yan
bulguydu: *muhafazakâr olması gereken gecikmeli bacak, gecikmesiz vadeli bacağı
geçiyordu.* Bu depoda bundan sonra o cümle bir merak değil, doğrudan bir
**hizalama şüphesi** olarak okunmalı.

### Açık uçlar

- **Fibonacci yalnızca gösteriliyor.** %61,8 uzantısı bir kâr-al seviyesi olarak
  **test edilmedi**, çünkü kazanan bir trendi kapatan bir hedef "kırılana kadar
  tut"un tam tersidir. Test edilecekse ayrı bir ön-kayıt gerekir.
- **Giriş yalnızca UZUN.** VAL'in altına düşen kapanış bir kısa sinyali olarak
  ölçülmedi; bu sistem kısa pozisyon almıyor (8. bölümdeki oranla aynı kısıt).
- **Kuralın kendisi süpürülmedi, sadece üç parametresi.** "VAH yerine POC
  kırılımı", "onayları ağırlıklandır", "hacim artışı şartı" gibi varyantlar
  ölçülmedi — ve Bölüm 2 göz önüne alındığında bunların bir yerden IC çıkarması
  için önce Bölüm 2'nin tablosunun değişmesi gerekir.
- **Bölüm 2 negatifinin gücü yazılmadı.** Tablo "hiçbiri geçmedi" diyor; bu
  örneklemin görebileceği en küçük farkın ne olduğu (`ablation.min_detectable_ic`
  ailesinden bir sayı) hesaplanmadı. |t| değerlerinin hepsinin 0,8'in altında
  olması bunu daha az acil kılıyor ama kapatmıyor.

---

## 19. ML bileşeninin yön eşiği: 0,5 mi, taban oran mı? (`threshold.py`)

Bu depo taban oranı hemen her yerde düzeltiyor: `ensemble.py` kanıtı ona karşı
olabilirlik oranıyla havuzluyor, `calibration.py` isotonic'i ona çapalıyor,
mail ve arayüz `edge_over_base` basıyor, ve `edge.py`'nin kendi başlığı "%50'yi
geçmek hiçbir şey kanıtlamaz" diyor.

Bir yer düzeltmiyordu. `ml_model.ml_signal`:

```python
direction = "UP" if proba_up >= 0.5 else "DOWN"
```

Model bir **olasılık** üretiyor ve prior biliniyor (altın 0,557). Modelin 0,52
dediği bir gün, boş bir tahminden **daha az** yükseliş beklediği gündür — ve
bileşen onu YÜKSELİŞ diye raporluyordu. `edge.py` de aynı 0,5'te puanlıyor.

Bunun burada özel bir ağırlığı var: `ensemble.combine` bir bileşenin **işaretini**
ve geçmiş sicilini okuyor, günlük güven büyüklüğünü hiç okumuyor. Yani modelin
olasılığının havuza tek kanalı, eşiğin hangi tarafına düştüğü. Eşik prior'ın
yanlış tarafındaysa UP kovası prior-altı günlerle sulanır — ki bu tam olarak
`component_evidence`'ın doğru şekilde ~0 döndürdüğü ve bileşenin sustuğu durum.

### Ön-kayıt — ilk koşumdan önce yazıldı

Eşik, AYNI yürüyen-ileri satırlarında, **iki metalde birden**: (1) iki taraf da
kendi bilgisizlik noktasını geçmeli, (2) prequential Brier becerisi hem pozitif
hem 0,50'ninkinden yüksek olmalı, (3) küçük taraf en az 200 kez konuşmalı.

### Sonuç

| metal | eşik | UP der | P(up\|UP) | fark | z | DOWN der | P(dn\|DN) | fark | z |
|---|---|---|---|---|---|---|---|---|---|
| altın | 0,50 | 3679 | %55,61 | +0,39 | 0,21 | 1214 | %45,96 | +1,19 | 0,37 |
| altın | **0,552** | 2496 | %57,29 | **+2,07** | 0,93 | 2397 | %46,93 | **+2,16** | 0,95 |
| gümüş | 0,50 | 3233 | %52,83 | +0,30 | 0,15 | 1661 | %48,04 | +0,58 | 0,21 |
| gümüş | **0,525** | 2705 | %52,94 | +0,41 | 0,19 | 2189 | %47,97 | +0,50 | 0,21 |

Prequential Brier becerisi (yalnızca prior = 0): altın −%0,016 → **+%0,121**,
gümüş −%0,032 → −%0,030.

**Baraj GEÇİLEMEDİ ve eşik 0,5'te kaldı.** Altında üç şartın üçü de geçiyor —
iki tarafın da kaldıracı üç katına çıkıyor ve beceri negatiften pozitife
dönüyor. Gümüşte beceri hâlâ **negatif**: şart (2) "pozitif VE daha yüksek"
diyordu, "daha az kötü" demiyordu. Bu tezgâhın kuralı bir metalde çıkıp
diğerinde çıkmayan sonucu benimsememektir (13. bölümdeki oynaklığa bölme
açık ucunun aynısı).

**Ve negatifin gücünü yazmak şart:** z değerlerinin **hiçbiri 1,0'a ulaşmıyor**
(en büyüğü 0,95). Örtüşme düzeltmesinden sonra etkin gözlem ~980 ve bu
örneklemin ayırt edebileceği en küçük fark ~3 puan; ölçülen 2,07. Yani çalışma
"taban oran eşiği belirgin şekilde daha iyi" **diyemiyor**, ama "daha kötü"
de diyemiyor. Doğru okuma: **işaret tutarlı, kanıt yetersiz.**

Tekrar bakılması için iki tetik yazılı olsun:
- **Canlı sicil 300 çözülmüş satırı geçtiğinde.** O zaman soru simülasyon değil
  ölçüm olur, üstelik `model_state`'in dört sayacı zaten tam bu ayrımı tutuyor.
- **`ensemble` bir gün büyüklüğü de okumaya başlarsa** eşik sorusu kendiliğinden
  düşer: olasılık havuza doğrudan girer ve kesme noktası kalmaz.

> Yan bulgu, kayıt için: modelin olasılık dağılımı prior'ın etrafında oturuyor
> (altın ortalama %55,7, medyan %55,4 — `assets.py`'deki 0,557'nin üstüne
> neredeyse birebir). Bu, 7. bölümün "taban oran öğrenilebilir olan tek şey"
> bulgusunun bağımsız bir doğrulaması: model prior'ı öğrenmiş, üstüne az şey
> koymuş.
