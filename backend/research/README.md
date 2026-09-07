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
| `panel.py` | Her metal için 25 yıllık + 13 makro serilik günlük panel kurar, `panel_<varlık>.json`'a önbelleğe alır (~30 sn, gitignore'da) |
| `wall.py` | Başabaş duvarı: ufka ve maliyete göre gereken yön isabeti |
| `drivers.py` | 16 makro serinin eşzamanlı (açıklayan) vs öncü (tahmin eden) etkisi |
| `lags.py` | Bir "öncü" sürücü gerçekten öncü mü, yoksa takvim kayması mı |
| `edge.py` | Yürüyen-ileri yön testi: 1/5/20 günlük ufuklarda, üç ölçüte karşı |
| `defense.py` | Yön tahmin etmeden düşüşü azaltabilir miyiz (trend + oynaklık kuralları) |
| `tilt.py` | Model yön seçemiyorsa, pozisyon **boyutunu** eğebilir mi |
| `season.py` | Altının takvim etkileri (ay, hafta günü, ay dönümü) |
| `compare.py` | Gümüşü altına karşı ölçer; `assets.py`'deki her sayı buradan gelir |
| `ratio.py` | Altın/gümüş oranı: ortalamaya dönüş, rotasyon, çift tutma, ve `gs_ratio_z`'nin modele katkısı |
| `ablation.py` | ML bileşeni taban orana neden takılıyor — etiket mi, özellikler mi |

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
```

`panel.py` argümansız çalıştırılınca **her iki metal için de** panel kurar
(`panel_gold.json`, `panel_silver.json`). Diğer dosyalar varsayılan olarak
altını okur; `backtest.py silver` gibi bir argümanla gümüşe çevrilebilir.

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
