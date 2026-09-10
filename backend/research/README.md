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
| `panel.py` | Her metal için 25 yıllık + 13 makro + 9 **aday** serilik günlük panel kurar, `panel_<varlık>.json`'a önbelleğe alır (~1 dk, gitignore'da). Adaylar (`CANDIDATE_SYMBOLS`) canlı yolda **yok** — 12. bölüm |
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
