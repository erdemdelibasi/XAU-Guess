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
  -> backend/track_etf.py     predict.py ile AYNI adımda, hemen sonrasında --
                              alınabilir ETF defterleri (assets.TRACKED).
                              Model yok, LLM yok, makro panel yok: sadece
                              fiyat geçmişi ve trading.MECHANICAL.
  -> backend/track_breakout.py  aynı adımda, track_etf'ten sonra -- Kırılım
                              Takibi panelinin durumu (breakout_state) VE o
                              kuralın kendi $1000'lık defteri
                              (breakout_trading.py, metal başına bir tane,
                              2026-09-16'da açıldı). Kural ön-kayıtlı barajı
                              GEÇEMEDİ (research/README.md 18. bölüm); defter
                              bunu canlı göstermek için var, kopyalanmak için
                              değil. `breakout` yine de trading.STRATEGIES'te
                              YOK -- tam giriş/çıkış, hedef pozisyon değil.
                              Hacmi TradingView'den COMEX:GC1!/SI1! olarak
                              okur (tv_history.py), çünkü Yahoo o kontratların
                              hacmini sunamıyor -- ve o kontrat $/ons kote.
  -> backend/daily_report.py  her iş günü 06:00 UTC (09:00 TRT) -- günlük
                              özet maili; hiçbir şey yazmaz, sadece okur
  -> backend/export_backtest.py  ELLE, cron YOK -- backtest'in sermaye
                              eğrilerini frontend/data/backtest.json'a yazar.
                              Bir parametre değiştirdiğinde yeniden koş ve
                              JSON'u AYNI commit'te ver (bkz. aşağıdaki
                              "Ölçülmüş geçmiş" bölümü)

Kullanıcının kendi bilgisayarı (Windows Task Scheduler -- GitHub Actions DEĞİL,
bkz. aşağıdaki Kanal Finans notu)
  -> ../Kanal-Finans-Fetcher/fetcher.py    01:00/07:00/13:00/19:00 -- YouTube'dan TEK çekiş,
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
   boyutlandırma — ve bu, ALINABİLİR enstrümanda da ayakta kalan TEK şey.**
   19,9 yıl örneklem dışı: Sharpe 0,58→0,64, maksimum düşüş %44,4→%30,1,
   karşılığında 2,1 puan yıllık getiri. `research/instrument.py` skorbordun
   tamamını `GLD`/`IAU`/`SLV` üzerinde, ortak pencerede ve sabit komisyonla
   yeniden koştu: `voltarget` **her sütunda** (vadeli ve ETF, altın ve gümüş)
   al-ve-tut'u Calmar'da geçiyor. Geçen başka hiçbir strateji bunu yapamıyor.
   Sebep de tutarlı: kazancı oynaklığın **otokorelasyonundan** geliyor, ki bu
   serinin kendi özelliğidir. 10. maddedeki `miners`'ınki bir **saat farkıydı**
   ve saat değişince gitti (16. bölüm).

   **Ama Calmar para değildir, ve bu ayrım bu projenin en pahalı dersidir.**
   $10.000'lik bir GLD hesabında 16,1 yılda: `voltarget` $36.257, al-ve-tut
   $34.844 — **fark $1.413, yani gürültü mesafesinde**. Kazanılan şey para
   değil, sükûnet: maksimum düşüş %45,6 → %39,2, Sharpe 0,48 → 0,59, ve bunu
   **yılda ~8 işlemle**. Calmar'da al-ve-tut'u geçen diğer üç strateji
   (`trend`, `defensive`, `ensemble`) **parada ondan geride** — düşüşü keserek
   kazanıyorlar. **Bu depoda $10.000'lik bir hesapta al-ve-tut'tan anlamlı
   şekilde daha fazla PARA kazandıran hiçbir şey yok.** `research/README.md`
   17. bölüm.
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
9. **Piyasanın kendi oynaklık tahmini bizimkinden belirgin şekilde iyi — ama
   bu Calmar'a çevrilemedi.** GVZ (`^GVZ`, altının ima edilen oynaklığı)
   gelecek 60 günün gerçekleşen oynaklığını r=0,588 / RMSE 5,34p ile
   kestiriyor; üretimin geçmişe bakan rv60'ı r=0,501 / 6,29p. Kapsama
   testinde (örtüşmeyen alt örneklem) GVZ t=+3,12 alırken **rv60 onun yanında
   hiçbir şey katmıyor** (t=+0,14). Buna rağmen `trading.py` DEĞİŞMEDİ:
   ağırlık ızgarasını eğitim ve test yarıları **tam ters** sıralıyor
   (Spearman −1,00), yani bölme soruyu çözmedi, bir rejim değişimini ikiye
   ayırdı. `research/README.md` 12. bölüm.
10. **Altın madencileri metali gerçekten öncülüyor — ve bu, bu depoda yön
    tarafında ÜRETİME GİREN ilk bulgudur.** `GDX` her iki metalde de örneklem
    dışı Bonferroni eşiğini geçti ve **yedi** öldürme denemesinden sağ çıktı:
    hizalama taraması, gümüş kontrol serisi, düz mum artefaktı, metalin kendi
    getirisi (kontrol edilince ilişki zayıflamıyor **güçleniyor**: r=+0,151 →
    kısmi **+0,206**), ve `miners.py`'nin üç ekonomik kontrolü — sabit-ortalama
    pozisyon, 5 gün bayat sinyal, metalin kendi momentumu. Son üçü kritikti:
    kural al-ve-tut'tan az metal tutuyor ve **daha az tutmak tek başına
    Calmar'ı yükseltir**, yani gürültüyle bile kazanmış görünürdü. Sabit-ortalama
    kolu her hücrede al-ve-tut'la aynı çıktı (±0,02), diğer ikisi al-ve-tut'un
    **altında** kaldı.

    **Ufuk 1 GÜN, ve bu bir ayrıntı değil, mimari bir kısıt.** Bilginin tamamı
    t+1'de, t+2'den itibaren hiçbir şey yok. `edge.walk_forward`'ın eşleştirilmiş
    A/B'sinde 1 günlük ufukta katkı **+0,079..+0,097 IC, dört hücrenin dördünde
    p=0,000** (altın +0,0447 → **+0,1416**, bu deponun ölçtüğü en yüksek IC);
    5 günlük ufukta ayırt edilemiyor (p=0,13 / p=0,99). Bu yüzden `miners`
    **`ensemble.COMPONENTS`'te DEĞİL**: `ensemble.combine()` 5 günlük bir tahmin
    havuzluyor, 1 günlük bir oyu oraya koymak farklı bir soruyu tam ağırlıkla
    cevaplatmak olurdu. Kanal Finans'ın dışarıda tutulmasıyla aynı aile.
    Üretime **yalnızca strateji** olarak girdi. Aynı sebeple `gdx_chg`
    `ml_model.FEATURE_COLUMNS`'a **konmadı** — 5 günde ölçülebilir katkısı yok
    ve `build_feature_frame` NaN satırı düşürdüğü için panelin %18,6'sına mal
    olurdu. `tests/test_miners_signal.py` bu üç sınırı da kilitliyor, ve özellik
    sayıları değişmedi (altın 27, gümüş 25; eğitilebilir satır 5706/5707).

    **Benimseme barajı sonuçlara BAKILMADAN önce ilan edildi**: "`miners`,
    `buyhold`'u Calmar'da hem 2bp hem 10bp basamağında, her iki metalde de
    geçecek". `backtest.py`, 19,5 yıl:

    | | altın miners | altın al-tut | gümüş miners | gümüş al-tut |
    |---|---|---|---|---|
    | COMEX 2bp | **0,38** | 0,23 | **0,27** | 0,12 |
    | **ETF 10bp** | **0,32** | 0,23 | **0,24** | 0,12 |
    | Perakende 40bp | 0,17 | 0,23 | 0,15 | 0,12 |
    | **Banka 150bp** | **−0,05** | 0,23 | **−0,02** | 0,12 |

    Altının ETF basamağında **iki tarafı birden** iyileştiriyor: YBG %10,8 vs
    %10,3 **ve** maksimum düşüş %33,2 vs %44,4.

    **Ama yılda ~165 işlem yapıyor** (19,5 yılda 3225), ve merdivenin çökme
    sebebi budur: 150bp'de $1000'lık deftere $2078 komisyon. **Banka gram
    altınında bu sinyal para kaybettirir.** 7. maddedeki `macro` bileşeninin
    aynısı — gerçek bir sinyal, üzerine para koymanın pahalı olduğu bir sinyal.
    Ekranda al-ve-tut'un yanında, kıyas rozetiyle duruyor.

    `GDX` bu yüzden `fetch_data.MACRO_SYMBOLS`'e girdi ve **bunu yapan tek
    seridir**; yolu `research/panel.py`'nin başlığında yazılı ve tek yön var:
    `drivers.py`'nin Bonferroni eşiği → `lags.py`'nin hizalama taraması →
    `miners.py`'nin maliyet merdiveni. `^HUI` aday olarak kaldı (ikisi 0,01 IC
    içinde ölçüldü; ikisini birden göndermek canlı bağımlılığı bedavaya
    ikiye katlamak olurdu) ve belgelenmiş yedektir.

    **AMA aynı gün ölçüldü ki bu kazanç VADELİ KONTRATA ÖZGÜ.** Aynı kural,
    alınabilir ETF'lerin kendi kapanışları üzerinde koşulunca kayboluyor: öncü
    korelasyon `GC=F`'te +0,150 iken `GLD`'de **+0,040**, `SI=F`'te +0,161 iken
    `SLV`'de +0,071 — ve **lag0 + lag+1 toplamı sabit kalıyor**, yani bilgi
    yok olmuyor, "bugün"e geri kayıyor. Sebep bir faz kayması: `GC=F`'in günlük
    mumu ~23 saat (önceki gün 18:00 → 17:00), `GDX`'inki 09:30–16:00; vadelinin
    t+1 mumu GDX kapandıktan **iki saat sonra** başlıyor, `GLD` ise GDX ile
    **aynı anda** kapanıyor. $10.000'lik hesapta GLD üzerinde `miners`
    al-ve-tut'a **$22.785 kaybediyor**. `lags.py` bunu göremezdi: o **tam gün**
    kayması arar, bu ise **kısmi seans örtüşmesi**. Strateji kaldırılmadı
    (kâğıt portföyler vadeli fiyatla değerleniyor, ölçüm kendi şartlarında
    geçerli) ama **arayüz kartı ve günlük mail artık satın alınabilir olmadığını
    açıkça yazıyor**. `research/README.md` 14. ve **16.** bölüm.

11. **Kırılımda girip trend kırılana kadar tutan kural ölçüldü ve baraja
    takıldı — ama asıl bulgu ondan önce geldi: HACİM SERİSİNİN KENDİSİ
    ÖLÇÜLMEDEN KULLANILAMAZ.** Order flow ve volume profile hacim
    enstrümanlarıdır, ve `research/flow.py`'nin ilk işi hacmin kendisini
    sınamak oldu.

    **Bu madde iki fazlı okunur ve karıştırılmamalı: Faz 1 Yahoo'yla, Faz 2
    TradingView'le koştu. Bugün canlıda olan Faz 2'dir.** Aşağıdaki her tablo
    ve her sayı hangi faza ait olduğuyla etiketli.

    **Faz 1 (Yahoo):** iki vadeli seri **iki farklı şekilde** düşüyor, bu
    yüzden üç test var:

    - `GC=F` **oturumlar arasında kararsız**: aynı 250 tarih, diskteki panel
      anlık görüntüsüyle bugünün çekişi arasında **%3,6 tutuyor**, korelasyon
      **−0,10**, medyan 622'ye karşı 170.868 kontrat. Aynı arıza derinlik
      ekseninde de var: 2 yıllık istek 181.246, 25 yıllık istek **219**.
    - `SI=F` kararlı ama **her derinlikte gerçek dışı**: medyan 40–124
      kontrat, 627 sıfır hacimli seans. COMEX gümüşü günde ~60 bin işliyor.
    - `GLD`/`SLV` üç testi de geçiyor (çekişler arası birebir aynı, sıfır
      hacimli gün yok, seviye makul).

    Bunun tuzağı şu: "aynı oturumda iki kez çek, karşılaştır" testini **dört
    sembol de geçiyor**. Tek başına koşulsaydı kullanılamaz iki seriye temiz
    kâğıt verirdi. `part0` üçünü birden basıyor.

    **Faz 1'in çözümü buydu:** `flow_signal.py` hacimle ilgili her şeyi
    `GLD`/`SLV`'den okudu ve metali kendi fiyatıyla işledi — sinyal girdisiyle
    enstrümanın bilerek ayrıldığı bir kurgu. **Faz 2 bunu ortadan kaldırdı**
    (aşağıda): kural artık `COMEX:GC1!`/`SI1!`'in kendi mumunda yaşıyor, yani
    hacim de fiyat da tek bir seriden geliyor ve o seri `$/ons` kote.

    **Kuralın kendisi:** değer alanının üstüne kapanış + AVWAP üstü + pozitif
    akış + en az iki osilatör onayı → gir; oynaklık ölçekli (yalnızca yukarı
    hareket eden) stop ya da iki seans AVWAP altı → çık. Baraj sonuçlara
    bakılmadan ilan edildi: "$10.000 rungunda, ETF üzerinde, iki metalde de
    Calmar'da al-ve-tut'u geç **ve** parada %25'ten fazla geride kalma".

    **Faz 1 sonucu** (sinyal GLD/SLV üzerinde) — bugünün kartındaki sayılar
    bunlar DEĞİL:

    | metal | Calmar | al-tut | son $ | al-tut $ |
    |---|---|---|---|---|
    | altın | **0,566** | 0,495 | $24.556 | $37.163 (**−%33,9**) |
    | gümüş | 0,116 | 0,232 | $16.488 | $31.275 (**−%47,3**) |

    Altın Calmar'ı kazanıyor — düşüşü %27,6'dan %15,5'e indiriyor, bu deponun
    ölçtüğü **en büyük düşüş kesintisi** — ve on yılda **$12.607 daha az para**
    bırakıyor. 17. maddedeki $1.413'ün dokuz katı: orada "para değil sükûnet"
    bir savunmaydı, burada bir maliyettir.

    **Dokuz bileşenin hiçbiri tek başına yön de taşımıyor** (Faz 1): 5 ve 20 günlük
    ufuklarda, iki metalde, 36 hücrenin sıfırı eşiği geçti ve **hiçbiri
    |t|=1'e bile ulaşmadı** (en büyüğü 0,80). Altının VAH kırılımı 20 günde
    +3,0 puan, gümüşünki −5,2 — işaret metaller arasında ters dönüyor.

    **Faz 2 (2026-09-16): kaynak değişti, hüküm değişmedi, ve panel artık
    ONS konuşuyor.** Faz 1'in bedeli şuydu — ons altın izleyen biri seviyeleri
    GLD dolarında okuyordu. Sebep yukarıdaki bulguydu, ama o bulgu "vadelinin
    hacmi yok" demek değildi: doğru soru "**bu satıcı** sunamıyor" idi ve
    ikinci bir satıcıya sorulmamıştı. `backend/tv_history.py` TradingView'in
    grafik beslemesinden günlük OHLCV çekiyor (girişsiz, 12.000 bara kadar):

    | | `TVC:GOLD` (spot) | `COMEX:GC1!` | `COMEX:SI1!` |
    |---|---|---|---|
    | medyan hacim | **her barda 0** | 176.514 | 57.776 |
    | derinlik değişmezliği | — | %100 | %100 |
    | taze Yahoo ile seviye | — | 176.343 ✓ | **168** ✗ |
    | birim | $/ons | **$/ons** | **$/ons** |

    **Spot altının hacmi hiçbir kaynakta yok ve bu bir satıcı sorunu değil**:
    XAU/USD tezgâh üstüdür, konsolide tape yoktur. OANDA bir sayı döner ve o
    sayı tek bir aracı kurumun kendi müşterilerinin tikleridir — ikinci bir
    aracı kurum başkasını verirdi. Bir hacim profili "piyasa nerede işlem
    gördü" iddiasıdır; spot için o iddiayı taşıyabilecek seri mevcut değil.

    COMEX kontratı hem gerçek hacme hem `$/ons` birimine sahip, o yüzden
    sinyal oraya taşındı. Yeni kaynak = yeni deney, o yüzden **ikinci bir
    ön-kayıt** yazıldı: baraj aynı, ama alınabilir bacak sinyali `GLD`/`SLV`'ye
    **tam bir seans gecikmeyle** uyguluyor (vadeli mumu NY 17:00'da, ETF 16:00'da
    kapanıyor — gecikmesiz bir bacak 16. maddedeki seans sınırı etkisini
    tekrarlardı), ve süpürme aynı kurgu üzerinde puanlanıyor.

    **Faz 2 sonucu** — kartın bugün bastığı sayılar bunlar:

    | metal | Calmar | al-tut | son $ | al-tut $ |
    |---|---|---|---|---|
    | altın | **0,520** | 0,463 | $20.548 | $35.284 (**−%41,8**) |
    | gümüş | 0,154 | 0,236 | $17.996 | $32.715 (**−%45,0**) |

    **İki satıcı, iki enstrüman, aynı cevap** — bu, iki koşunun her birinden
    ayrı ayrı daha değerli: başarısızlık kuralın, veri artefaktının değil.

    Üç yan bulgu kayıt altında:
    - **İki metal artık AYNI parametreleri seçti** (onay≥2, 2,0σ, sert çıkış);
      Faz 1'de gümüş 3,0σ seçmişti. **Ayrı ayrı ölçülmüş aynı sayılar sorun
      değil, kopyalanmış aynı sayılar sorundur** — ve ikisi dışarıdan ayırt
      edilemez, o yüzden ölçüm her birinin yanındaki yorumda duruyor.
    - `test_flow_signal.py`'nin "ikisi farklı olmalı" testi bu yüzden **düştü
      ve yeniden yazıldı**. Bir ölçümün sonucunu çiviyle tutturan bekçi, ölçüm
      yeniden koşulduğunda — tam susması gereken anda — kırılır. Yerine
      yapısal olan kondu: config varlık başına bakılıyor mu, iki seri farklı mı.
    - **Bu belgelenmemiş bir WebSocket.** `tv_history.daily()` hiçbir zaman
      exception fırlatmaz, boş çerçeve döner; hiçbir tahmin yolu onu import
      etmez. Bozulursa bedeli bayat bir panel, kaçan bir karar değil.

    **Üretime giren şey bir PANEL, ve 2026-09-16'dan beri bir DEFTER.**
    `breakout` hâlâ `trading.STRATEGIES`'te yok, `ensemble.COMPONENTS`'te yok,
    `ml_model.FEATURE_COLUMNS`'ta kolonu yok. Ama `portfolios`'ta **satırı
    var**: metal başına $1000, tam giriş / tam çıkış (`breakout_trading.py`).

    **Bu bir fikir değişikliği değil, ölçümün değişmemesine rağmen verilen bir
    karar** — ve ikisini ayırmak önemli. Baraj geçilmedi ve geçilmiş gibi
    davranılmıyor: kartın üzerinde yukarıdaki tablo, defterin yanında
    "kopyalanacak bir kural değil" cümlesi, mailde kendi uyarı satırı duruyor.
    Defterin eklediği şey tablonun ekleyemediği şey: **kaybın tek tek
    dolumlarla, al-ve-tut'un yanında, aynı günlerde birikmesi.** Değeri
    olumsuz sonuçları dürüst ölçmek olan bir depo, bir kaybı izlenebilir
    kılabilmelidir.

    `trading.STRATEGIES`'ten uzak durmasının sebebi ölçüm değil **yapı**:
    orası `compute_target_exposure()` ile boyutlanan kuralların kümesi, bu
    kural ise ayrık bir durumdan tam giriş/çıkış yapıyor — `kanalfinans`'la
    aynı üçüncü tür. Bir hedef pozisyon vermek kuralın kendisiyle çelişirdi
    ("kırılana kadar tut" ile "her sabah %3 kırp" aynı anda olamaz).
    `tests/test_flow_signal.py` bu sınırları kilitliyor.

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

- **Gerçek para/emir yok.** Metal başına **on iki** portföy (onu `trading.py`'nin
  motoruyla, biri Kanal Finans takipçisi, biri kırılım kuralı) — toplam yirmi
  dört, artı GLD ve SLV için dörder ETF defteri. **Otuz ikisi de sanal.**
- **Hiçbir piyasa verisi anahtarı gerekmiyor.** Yahoo Finance chart API
  (GC=F, SI=F + 14 makro seri), Binance'in kamuya açık
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
| `breakout.symbol` | `COMEX:GC1!` | `COMEX:SI1!` | panelin hacmi buradan okuması ölçülmüş bir zorunluluk |
| `breakout.stop_sigmas` | 2,0 | 2,0 | **ayrı ayrı ölçüldü, aynı çıktı** — Faz 1'de 2,0 vs 3,0'dı |

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

**Ve "daha çok gözlem" 2x'te denendi — işe yaramadı** (`research/pooled.py`).
Altın ve gümüş havuzlanıp tek modelde eğitildi (etkin bağımsız gözlem ~1141 →
~2282, tespit tabanı 0,0895 → 0,0634). Havuzlamanın katkısı **iki metalde de
negatif** (altın −0,033 p=0,101, gümüş −0,002 p=0,937), ve "kapasiteyi aç
bıraktık" mazereti ön-kayıtlı bir teşhisle kapatıldı (`max_depth=4` ikisini de
kötüleştirdi). Sebep muhtemelen basit: **iki metal aynı gün r=+0,78 hareket
ediyor**, yani gümüşün satırları bağımsız gözlem eklemiyor, büyük ölçüde aynı
gözlemi tekrarlıyor. Tez çürümedi, ama "sadece daha fazla satır ver" biçimi
çürüdü — gereken şey *bağımsız* gözlem, ve ikinci bir metal onu vermiyor.

> Aynı çalışmanın yan bulgusu açık uçlu duruyor: fiyat türevli özellikleri
> varlığın kendi oynaklığına bölmek altında IC'yi +0,0596'dan **+0,1040**'a
> çıkardı (t=+3,27, tespit tabanının üstünde). Alınmadı, çünkü eşleştirilmiş
> fark anlamlı değil (p=0,122) **ve** gümüşte tekrar etmiyor (+0,0065). Bu
> tezgâhta bir metalde çıkıp diğerinde çıkmayan sonuç benimsenmez.

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

**`vix3m` denendi ve `vix`'in yerini ALMADI.** 2026-09-10'daki aday
taramasında `^VIX3M` iki metalde de `vix`'ten yüksek t aldı (altın −3,68 vs
−3,58; gümüş −4,95 vs −4,57) — aynı şekil, aynı işaret, daha az gürültülü bir
ölçüm gibi duruyordu. `research/vixterm.py` takası **iki tüketici için ayrı
ayrı** sınadı (ML özelliği ve `macro_signal`'ın oyu), üretimin gerçek 5 günlük
ufkunda ve ortak pencerede: **dört hücrenin dördü de ayırt edilemedi**
(p=0,77..0,96) ve işaretler hücreler arasında çelişti. `drivers.py`'deki
üstünlük 1 GÜNLÜK ham korelasyondu; 5 günde, gerçek tüketicilerin içinden
geçince kalmıyor. Üstelik takasın iki bedeli var: `^VIX3M` 2006'da başlıyor ve
`prepare_training_frame` NaN satırı düşürdüğü için her eğitimden **%19,2
seans** silinirdi, ve `VIX_SCALE` VIX'in kendi dağılımında ölçülü olduğu için
ham takas ağırlıklı bir terimi 1,46 kat sessizleştirirdi.

> Bundan çıkan tek üretim değişikliği `indicators.LEVEL_SERIES` oldu: seviye
> serilerinin **farkı**, fiyat serilerinin **getirisi** alınır ve bu ayrım
> `("vix", "us10y")` diye gömülü bir listeydi. Bir aday seriyi yanlış
> dönüşümle ölçmek onu ölçmemektir — `real_yield_chg`'in birim tutarsızlığının
> aynı ailesi. Üretimin gördüğü kolonlar değişmedi.

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

### Maliyet tek bir sayı değil -- ve hepsi oransal da değil

`backtest.py` dört senaryoyu birden basar (2/10/40/150 bp gidiş-dönüş).
Fark belirleyici: ETF maliyetinde `voltarget`, `technical`, `ml` ve `macro`
al-ve-tut'u Calmar'da geçiyor; **banka gram altın maliyetinde (150 bp)
hiçbiri geçmiyor.** `macro` bileşeni bunun en net örneği — 19,5 yılda 2288
işlem yapıyor, 2 bp'de Calmar 0,27 (al-ve-tut 0,23), 150 bp'de 0,03.
Gerçek bir sinyal, üzerine para koymanın pahalı olduğu bir sinyal.

**Ve bu merdivenin tamamı ORANSAL maliyettir; gerçek bir ETF aracı kurumu
çoğu zaman işlem başına sabit dolar alır.** Bu bambaşka bir şekildir: oransal
ücret hesap büyüklüğüne görünmezdir, sabit ücret ise başka hiçbir şeye bağlı
değildir. `backtest.flat_fee_ladder` işlem başına $1,50'yi hesap büyüklüğüne
karşı süpürüyor ve cevap bir **hesap büyüklüğü eşiği**: `miners` ve `macro`
$1.000'lik defteri **iflas ettiriyor** (efektif 170 bp tek yön), $25.000'de
al-ve-tut'u net geçiyor (0,350 vs 0,231), $500.000'de maliyetsiz sınıra
oturuyor. Süpürme tamdır çünkü sabit ücret dışındaki her şey ölçek-değişmezdir
-- $N nakit + $1,50 ücret, standart $1000'lık defter + $1,50×1000/N ücretle
birebir aynıdır.

**Sabit ücreti sezgiyle baz puana çevirme, üç kat yanılırsın.** $1,50'yi
mümkün olan en küçük işleme (`REBALANCE_THRESHOLD` × defter) bölmek $5.000'de
60 bp verir; ölçülen **11,7 bp**'dir, çünkü işlemler o tabanda kalmaz ve
defter bileşiklenir. `flat_fee_ladder` efektif bp'yi kendisi basıyor.
Ayrıca sabit ücret bir defteri **eksiye** düşürebilir (küçük bir satışta ücret
gelirin kendisini aşar); `metrics()` orada `nan` döndürür ve onu basmak
silinmiş bir hesabı "veri yok" diye raporlamak olur -- `BUST` sentinel'i ve
`_beats()` bunun için var. `research/README.md` 15. bölüm.

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
  Supabase'ine yazar. **Günde dört kez çalışır: 01:00, 07:00, 13:00, 19:00.**
  Üç gündüz saati kanalın fiilen yayın yaptığı saatler, yani yeni video kör bir
  yoklamayı beklemeden dakikalar içinde işleniyor; 01:00 gece gelenleri
  topluyor. Eski takvim 30 dakikada birdi ve engelin sebebi olan tekrar
  fırtınasının taşıyıcısı oydu — yeni takvim yoklama hızını tek başına 12 kat
  düşürüyor. Koşu başına sınır bu yüzden 3'ten **8 videoya** çıkarıldı: RSS'ten
  ölçüldüğünde kanal günde 1,67 video yayınlıyor ve hiçbir gün 3'ü geçmemiş,
  ama artık koşular 30 dakika değil **6 saat** arayla, yani bir pencerede biriken
  her şeyin tek koşuya sığması gerekiyor — sığmazsa sinyal 6 saat bekler ki bir
  piyasa yorumu videosu için bu ömrünün çoğu demektir. Geri çekilme artık **tek
  ve gerçekten paylaşılan** bir sayaç (`state/backoff.json`, yerel dosya,
  Supabase'de değil) — eskiden iki proje aynı videonun geri çekilmesini
  birbirinden bağımsız sayıyordu, yani her ikisinin toplamı tek bir paylaşılan
  sayaçtan daha sık deniyordu.

  **Transkript kaynağı 2026-09-09'da değişti ve önceki teşhis yanlıştı.**
  Fetcher `youtube-transcript-api` kullanıyordu, iki gün boyunca 242 kez
  `IpBlocked` aldı, **hiç** başarılı olmadı, ve dosyaya "bu makine tam engelli,
  çözüm Webshare proxy" diye yazıldı. Aynı makineden yeniden ölçüldüğünde:
  RSS **200** (10/10), izleme sayfası **200**, ses **200** (32 MB/s) — ve
  altyazı (`youtube.com/api/timedtext`) **429**, her istekte. Yani IP engelli
  değil, **tıkalı olan tek uç nokta altyazı**. Eski okumadaki 404'ler gerçekti
  ama aralıklıydı (aynı URL 500 de döndürdü, bir kez DNS çözülemedi); geçici
  bir yerel ağ arızası kalıcı bir yasak diye kaydedilmişti.

  Sebep büyük ihtimalle kendi tekrar fırtınamız: her başarısızlık iki istek,
  her koşu ~16 bekleyen videoyu yeniden deniyor — günde ~1.500 altyazı isteği.
  **Proxy bunu çözmez, gizler**; limit yeni IP'ye de gelirdi. Çözüm tıkalı uç
  noktaya hiç ihtiyaç duymamak: aynı IP'nin tam hızda verdiği **sesi** alıp
  `faster-whisper` ile **yerelde** yazıya çevirmek. Anahtar yok, hesap yok,
  proxy yok, ödenecek bir şey yok. Altyazı yine de video başına bir kez önce
  deneniyor (çalıştığında konuşmacının kendi kelimeleri); Whisper yedek, ve
  bugün fiilen çalışan yol o.

  İki sayı bu projenin kendi disipliniyle ölçüldü: `WHISPER_PROMPT` olmadan
  kanalın kendi konusu **"gümüş"**, 6 geçişin 2'sinde **"günmüş"** yazıldı —
  yani bir yazım hatası değil, `assets.py`'nin ayırdığı iki metalden birinin
  **kaybolmuş sinyali**; ipucuyla 6/6 doğru. Ve koşu başına **3 video /
  15 dakika** sınırı var, çünkü transkripsiyon artık CPU dakikaları harcıyor
  (6,4 dakikalık video = 147 sn) — sınır aynı zamanda fırtınayı bir daha
  kazanmamanın asıl güvencesi.

  **Transkript gelmiyorsa `../Kanal-Finans-Fetcher/youtube.md`'ye bak** — o
  konudaki tek doğruluk kaynağı orası: ölçüm tablosu, daha önce yapılmış iki
  yanlış teşhis (ve neden ikisinin de ikna edici göründüğü), belirti→çözüm
  listesi. İlk adım her zaman `python diagnose_youtube.py`: dört uç noktayı
  aynı koşuda ölçüp hüküm basıyor, çünkü bu projenin yaptığı iki yanlış
  teşhisin ikisi de "bir uç nokta patladı, demek ki IP engelli" biçimindeydi
  ve o ikisini ayıran tek şey uç noktaları yan yana ölçmek.
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

### Sayfada hiçbir şey katlanmaz, iç kaydırma ve gezinen sayı yoktur

Üç kural, ve üçü de kullanıcının açık talebi:

1. **Açıklamalar dışında hiçbir şey açılır-kapanır değildir.** `.explain`
   blokları ("bu tahmin ne işe yarar") kalır; onlar içeriğin kendisi değil,
   içeriğin *tarifi*. Geri kalan her şey açıktır. Bir zamanlar sinyal
   defterleri bir `<details>` içindeydi ve gerekçesi "asıl bakılan şey ölçülmüş
   kurallar"dı — ama tıklanması gereken panel, bir kez okunan paneldir.
   Ayrım artık bir katlama değil, bir **başlık ve bir cümle**.
2. **Hiçbir öğe kendi içinde kaymaz.** `.table-wrap`'in eski
   `overflow-x: auto` kuralı kolay çözümdü ve sekiz sütunlu tabloların
   büyümesine izin veren şeydi: yana kayan bir tablo, sütunları çoğu okuyucunun
   hiç yapmadığı bir hareketin arkasına saklar — ve saklananlar önemsiz olanlar
   değil, sonuncu olanlardır.
3. **Grafiklerin altındaki sayılar sabittir; fareyle değişmez.** İlk sürümde
   iki grafiğin de bir nişangâhı vardı ve altındaki satırı her imleç
   hareketinde yeniden yazıyordu. `dataviz` becerisinin varsayılanı budur ve
   burada yanlıştı: okuyucunun **az önce okuduğu sayılar, imleç üzerlerinden
   geçerken değişiyordu**, yani kartta akılda tutulacak ya da karşılaştırılacak
   tek bir okuma yoktu. Satır artık her çizili eğrinin **nerede bittiğini**
   yazıyor — ölçülmüş grafikte son seansın değeri ve o değerin kendi zirvesinden
   uzaklığı (ikincisi tablodaki kolon değil: orada **en kötü** düşüş var, burada
   bugünkü), canlı grafikte "şimdi" işaretindeki defter değerleri.
   `chart.js` artık `.hit` dikdörtgeni ve `.crosshair` grubu **üretmiyor**;
   kimlik zaten her çizginin sağ ucundaki doğrudan etikette.

**Bu ikincisi göz kararı doğrulanamaz.** `scratchpad/overflow.js` her öğeyi
dolaşıp `scrollWidth > clientWidth` arıyor ve 300px–1400px arası her genişlikte
koşuluyor. Bir kolon genişliği değiştirdiğinde bunu tekrar koş; "bana normal
göründü" bu sayfada yeterli değil.

Üç şey ölçülerek düzeltildi:

- **Tek-kolon eşiği 960 değil 1100.** 1024px'te iki kolon ~594/~382 çıkıyor ve
  382'de altı sütunlu bileşen sicili karttan taşıyordu — **sessizce**, çünkü
  artık hiçbir şey kaymıyor.
- **Başlıklar sarar, sayılar sarmaz.** `th { white-space: nowrap }` her sütuna
  bir taban genişlik koyuyordu; "Hedef seans"ın iki satıra inmesi bir kerelik
  bir satır yüksekliği, tek satırda kalması ise kalıcı bir taban.
- **700px altında tablolar satır-kartına dönüşür.** Her hücre kendi sütununu
  yazar; etiketi `labelTableCells()` render anında `<th>`'den **okur**, render
  fonksiyonlarının ayrıca yazmasıyla değil. Altı ayrı fonksiyon satır üretiyor
  ve değerin yanına ikinci kez yazılan bir etiket, sütun ilk yeniden
  adlandırıldığında başlığından ayrışan bir etikettir.

**Kanal Finans tablosu kart listesine dönüştü, ve bu bir form düzeltmesi.**
Sekiz sütunun yedisi kısa etiket ve seviye, sekizincisi transkript edilmiş
konuşmadan bir paragraf — bunlar karşılaştırılabilir sekiz ölçü değil. 444px'lik
yan kolonda hiçbir sıkıştırma onu sığdıramıyordu. Kartta seviyeler saran
çiplere, özet ise tam genişliğe kavuşuyor. Seviye çipleri **yalnızca
konuşmacının verdikleri**: her videoda tire basan bir satır "bahsetti ve boştu"
der, oysa eksik seviye "değişmedi" demektir.

### Canlı defterlerin eğrisi: tarayıcıda kurulur, ikinci bir kaynak yoktur

Ölçülmüş geçmiş kartı "bu kurallar 19,5 yılda işe yaradı mı" sorusunu
cevaplıyor; `Defterlerin seyri` ise **"benim bin dolarım ne yaptı"** sorusunu,
ki onu hiçbir panel cevaplayamıyordu — bir pozisyon kutusu, bu sabah da bir ay
önce de ayarlanmış olsa aynı görünür.

`liveEquitySeries` `trades`'i baştan oynatıyor ve her günü o günün
`predictions.price_at_prediction`'ıyla değerliyor. **Fiyat serisi bu, başka bir
şey değil**: aynı koşu, aynı an, aynı besleme. Defterleri başka bir seriyle
(spot kotasyonu, başka bir kapanış) markalamak, pozisyonu hiç alınmadığı bir
para biriminde fiyatlamak olur — değerleme notundaki vadeli/spot hatasının
günlük hâli. İkisi de zaten indiriliyor (ortalama maliyet için), yani grafik
ek bir istek getirmiyor.

İki incelik:
- **İşlemler günün SONUNDA kesilir.** `predict.py` önce tahmini yazıyor, bir
  saniye sonra işlem yapıyor; tahminin kendi damgasında kesmek her defteri
  kendi doldurmalarının bir gün gerisinde gösterirdi.
- **`predictions` limiti 30 değil 400.** Sicil tablosu bir pencere gösteriyor
  ama eğri **her satırı** kullanıyor — her biri bir günün mark fiyatı. 30'luk
  bir tavan, bir ay sonra grafiği sessizce son altı haftaya kırpardı.

**Palet 8'den 10'a, sonra 11 slota çıktı ve her seferinde yeniden
doğrulandı.** `claude` backtest edilemiyor, `kanalfinans` bir arşive bağlı,
`breakout` ayrık bir motor koşuyor — üçü de yalnızca canlı grafikte var.
11. slot (2026-09-16, orkide `#a54ac2`) gamut taramasıyla seçildi, gözle
değil: `frontend/tools/palette.js` CIEDE2000 + Viénot dikromasi simülasyonu
koşuyor ve aday, mevcut paletin **kendi en kötü durumunu hiçbir ölçüde
bozmamak** zorundaydı — ve bozmadı: onun en kötü dörtlüsü (34,9 / 2,1 / 12,6 /
3,78:1) on birlikteyle **birebir aynı**. Aday taraması
`frontend/tools/palette-search.js`'te; ölçüler `chart.js`'te slotun yanında da
yazılı.
**Bu ölçüler 1-10. slotları puanlayan araçla AYNI ÖLÇEKTE DEĞİL** — birbirleriyle
karşılaştırılabilirler, eski kayıtlı sayılarla değil. Parlaklık/kroma bandı
kısıtı taşıyıcı: ayrımı en yüksek adaylar 11:1 kontrastlı soluk pastellerdi ve
onlar mesafeyi kazanıp okuyucunun gözünü sahipleniyordu.

`LIVE_SERIES`, `BACKTEST_SERIES`'i **yayarak** genişletiyor, yeniden
sıralayarak değil: renk varlığı takip eder, yani "mavi = oynaklık hedefi" iki
grafikte de geçerli olmalı. Ve sıra kritik: `claude`'u `STRATEGIES`'teki
komşusunun yanına koyunca tan ile kırmızı bitişik oldu ve çift normal-görüş
tabanını geçemedi (ΔE 13,7 < 15); sona eklenince 19,3.
`test_export_backtest.py` bu iki değişmezi de kilitliyor.

---

### Düzen: üç bant, ve hangi kartın nerede durduğu ölçümden geliyor

Sayfa 2026-09-11'e kadar **tek bir 8.157 piksellik kolondu** ve içinde her kart
aynı görsel ağırlığa sahipti: karar, 19,5 yıllık ölçüm, ve Brier beceri skoru
her ufukta negatif ölçülmüş bir bileşen — üçü de tam genişlik kart, aynı başlık
puntosu. Yeni düzen `research/README.md`'nin düzyazıyla söylediğini **yerleşimle**
söylüyor. Ölçülen sonuç: 8.157 → **5.607 piksel**, kolonlar 3.324 / 3.010.

> **Bu iki sayı aynı anda ölçülmedi ve yan yana okunmamalı.** Sayfa yüksekliği
> görüntü genişliğine ve o gün kaç işlem yapıldığına bağlı; yukarıdaki çift
> yeniden tasarım anındaki ölçüm. Defter kutuları eklendiğinde (2026-09-11,
> `bookLogHtml`) **1280px'te** ölçülen çift **8.213 → 7.501 piksel** oldu: on
> beş defterin her biri kendi dolumlarını kazandı, ama iki birleşik tablo
> (metallerin on beş satırı ve ETF kartınınki) gitti ve net 712 piksel kısaldı.
> Bir yükseklik iddiası yazarken hangi genişlikte ölçtüğünü de yaz.

Üç bant:

- **HERO** — `Bugün` kartı ve `Piyasa Durumu` yan yana, çünkü bunlar tek bir
  düşüncedir: hedef pozisyon, yanındaki oynaklığa verilen **tepkidir**. Alt
  alta konunca okuyucu cevabı, sebebine ulaşmadan geçiyor.
- **TAM GENİŞLİK** — `Ölçülmüş Geçmiş`. Grafikler her pikseli istiyor.
- **İKİ KOLON** — ve ayrım şu: **ana kolon SONUÇLAR** (kağıt portföyler,
  alınabilir ETF defterleri, tahmin sicili — üzerinde para olan ve kuralları
  ölçülmüş olan taraf), **yan kolon GİRDİLER** (günün yön çağrısı, bileşenler,
  her birinin hak ettiği sicil, bir insanın görüşü). İkincisinin tamamı gerçek
  çıktıdır ve hiçbiri hiçbir şey yapmamayı geçmiyor. Dar kolona almak onu
  gizlemek değil — sayfanın nihayet araştırma tezgâhıyla aynı şeyi söylemesi.

Kartların hangi kolona gittiği **ölçülerek** ayarlandı, sezgiyle değil: sicil
önce girdi tarafındaydı ve kolonlar 2.878/3.490 çıkıyordu, yani defterlerin
altında 600 piksel ölü alan kalıyordu. Sonuçlar tarafına alınca 3.324/3.010.
Bir kartı taşımadan önce iki kolonun yüksekliğini ölç.

**Sekme şeridi başlığa taşındı ve başlık yapışkan.** 8.000 piksellik bir sayfada
metal anahtarına ancak en başa dönerek ulaşılabiliyordu — oysa o sekme,
altındaki her varlık-kapsamlı sayının **ne anlama geldiğini** belirliyor. Tüm
sayfayı yeniden çerçeveleyen bir kontrol, ilk kaybolan şey olamaz. Kotasyon
şeridi de aynı sebeple orada: "%63 pozisyon" uygulandığı fiyat olmadan
okunabilir bir talimat değil, ve `Anlık Fiyatlar` kartı portföyler okunurken
binlerce piksel yukarıda kalıyor. 1080px altında şerit gizleniyor — dar ekranda
başlığın görüntü alanını yemesi, kotasyondan daha pahalı.

`renderTopbarQuotes` bilerek **`Anlık Fiyatlar` kartının özeti**, ikinci bir
kaynak değil: aynı `live` nesnesi ve aynı COMEX yedeği veriliyor, yani ikisi
ancak biri hiç çizilmemişse ayrışabilir. Düşürdüğü şey tam olarak **köken
bilgisi** — TL paritesi, kaynak satırı, vadeli–spot farkı — çünkü bunlar doğru
ifade edilmek için yer isteyen iddialar ve bir başlık şeridinde o yer yok. Bu
yüzden şerit "canlı" rozetini de takmıyor.

**Kağıt portföyler ikiye ayrıldı, ve çizgi `trading.MECHANICAL`.** Bu bir
yerleşim tercihi değil, backend'in ETF defterlerinde hangi kuralların
koşabileceğine karar vermek için zaten kullandığı sabitin aynısı:

- Dört mekanik defter **hiçbir şey tahmin etmiyor** — gerçekleşen oynaklığa ve
  fiyatın kendi uzun ortalamasına tepki veriyorlar — ve `research/instrument.py`
  alınabilir enstrümanda al-ve-tut'u geçenlerin biri hariç hepsinin bu kümede
  olduğunu ölçtü.
- Diğer altısı, `research/edge.py`'nin her ufukta "hep uzun"a yenildiğini
  ölçtüğü, `research/tilt.py`'nin ise tam olarak sıfır değerinde bulduğu bir yön
  çağrısına göre pozisyon alıyor.

On bir eşit kutu, bu iki kümenin eşit desteklendiğini söylüyordu. Söylemiyorlar,
ve bu sayfanın bütün işi bunu söylememek. **Hiçbir şey gizlenmiyor**: özet satırı
canlı sayıyı taşıyor ve tek tık açıyor.

**Ve on birinci defter (`kanalfinans`) 2026-09-11'de bu karttan çıktı: artık
Kanal Finans kartının içinde, kopyaladığı sözlerin yanında.** Üçüncü bir tür, ve
bunu söyleyen sayfa değil backend: `predict.py` onu üretmiyor,
`ensemble.COMPONENTS` içermiyor, `trading.compute_target_exposure` boyutunu
hiç hesaplamıyor, `trading.REBALANCE_THRESHOLD` ona uygulanmıyor — hatta
**`trading.STRATEGIES` içinde bile değil**; işlemleri
`kanal_finans_trading.decide_on_mention` koyuyor ve kural ayrık AL/SAT.
Ölçülmüş kuralların ızgarasında durunca on birinci bir kural gibi okunuyordu.

İki inceliği var:

- **Eğrisi canlı grafikte KALIYOR.** Paneli taşımak defterin nerede
  *anlatıldığıyla* ilgili; karşılaştırma grafikte yapılıyor ve oradan bir çizgi
  düşürmek, her defteri aynı ölçüye vuran tek yeri bozmak olurdu.
- **Panel aynı fonksiyondan çıkıyor** (`bookPanelHtml`, ortak `bookContext`).
  İki kart aynı kutuyu iki ayrı kopyadan çizseydi, ilk eklenen satırda
  ayrışırlardı — birleşik işlem defterlerinin dersinin aynısı. Kıyas değeri de
  tek yerde hesaplanıyor, yoksa iki kart al-ve-tut hakkında farklı şey söyleyebilir.

`test_track_etf.test_the_follower_book_is_drawn_once_and_not_among_the_rules`
iki sessiz arızayı da kilitliyor: sinyal ızgarasında kalan bir `follower`
**iki kere** çizilir, ikinci bir `follower` girdisi ise `.find` yüzünden
**hiç** çizilmez.

> **Ve o özet satırı kendi örneklemini de yazıyor.** İlk sürüm "şu an 7'sinin
> 7'si al-ve-tut'un üzerinde" diyordu — doğru, ve anlamsız: defterler 4 günlük ve
> altının düştüğü bir haftada %100'ün altında duran her defter tanım gereği
> önde. `renderHistory`'nin `MIN_ROWS_FOR_VERDICT` ile reddettiği hükmün aynısı.
> Satır artık defter yaşını (`bookAgeDays`, ilk işlemden hesaplanıyor) ve
> "ölçülmüş sıralama yukarıdaki grafikte" cümlesini birlikte basıyor.

İki ızgara iki farklı şekil istiyor ve ikisi de ölçüldü. 1280px'te, ana kolonda:
ölçülmüş dörtlü **2×2** oturuyor (panel 321px; üç sütun tek başına bir yetim
satır bırakıyordu), sinyal altılısı ise daha dar tabanla (196px) **3×2**
oturuyor (panel 210px). Takipçi defteri buradan çıkınca — yedi paneldi ve
üçüncü satırda **tek başına** kalıyordu — grup tam iki satıra denk geldi;
yetim satırın kaybolması taşınmanın amacı değildi, ölçülen yan faydasıydı.
Kanal Finans kartındaki tek kutu yan kolonun tamamını alıyor (412px).

---

### Sayfa cevapla açılır, gerekçeyle değil

İlk kart **`Bugün`** ve manşet sayısı `voltarget`'ın **hedef pozisyonu** —
yön tahmini değil. Bu bir düzen tercihi değil, projenin kendi ölçümünün
sayfaya uygulanmış hâli: `research/edge.py` yön modelinin Brier beceri
skorunu **her ufukta negatif** ölçtü, `research/instrument.py` ise oynaklık
hedeflemeyi ölçülen **her sütunda** (vadeli/ETF, altın/gümüş) al-ve-tut'u
Calmar'da geçen tek kural olarak buldu. Sayfa uzun süre ölçülerek değersiz
bulunan sayıyı en büyük punto ile basıyordu ve işe yaradığı ölçülen sayıyı
(`target_exposure`) portföy kutularının içine gömüyordu.

Kartta **iki işaret** var ve ikisi de gerekli: dolgu **hedef** pozisyon, çentik
**şu anki** pozisyon. Tek bir çubuk "ne tutmalıyım" sorusunu cevaplar ve
aksiyon üreten tek soruyu — "hedeften ne kadar uzağım" — gizler.

Yön çağrısı kaldırıldı değil, **küçültüldü**; gizlemek kendi başına bir
dürüstsüzlük olurdu. Ama `edge_over_base` negatifken satır bunu açıkça
yazıyor: p_up 0,5'in üstünde ama taban oranın altındaysa "YÜKSELİŞ" etiketi
tek başına yanıltır — `renderPrediction`'ın kendi kartında ayrı cümleyle
anlattığı durumun aynısı.

### Ölçülmüş geçmiş: sayfa artık gürültülü örneklemi değil bilgi taşıyanı gösteriyor

`backtest.py` 19,5 yılı **yalnızca stdout'a** basıyordu, workflow
`workflow_dispatch`, ve GitHub log'u 90 günde siliniyor. Yani bu projedeki
tek bilgi taşıyan örneklem kalıcı değildi ve sayfada hiç yoktu — sayfa ise
Eylül 2026'da başlamış, al-ve-tut'a karşı hüküm vermesi **~2500 seans**
sürecek canlı defteri başrolde gösteriyordu. Ters taraf başroldeydi.

`backend/export_backtest.py` → `frontend/data/backtest.json` → `chart.js`.

Kararlar ve sebepleri:

- **Supabase tablosu değil, repo'daki statik dosya.** Bu veri yalnızca biri
  backtest'i bilerek yeniden koştuğunda değişir — yani `trading.py`'nin
  sabitleri değiştiğinde. Dosya olarak tutulunca eğri ile onu üreten
  parametre **aynı commit'te** duruyor; tablo olsaydı ikisi sessizce ayrışırdı
  ki bu deponun tamamı tam olarak buna karşı örgütlenmiş. Ayrıca elle
  uygulanacak bir migration, bir `service_role` yazma yolu ve bir RLS
  politikası gerektirmezdi — canlı da olmayan, kullanıcıya özel de olmayan
  bir veri için.
- **Metal başına TEK maliyet basamağı: o varlığın canlıda ödediği.**
  `backtest.py` merdivenin tamamını süpürür çünkü "sinyal var mı" ile "bir
  insan bunu koruyabilir mi" farklı sorulardır; ama kağıt portföylerin
  yanında duran bir grafiğin **üçüncü** bir soruyu cevaplaması, tek eksen
  altında iki farklı dünyayı karşılaştırmak olurdu.
- **Haftalık örnekleme.** 4900 seans, 1100 piksel — günlük eğri pikselden
  çok nokta demek. Son seans **her zaman** korunuyor: `sample_indices`
  olmadan kartın bastığı nihai değer ızgaranın rastgele denk geldiği güne ait
  olur, bir haftaya kadar yanlış ve tamamen makul görünür.
- **Düşüş paneli tarayıcıda hesaplanıyor**, JSON'a konmuyor. Sermaye
  eğrisinin saf bir fonksiyonu; göndermek dosyayı ikiye katlar ve kendi
  kaynağıyla çelişebilen ikinci bir kopya yaratır.
- **Logaritmik eksen, ve sınırlar tam dekada değil 1-2-5 adımına yuvarlanır.**
  Doğrusal eksende ilk on yıl dibe yapışık düz bir çizgidir ve okuyucu "on yıl
  hiçbir şey olmamış" sonucunu çıkarır; dekada yuvarlamak da en düşük noktası
  $840 olan bir seriye $100 çizgisi koyup panelin %40'ını boşa harcıyordu.
- **`buyhold` sekiz kategorik renkten biri DEĞİL.** Kesikli ve solgun: rakip
  değil **ölçüt**. Kategorik bir renk vermek, referans çizgisini referansı
  olduğu karşılaştırmanın içine sokardı.
- **Renk stratejiyi takip eder, sıralamasını ya da seçili olup olmadığını
  değil.** Bir seriyi kapatmak diğerlerini yeniden boyarsa okuyucunun
  "mavi = oynaklık hedefi" hafızası her filtrelemede siliniyor demektir.
- **Özet satırı Calmar'ı VE parayı ayrı ayrı basar**, çünkü ikisi burada
  aynı listeyi vermiyor ve **bu ayrışmanın kendisi bulgudur**. Yalnızca
  ilkini basmak, `research/README.md` 17. bölümün düzeltmek için var olduğu
  abartının aynısı olurdu. `miners` iki listede de görünüyor ve **yıldızla**
  geliyor: bu depoda onun satın alınabilir olmadığı uyarısı ismin gittiği her
  yere gider.
- Palet dataviz referansının koyu basamakları, **bu sayfanın kendi kart
  zemininde (#15120d) doğrulandı** — parlaklık bandı, kroma tabanı, komşu
  çiftlerde renk körlüğü ayrımı (en kötü ΔE 8,4), normal görüş tabanı (19,3)
  ve 3:1 kontrast. Gözle renk değiştirme, doğrulayıcıyı yeniden koş. Ayrıca
  her görünür çizgi sağ ucunda **doğrudan etiketli**, yani kimlik hiçbir zaman
  yalnız renge yaslanmıyor.
- **Kart Supabase'e bağlı değil ve öyle kalmalı.** `loadBacktest` payload'ı
  alır almaz çiziyor; `renderAll`'ı beklemek, Supabase'de bir kesintinin
  sayfadaki **tek** kendi kendine yeten paneli karartması demekti.

**`chart.js` tek bir global üzerinden konuşur: `Viz`.** İlk sürüm tepe
seviyede `const esc` tanımlıyordu, `app.js` de tanımlıyor — ikisi de düz
`<script>`, yani aynı global kapsam. Bu çakışma **uyarı vermiyor**, çakışma
noktasında da patlamıyor; **ikinci dosyanın tamamının parse edilmemesine**
neden oluyor. Sayfa statik HTML'ini çizdi, her sayı "-" kaldı, konsolda tek
satır vardı. İsim alanı bunu ihtimal olmaktan çıkarıp imkânsız yapıyor.

**`tests/test_export_backtest.py` iki dilin arasındaki aynaları kilitliyor.**
Çalışma zamanında ihracatçıyı sayfaya bağlayan hiçbir şey yok: bir alanı
yeniden adlandır, sayfa çökmez — 19,5 yıllık ölçüm vadeden bir başlığın
altında **boş bir kart** çizer, ki bu eksik grafikten kötüdür çünkü başlık
iddiayı etmeye devam eder. `test_track_etf`'in "arayüze yazılmayan defter"
testiyle aynı aile.

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
- **Alınabilir enstrüman kartı sekmeyi TAKİP EDER**, ve bu ayrım bilinçlidir:
  fiyat kartları iki farklı şeyin yan yana konmuş iki kotasyonudur, ETF kartı
  ise bir **defterdir** ve defter, üzerinde durduğu metalin sayfasına aittir.
  GLD altın sekmesinde, SLV gümüş sekmesinde. Kart GLD tek başınayken bilerek
  sekmeden bağımsızdı — o zaman `currentAsset`'e göre filtrelemek kartı gümüş
  sekmesinde boşaltırdı; SLV eklenince o tehlike de gerekçe de ortadan kalktı.
  `TRACKED_ETFS` her girdide hangi sekmeye ait olduğunu taşıyor ve
  `test_track_etf.test_every_tracked_book_is_reachable_on_the_page` bu eşlemeyi
  kilitliyor: `assets.TRACKED`'a eklenip arayüze yazılmayan bir defter her iş
  günü işlem yapar ve hiçbir sayfada görünmez — hiçbir yerde hata üretmeden.
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

**Ama tek bir birleşik defter yanlış soruyu cevaplıyordu, ve 2026-09-11'de
defter başına ayrıldı** (`bookLogHtml`). Zamana göre sıralı tek bir liste on
bir defteri **iç içe geçiriyor**: okuyucunun sorusu "bu kural ne yaptı",
cevabı ise on beş satır boyunca bir strateji kolonunu taramaktı. Daha kötüsü,
iki haftadır sessiz duran bir defter listeden **tamamen** düşüyordu — yani
"hiçbir şey yapmadı" tam olarak görünmez olan durumdu, oysa sorulan soru oydu.
Artık her defter kendi kutusunda kendi son altı dolumunu taşıyor, dolumu
olmayan defter de bunu yazıyor.

Kutunun taşımadığı iki şey bilerek dışarıda: **gerekçe metni** (bir cümlelik
düzyazı, dört sayıyla birlikte 220 pikselik bir panele girmez) ve **dolum başı
komisyon** (başlıkta toplanıyor — karar veren sayı tek bir dolumun ücreti değil,
o defterin bugüne kadar ödediği toplam). Tam geçmiş bir sorgu uzaklıkta;
sayfanın işi onu barındırmak değil. `<table>` de değil: 700px altında bu
sayfadaki her tablo etiket/değer bloklarına dönüşüyor ve dört kolonluk bir
defter orada defter başına yirmi dört satır olurdu.

**Dolum fiyatı `asset.digits` ile değil, okuma hassasiyetiyle basılıyor**
(`logPriceDigits`, ~5 anlamlı hane). Kotasyon hassasiyeti aynı panelde iki satır
yukarıda zaten var (`aldığı fiyat`); kutunun ihtiyacı bir tarihin, bir yönün ve
bir tutarın yanına sığan bir sayı. Ölçüldü: 1140px'te iki kolonlu düzende panel
içi ~170px ve "$4.476,60" orada kendi satırına kayıyor, "$4.477" kaymıyor.
Gümüş kuruşlarını koruyor, çünkü "$66" kaybolurdu.

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

### Alınabilir enstrüman: ayrı defterler, ayrı kayıt, ayrı iddia

`predict.py`'nin ürettiği yirmi iki portföyün hepsi (artı `track_breakout.py`'nin
ikisi) **COMEX vadeli** fiyatıyla
değerleniyor ve perakende bir hesap vadeli kontrat tutamaz. 16. ve 17. bölümler
bunun kozmetik bir fark olmadığını ölçtü. `backend/track_etf.py` bu yüzden var:
aynı kuralları **GLD ve SLV** üzerinde, işlem başına **$1,50 sabit komisyonla**
işleten dörder defter.

**İki metal de defter alır, ve ikisi aynı şeyi iddia etmez.** Proje her yerde
iki metalli; tam da metal *alınabilir* hâle geldiği yerde altında durmak sessiz
bir daralma olurdu. SLV'nin sabitleri SLV'de ölçüldü, GLD'den devralınmadı
(`macd` 93,7 / `ema_cross` 29,0 / `sma200` 3,73 — SI=F'in 93,4/29,3/3,72'si ile
birebir aynı aileden, GLD'ninkinin ~1,8 katı uzağında). $10.000'lik hesapta
16,1 yıl:

| | `voltarget` | `buyhold` | düşüş | Sharpe |
|---|---|---|---|---|
| GLD | $36.257 | $34.844 | %45,6 → %39,2 | 0,48 → 0,59 |
| SLV | $35.023 | $33.286 | %76,3 → %70,8 | 0,24 → 0,32 |

Aynı şekil, çok daha sert zeminde: gümüşün al-ve-tut düşüşü %76,3, altınınki
%45,6. Yani SLV'de kesilen beş puan, altındaki altı puandan **daha büyük bir
yaranın** üzerinde. Altının çiftini gümüş defterinin yanına basmak iki sayıyı
birden yanlış söylerdi — `daily_report.ETF_CLAIM` ve frontend'in
`TRACKED_ETFS`'i bu yüzden enstrüman başına ayrı bir dize taşıyor.

**`assets.TRACKED`, `assets.ASSETS`'ten AYRI bir sözlüktür ve öyle kalmalı.**
`ASSETS` `predict.py`'nin döndüğü şeydir: ML modeli, kalibratör, Claude çağrısı,
ensemble, bir `predictions` satırı. Bunların hiçbiri burada geçerli değil ve
GLD'yi oraya koymak günlük bir LLM çağrısı ile üçüncü bir model dosyası satın
alıp karşılığında hiçbir şey vermezdi. `GLD.model_filename` bilerek **boş**,
`leading_drivers` bilerek **boş tuple** — ikincisi önemli, çünkü altınınkileri
yazmak GLD üzerinde yapılmamış bir `drivers.py` ölçümünü ima ederdi.

**Yalnızca `trading.MECHANICAL` koşuyor** ve bu ölçülmüş bir seçim: 17. bölümde
ETF üzerinde al-ve-tut'u geçenlerin `ensemble` dışında hepsi mekanik, ve mekanik
stratejiler fiyat geçmişinden başka hiçbir şey istemiyor. İki gerekçenin
çakışması tesadüf ve tam da bu yüzden birileri sonradan "model zaten var" diye
`ml` eklemek isteyebilir — o model bu varlık için **yok**.

**`Asset.flat_fee_usd` varsayılan 0,0'dır ve altın/gümüş için 0,0 kalmalı.**
1-14. bölümlerdeki her Calmar tamamen oransal maliyet varsayıyor; sıfırdan farklı
bir varsayılan hepsini sessizce geçersiz kılardı. `trading.maybe_trade` artık
`gross * fee_rate + flat_fee_usd` hesaplıyor.

**`portfolios.ounces` bu defterlerde ONS DEĞİL, PAY tutar.** Tek tablo iki tür
defteri birden taşıyor ve kolonun adı metallerden geliyor; ETF tarafında içindeki
sayı adet hissedir. Bir GLD payı ~0,091 ons altın, bir SLV payı ~0,899 ons gümüş
(2026-09-11'de ölçüldü) — yani bu sayıyı "ons" başlığı altında basmak altın
tutarını **on bir kat** abartır. Arayüz ve mail ikisi de "pay" yazıyor.

**Pay → gram çevrimi SPOT fiyatla yapılır, ve bu değerlemenin kuralının tam
tersidir.** Defterler vadeliyle değerlenir çünkü işlemler o seride gerçekleşti;
ama bir fonun külçesi spot piyasada değerlenir, dolayısıyla pay başına metal
içeriğini vadeliye bölmek ~%1'lik bazı sessizce gram sayısına gömer. Çevrim
ETF fiyatının spot fiyata **oranından** türetiliyor (fon neredeyse yalnızca
külçe tutuyor, yani pay fiyatı ≈ pay başına metal × metal fiyatı) — sponsorun
NAV dosyasına yeni bir canlı bağımlılık eklemeden. Ölçüldü: GLD 0,0913 ons,
SLV 0,8989 ons; ikisi de sponsorun yayımladığı rakamın %1 içinde. İki sınırı da
ekranda yazılı: **yaklaşıktır**, ve ABD borsası kapalıyken ETF'in son kapanışı
canlı spotla karşılaştırıldığı için gece hareketi kadar sapar. Mail bu çevrimi
**yapmıyor** — oraya spot kotasyonu hiç gelmiyor ve olmayan bir fiyatı
uydurmaktansa gram satırını hiç basmamak doğrusu.

**ETF defterleri de kutudur ve her biri kendi dolumlarını taşır.** Kart bir
zamanlar dört satırlık bir tabloydu ve altında kendi birleşik işlem defteri
vardı; o defter, metallerin defteri `currentAsset`'e göre filtrelediği ve bir
ETF'in anahtarı hiçbir zaman o olmadığı için var olmuştu — **GLD işlemleri
veritabanına yazılıp hiçbir yerde gösterilmiyordu**. Ayrı bir sekme o zaman da
yanlış cevaptı (sekme şeridi **metal** demek, aynı kontrole ikinci bir anlam
yüklemek ikisini birden bozar) ama birleşik defter de öyleydi: bir defterin
dolumları o defterin kutusuna aittir.

Biçim artık metallerin panelleriyle **aynı**, ve bu bilinçli: bunlar aynı dört
kural (`trading.MECHANICAL`), ve tek bir kural kümesi için iki ayrı şekil
kullanmak onların iki ayrı şey olduğunu söyler. "al-ve-tut'a göre" de aynı
hesapla üretiliyor (`değer / kıyas değeri − 1`), tablonun kullandığı "iki toplam
getirinin farkı" ile değil: her defter tam $1.000'dan başladığı için ikisi
yuvarlama farkı kadar aynı, ama **birebir aynı görünen iki panel iki farklı şey
anlatamaz**.

Kartın özeti **ölçülen** efektif baz puanı basıyor (`komisyon / işlem hacmi`),
varsayılanı değil — `backtest.flat_fee_ladder`'ın aynı sebeple yaptığı şey.
$1,50'yi mümkün olan en küçük işleme bölmek 60 bp verir, gerçekleşen işlemlere
bölmek 11,7; sabit bir ücretin kendisine ait bir baz puan değeri yoktur. Bu
cümle birleşik defterle birlikte silinemezdi: **oran dört defterin ortak
özelliği**, defter başına komisyon toplamı ise ayrı bir sayı, ve $1.000'lık bir
defterin bu kuralı taşıyıp taşıyamayacağına karar veren o orandır.

`test_track_etf.test_every_book_on_the_page_shows_its_own_fills` her iki
ailenin de kendi defterini çizdiğini kilitliyor — yeni bir defter türü artık
"paylaşılan deftere eklemeyi unutmak" ile görünmez kalamaz, çünkü paylaşılan
defter yok.

**Nakit hem kartta hem mailde yazılı, sıfırken bile.** Yüzdelik pozisyon nakdi
gizler: %35 yatırımda olan bir defter aynı zamanda $650 bekleten bir defterdir
ve kişinin kendi hesabıyla karşılaştırdığı sayı odur. "Tam yatırımda" bir
bilgidir, eksik veri değil.

**Ve bu defterlerin iddiası getiri değil.** 17. bölüm: $10.000'lik bir GLD
hesabında 16,1 yılda `voltarget` $36.257, al-ve-tut $34.844 — fark gürültü.
Kazanılan şey maksimum düşüşün %45,6'dan %39,2'ye inmesi, ve bu yılda ~8
işlemle. Arayüz kartı, mail bölümü ve modül docstring'i üçü de bunu yazıyor;
biri silinirse okuyucu Calmar'ı kâr sanır.

### Kırılım Takibi: ölçülüp elenmiş bir kural, ekranda, kendi sonucuyla

Sayfadaki diğer her şey "5 seans sonra ne olacak" sorusunu cevaplıyor. Bu kart
başka bir soruyu cevaplıyor: **şu anda pozisyonda mıyım, ve beni oradan ne
çıkarır.** Kural `flow_signal.py`'de, ölçümü `research/flow.py`'de, günlük
durumu `track_breakout.py` → `breakout_state` tablosunda.

**Kart YAN kolonda ve bu bir tercih değil, ölçümün yerleşime uygulanmış hâli.**
Ana kolon sonuçlar — üzerinde para olan defterler. Bu kuralda para yok, çünkü
ön-kayıtlı barajı geçemedi (11. madde). Tam genişlik vermek, sayfanın bu kuralı
gerçekten desteklediği defterlerden daha çok desteklediğini söylerdi.

Yine de bir **grafiği** var, çünkü bir seviye bir sayı değildir: "fiyat $4.329,
değer alanı $4.731'de bitiyor" okuyucunun kafasında yaptığı bir aritmetik; aynı
iki işaret tek eksende bir bakış.

**Seviyeler `$/ons`, ve bu Faz 2'nin bütün amacıydı.** Faz 1'de kart GLD
dolarında konuşuyordu ($404,96) ve ons altın izleyen biri her seviyeyi kafasında
çeviriyordu. Kart artık ayrıca "seviyeler şu enstrümandadır, metalin kapanışı
şudur" cümlesini de **taşımıyor** — taşıması gereken bir şey kalmadı.

**Grafik kasıtlı olarak sermaye grafiklerinden farklı bir hayvandır.** Orada her
çizgi yarışan bir defter, soru "hangisi yukarıda". Burada **tek bir özne** var —
fiyat — ve geri kalan her şey ona karşı çizilmiş bir **seviye**. Sonuçları:

- **Fiyat on kategorik slottan biri DEĞİL** (`PRICE_COLOUR`, `BENCHMARK_COLOUR`
  ile aynı yerde tanımlı). Sebep `buyhold`'unkiyle aynı: ölçülen şeye bir
  rakip rengi vermek, referansı kendi karşılaştırmasının içine sokmaktır.
  `test_export_backtest.py` girintili `isim: "#hex"` satırlarını **kategorik
  palet** diye okuyor, yani bu şekilde yazılmış bir seri-dışı renk bir testi
  kırar — nitekim kırdı ve düzeltmesi rengi doğru yere taşımak oldu.
- **Değer alanı iki çizgi değil bir BANT.** Tek bir nesne: piyasanın son çeyrekte
  kabul ettiği aralık. Kenarlarını ayrı seriler gibi çizmek "fiyat VAH'ı kesti"yi
  bir çizgi kesişmesi gibi okutur, oysa olan şey bir **bölgeden çıkmaktır**.
- **Pozisyon her şeyin arkasında bir bant.** "Kural burada uzundu" zaman
  ekseninin bir özelliğidir, fiyat ekseninde bir değer değil.
- **Stop YALNIZCA pozisyon içindeyken çiziliyor.** Boştayken basılan bir stop
  seviyesi kurulu olmayan bir seviyedir ve çizgiden ayırt edilemez.
- **Y ekseni 6 tik istiyor, sermaye panelinin 4'ünü değil** — ve bu **Faz 1'de
  ölçülmüş**, Faz 2'de artık bağlayıcı olmayan bir sabittir. `niceTicks` adımı
  bir üst 1-2-5 katına **yuvarlıyor**, yani 4 isteyen 2 alabiliyor: Faz 1'in
  GLD dolarındaki $309–$520 penceresinde ham adım 52,8 → 100'e yuvarlanıyor ve
  tüm işi bir fiyatı seviyeler arasına yerleştirmek olan grafikte **iki
  gridline** kalıyordu; 6 istendiğinde 35,2 → 50 ve dört tik geliyordu.
  **Faz 2'nin $/ons pencerelerinde yeniden ölçüldü (2026-09-16) ve ikisi aynı
  sonucu veriyor**: altın (3.465–5.372) 4 de 6 da dört tik, gümüş (43,11–115,50)
  ikisi de üç tik. Yani 6 bugün hiçbir şey satın almıyor ama hiçbir şeye de mal
  olmuyor — 4'e döndürmeden önce iki metalin O GÜNKÜ penceresinde yeniden ölç,
  çünkü pencere fiyatla birlikte kayıyor ve arıza yalnızca belirli aralıklarda
  ortaya çıkıyor.

**Onay oyları backend'de karar veriliyor, JS'te değil** (`votes_detail` kolonu).
Altı eşik "geleneksel nötr nokta" olsa da bir eşik karşılaştırması **kararın
kendisidir**, ve bu deponun tekrar tekrar bulduğu arıza bir karar kuralının iki
dilde tutulup bir tarafta düzenlenmesidir. Bileşen sicili tablosunun log-odds
aritmetiğini kopyalamamasıyla aynı kural. Arayüz eşikleri **etiket olarak**
basıyor; o tarif, ikinci bir uygulama değil.

**Fibonacci seviyeleri tarayıcıda türetiliyor** (`fib_low`/`fib_high`'dan), ve
bu düşüş panelinin gerekçesiyle aynı: iki kayıtlı kolonun saf bir fonksiyonu,
yani saklanan bir kopya ancak kendi kaynağıyla çelişebilir. **Hiçbiri işlem
üretmiyor** — kazanan bir trendi kapatan bir kâr-al hedefi "kırılana kadar
tut"un tam tersidir.

**`loadBreakout` kendi `try/catch`'ine sahip ve bu kritik.** `api()` 200
olmayanda fırlatıyor, `loadData` tüm partiyi tek bir `try` içinde sarıyor —
yani migration'ı henüz uygulanmamış bir `breakout_state`, "Veri yüklenemedi"
ile **tüm sayfayı** karartırdı: her portföy, her fiyat, her tahmin, bir kartın
tablosu yok diye. `loadBacktest`'in kuralının aynısı.

**Tablo yoksa kart kendini gizlemiyor, sebebini yazıyor.** Kaybolmuş bir kart,
okuyucuya neden kaybolduğunu öğrenecek hiçbir yol bırakmaz.

**Kartın içinde bir DEFTER var (2026-09-16), ve yeri tesadüf değil.** Sıra
şudur: kuralın şu anki durumu → seviyeler → **defter** → ölçüm. Okuyucu önce
kuralın ne dediğini, sonra parayla ne yaptığını, en sonda da bunu kopyalamaması
gerektiğini söyleyen ölçümü görüyor. Ölçümü defterin üstüne koymak sıralamayı
bozardı: bir kural hakkındaki hüküm, o kuralın ne yaptığı görülmeden okunursa
soyut kalır.

Panel **aynı fonksiyondan** çıkıyor (`bookPanelHtml`, ortak `bookContext`) —
Kanal Finans kartıyla birebir aynı gerekçe. Üç incelik:

- **`hedef %0` basmıyor.** Bu defterin hedef pozisyonu yok; onun yerine
  pozisyondayken **stop**, boştayken **giriş eşiği** yazıyor, ikisi de
  `breakout_state`'ten okunuyor. Sıfır bir hedef, defterin hiçbir zaman
  yaklaşmayacağı bir hedefi iddia eder.
- **İlk dolumdan önce "al-ve-tut'a göre" satırı bu defteri ölçmüyor** ve panel
  bunu yazıyor: defter tam $1.000'da dururken kıyas Eylül başından beri
  koşuyor, yani sayı al-ve-tut'un kendi iki haftasının raporu.
  `renderStrategies`'in defter yaşını basmasıyla aynı disiplin.
- **Canlı grafikte çizgisi defterin AÇILDIĞI günde başlıyor** (`BOOK_OPENED`).
  Eksik nokta `null` dönüyor ve `timeSeriesPanel` kalemi kaldırıyor. Yoksa
  pencerenin başından itibaren düz bir $1.000 çizgisi çizilirdi — ve düz çizgi
  burada nötr bir işaret değil, "bu defter açıktı ve nakitteydi" iddiasıdır.
  Grafiğin altındaki cümle de sonradan açılan defterleri **türeterek** yazıyor;
  "her defter aynı gün başladı" diye sabit yazan sürüm, ikinci bir defter
  eklendiğinde sessizce yanlış olacaktı.

**Kart sekmeye bağlı, o yüzden düzyazısı da öyle olmak zorunda.** 2026-09-16'da
düzeltildi: açıklama bloğu ve dipnot yalnızca **altını** anlatıyordu ("spot
altının hacmi yok", "günde ~200 bin kontrat", gümüşe hiç değinmeyen bir Yahoo
karşılaştırması) ve `Kırılım Takibi — Gümüş` başlığının altında aynen
basılıyordu. Bir kart `asset-scoped` ise metni **ya iki metali de adıyla anmalı**
(ETF kartının "gümüşün al-ve-tut düşüşü %76,3, altınınki %45,6" cümlesi gibi)
**ya da varlık başına ayrılmalı** — `BREAKOUT_VERDICT[...].spotNote` bunun için
var. Üçüncü yol yok: sekmeyi takip eden bir başlığın altına tek metalin sayısını
basmak, okuyucuya o sayının seçili metale ait olduğunu söyler.

> Ve o ayrım **bir etiket değişkeni olamaz**: Türkçe eki çekiyor ("altının" /
> "gümüşün"), yani `${label}'in` biçiminde bir şablon iki metalden biri için
> mutlaka yanlış. Cümle parçası bütün hâlde saklanıyor — kartın yüzde
> cümlelerinin ek almaktan tamamen kaçınmasıyla aynı sebep.

**Günlük maile 2026-09-16'da girdi, ve nasıl girdiği önemli.** Dışarıda
kalma gerekçesi "bu kural hiçbir şey işlemiyor, dolayısıyla maile koyacağı bir
sonuç yok" idi; defter açılınca o gerekçe düştü — `daily_report.py` para olan
şeyleri raporluyor ve artık burada para var. Ama **kendi bölümü değil, portföy
tablosunda bir SATIR**, ve altında `miners`'ınki gibi kendi uyarı satırı
(`BREAKOUT_BOOK`). Ayrı bir bölüm, ölçülerek elenmiş bir kuralı ölçülerek
seçilmiş defterlerle eşit puntoya çıkarırdı — kartın yan kolonda durma
gerekçesinin tam tersi. Uyarı satırı **öne geçtiği haftalarda da** basılıyor,
çünkü tam o hafta en çok gerekiyor.

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
  oku.** Orada ölçülüp elenmiş **on sekiz** hipotez duruyor — oranla ilgili
  bir fikir 8. bölümde, Fed faiziyle ilgili olan 10. bölümde, reel faiz ve
  merkez bankası alımıyla ilgili olan 11. bölümde, yeni bir veri kaynağı
  eklemekle ilgili olan 12. bölümde, "daha çok veriyle eğitelim" ile ilgili
  olan 13. bölümde, altın madencileriyle ilgili olan 14. bölümde,
  komisyon/hesap büyüklüğüyle ilgili olan 15. bölümde,
  "gerçekte hangi enstrümanı alıyorum" ile ilgili olan 16. ve 17.
  bölümde, kırılım/order flow/VWAP/hacim profili ya da bir osilatör onay
  kümesiyle ilgili olan 18. bölümde büyük ihtimalle zaten var.
- **Yeni bir seri denemek isteyince `fetch_data.MACRO_SYMBOLS`'e EKLEME.**
  O sözlük canlı yolu da besliyor (`predict.py` her koşuda her girdiyi
  çekiyor), yani kapıdan geçmemiş bir seri oraya konunca günlük bir istek ve
  sessiz bir arıza yüzeyi satın alınmış olur. Adaylar
  `research/panel.CANDIDATE_SYMBOLS` içinde yaşar ve terfi yolu tektir:
  `drivers.py`'nin Bonferroni eşiği **ve** `lags.py`'nin hizalama taraması —
  ve seri bir **sinyale** girecekse ayrıca `miners.py`'nin maliyet merdiveni.
  Bugüne kadar bu yolculuğu **tek bir seri** tamamladı (`GDX`, 2026-09-10);
  diğer sekiz aday hâlâ adaydır. Bir seri terfi ettiğinde
  `CANDIDATE_SYMBOLS`'tan çıkarılır, yoksa iki yerden birden istenir.
- **Model özelliği olmayacak bir seri `indicators.SIGNAL_ONLY_SERIES`'e
  konur, `CONTEXT_DRIVERS`'a değil.** Ayrım yük taşıyor: `CONTEXT_DRIVERS`
  sınıflandırıcının bölünebileceği rejim bağlamıdır, `SIGNAL_ONLY_SERIES` ise
  bağımsız bir sinyalin okuduğu ama modelin **görmemesi gereken** kolondur.
  `gdx_chg`'i `ml_model.FEATURE_COLUMNS`'a eklemek 5 günlük ufukta ölçülebilir
  hiçbir şey kazandırmaz ve `build_feature_frame` NaN satırı düşürdüğü için
  panelin %18,6'sını sessizce siler.
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
  Bu projede sezgiyle konmuş sayı yok. **Sonra `export_backtest.py`'ı koş ve
  `frontend/data/backtest.json`'u AYNI commit'te ver** — yoksa sayfa eski
  parametrelerin eğrisini yeni sabitlerin yanında çizmeye devam eder, hiçbir
  hata vermeden. Bu dosyanın commit edilme sebebi tam olarak budur
  (`.gitignore`'daki nota bakılabilir: araştırma önbellekleri commit
  edilmiyor, bu ediliyor).
- **Bir kenar bulduğunda, ALINABİLİR enstrümanda da ölç.** Bu depodaki her
  strateji `GC=F`/`SI=F` üzerinde ölçülüyor ve bunlar perakende bir hesabın
  tutamayacağı vadeli kontratlar. `miners`'ın kazancının neredeyse tamamı bir
  **seans sınırı faz kayması** çıktı (vadeli mum ~23 saat, ETF mumu 6,5 saat)
  ve GLD/IAU/SLV'de kayboldu — 16. bölüm. Gün çözünürlüklü bir lag taraması
  bunu göremez. Ölçüm aracı: `research/miners.tradeable_frame` + 4. bölüm.
  Tüm skorbord için cevap `research/instrument.py`'de (17. bölüm): sıralama
  enstrümanla **köklü şekilde** değişiyor, iki yönde birden. İki şart olmadan
  o karşılaştırma geçersizdir — (a) fiyat ölçekleri ETF'in kendi serisinde
  **yeniden ölçülmeli** ama `target_volatility` **değiştirilmemeli** (o bir
  ölçüm değil, risk tercihidir; değiştirmek `voltarget`'ı iki sütunda farklı
  bir strateji yapar), ve (b) **ortak pencere zorunludur** — serbest bırakınca
  vadeli sütun 19,5 yıl, ETF sütunu 16,1 yıl kapsıyor ve aradaki 2008-2011
  altın patlaması tek başına al-ve-tut'un Calmar'ını 0,177'den 0,231'e
  çıkarıyor, yani takvimi ölçüp enstrüman diye raporlamış olursun.
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
