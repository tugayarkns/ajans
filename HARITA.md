# HARİTA — Projenin Numaralı Listesi

Bu liste, sistemin **her parçasını sırayla numaralandırır**. Her numara bir
işi/istasyonu anlatır: orada ne olur, bozulursa ne görürsün.

**Nasıl kullanılır:** Bir hata gördüğünde numarasını yaz — örnek: `8 bozuk`,
`12'de hata var`, `25 çalışmıyor`. Ben sadece o bölgeye bakarım, tüm projeyi
okumam; böylece hem daha hızlı hem daha ucuz olur.

Numaralar sistemdeki **akış sırasına** göredir: ürün bulunur (1-6), yayınlanır
(7-16), sipariş gelir (17-27), stok güncellenir (28-30), panelden izlenir
(31-38), ayarlar en sonda (39-48).

## Hızlı eşleme: ne görüyorsun → hangi numara

| Gördüğün sorun | Numara |
|---|---|
| Ürün az/alakasız fotoğrafla çıkıyor | **8**, **9** |
| Ürün mağazada görünmüyor (taslakta kaldı) | **8**, **7** |
| İyi ürün boşuna eleniyor / kötü ürün geçiyor | **1b** |
| Panelde hiç aday ürün belirmiyor | **1**, **1b** |
| Yeni ürün Shopify'a eklenmiyor | **7** |
| eBay'e yayın hatası (kategori / zorunlu alan) | **12**, **13** |
| eBay fiyatı yanlış, kur eski | **14**, **40** |
| Başlık kesik görünüyor | **15** |
| Rakip sayısı görünmüyor | **15b** |
| Ürünlerimi gözden geçirmek istiyorum | **10b** |
| Kod değişikliğinden sonra bir şey bozuldu mu bilmiyorum | **10c** |
| Eksik fotoğraflı ürünleri görmek istiyorum | **10** |
| Stok yanlış / aşırı satış | **28**, **29**, **30** |
| Sipariş iki kez işleniyor | **19** |
| Tedarikçiye sipariş hatırlatması | **26**, **27** |
| Panele giriş yapılamıyor | **32**, **33** |
| Panel hiç açılmıyor | **31** |
| Ajanın yazdığı metin/başlık kötü | **3**, **20-25** |
| Ciro/sipariş rakamları yanlış | **35** |
| "Yetkisiz / 401 / 403" tipi hatalar | **39**, **41** |

---

## A. ÜRÜN BULMA VE ONAY (1-6)

**1 — Ürün avcısı (keşif botu girişi)**
Dışarıdaki günlük bot, bulduğu yeni ürün adaylarını buradan sisteme yollar.
Kapıda şifre (token) sorulur, çünkü gönderen bir program, insan değil. Botun
uyması gereken kurallar `agents/scout_agent.md`'de yazılı.
*Bozulursa:* Panelde hiç yeni aday ürün belirmez.
`panel.py → _handle_discovery_submit`

**1b — ÜRÜN SEÇİM POLİTİKASI (güven kapısı) ⭐**
Gelen her aday buradan geçer: tedarikçi puanı 4.6'nın altındaysa, 1000'den az
satmışsa, 6'dan az gerçek fotoğrafı varsa, stoğu azsa, fiyatı 40 EUR'yu
aşıyorsa veya iade riski yüksek bir tipse (beden gerektiren, belirli telefona
özel, cam/kırılabilir, kozmetik, pilli, taklit şüpheli, montaj isteyen)
**kuyruğa hiç alınmaz**. Botun kendi puanına güvenilmez, puan burada yeniden
hesaplanır.
*Bozulursa:* Riskli ürünler kuyruğa sızar ya da iyi ürünler boşuna elenir.
`trust_score.py` + `panel.py → screen_candidate`

**2 — Onay bekleyen ürünler kuyruğu**
Kapıyı geçen adaylar burada bekler. Hiçbir ürün sen onaylamadan mağazaya
çıkmaz. Puanı yüksek olan üste gelir. Program kapansa da kuyruk kaybolmaz.
Elenen adaylar ayrı bir "Elenen Adaylar" tablosunda sebebiyle görünür.
*Bozulursa:* Adaylar kaybolur ya da sıralama karışır.
`panel.py → add_pending_products` + `pending_products.json`

**3 — Ürün metnini yazan ajan**
Aday ürünün başlığını ve satış açıklamasını yapay zeka yazar. Bu iş, sen
onaylamadan ÖNCE biter; yani panelde gördüğün metin ürünün son halidir.
*Bozulursa:* Başlık/açıklama saçma, eksik veya İngilizce-Türkçe karışık gelir.
`agents/product_agent.md` + `panel.py → _generate_listing`

**4 — Panelde ürün kartı**
Adayın resimlerini, fiyatını, puanını gördüğün kart. Küçük resimlere tıklayınca
büyük resim değişir.
*Bozulursa:* Resim gözükmez, kart bozuk görünür, tıklama çalışmaz.
`panel.py → _PAGE_HTML (ürün kartı bölümü)`

**5 — "Onayla ve Yayınla" düğmesi**
Bastığın an ürün gerçekten Shopify'a ve eBay'e çıkar. Buradan sonrası
otomatiktir.
*Bozulursa:* Düğme çalışmaz veya "yayınlandı" der ama mağazada ürün yoktur.
`panel.py → _publish_product`

**6 — Toplu ürün ekleme (`urunler` komutu)**
Elindeki hazır ürün listesindeki (products.json) ürünleri tek seferde mağazaya
ekler. Panelden tek tek onaylamanın alternatifidir.
*Bozulursa:* Komut hiç ürün eklemez ya da "zaten mağazada" der geçer.
`main.py → list_products`

---

## B. MAĞAZAYA YAYINLAMA (7-16)

**7 — Shopify'da ürünü açma**
Ürünü kendi mağazanda oluşturur: başlık, açıklama, fiyat.
*Bozulursa:* "Shopify'a eklenemedi" hatası; ürün mağazada görünmez.
`shopify_client.py → create_product`

**8 — Ürün fotoğrafları (EN AZ 6 GERÇEK FOTOĞRAF) ⭐**
Her ürün en az 6 **gerçek tedarikçi** fotoğrafıyla çıkar. Yapay zeka fotoğrafı
artık kesinlikle kullanılmıyor — müşteriye gidecek gerçek ürünü göstermediği
için iade sebebiydi. 6'ya ulaşılamazsa ürün **satışa açılmaz**, Shopify'da
gizli taslak olarak kalır ve eBay'e hiç gönderilmez.
*Bozulursa:* Ürün taslakta takılı kalır; panelde kırmızı "yayınlanmadı" satırı.
`panel.py → attach_product_images` + `publish_dual_channel`

**9 — Gerçek fotoğraflar nereden geliyor**
Tedarikçiden. DSers'te ürün **arandığında tek** fotoğraf gelir — tek resim
probleminin sebebi buydu. Gerçek galeri (10-20 fotoğraf) ancak ürün DSers'e
import edilip önizlemesi çekildiğinde geliyor. Keşif botu bunu yapmak
zorunda; kuralı `agents/scout_agent.md`'de yazılı.
*Bozulursa:* Adaylar 6 fotoğraf şartına takılıp elenir.
`agents/scout_agent.md` (DSers import → preview akışı)

**10 — Eksik fotoğraflı ürünleri listeleme (`gorseller` komutu)**
Yayındaki ürünlerden fotoğrafı 6'nın altında kalanları listeler. Kendi başına
tamamlayamaz (gerçek fotoğraf sadece DSers'te var, program oraya erişemez) —
Claude Code oturumunda "eksik görselleri tamamla" demen gerekir.
*Bozulursa:* Eksik ürünler görünmez olur.
`main.py → backfill_product_images`

**10b — Katalog denetimi (`denetim` komutu + otomatik arka plan)**
Mağazadaki her ürünü iade riskine göre tarar ve **KALSIN / DÜZELT / KALDIR**
önerisi verir. Hiçbir şeyi kendi değiştirmez, karar senin. `otomatik` modda
elle çalıştırmana gerek yok — arka planda **saatte bir kendi kendine** çalışır;
sorun varsa (KALDIR/DÜZELT çıkarsa) panelde kırmızı bir olay bırakır, katalog
tertemizse sessiz kalır.
*Bozulursa:* Rapor boş çıkar veya yanlış ürünü işaretler.
`main.py → audit_catalog` + `run_automatic`

**10c — Kural doğrulama testi (`test_policy.py`)**
Ürün seçim kurallarının (10 numaralı fotoğraf şartı, 1b'deki eleme kuralları,
15b'deki rakip sayacı) doğru çalıştığını kontrol eden bir kendi kendine test.
Terminalde `python test_policy.py` ile çalıştırılır. Bu proje üzerinde kod
değişikliği yapılırken bu dosya çalıştırılıp hepsinin ✅ olduğu görülmeli —
aynı hata (örn. "bagaj" kelimesini ayakkabı sanmak) sessizce geri gelmesin
diye var.
*Bozulursa (kırmızı ❌ satırı çıkarsa):* Az önce yapılan kod değişikliği ürün
seçim kurallarını bozmuş demektir — mağazaya yansımadan yakalanır.
`test_policy.py`

**11 — Ürüne numara (SKU) verme**
Her ürüne `AJANS-001`, `AJANS-002` gibi bir kod verilir. Shopify'daki ürünle
eBay'deki ilanın aynı ürün olduğunu sistem bu kodla anlar.
*Bozulursa:* Stok takibi şaşar, aynı ürün iki farklı ürün sanılır.
`panel.py → _next_sku` + `shopify_client.py → update_variant_sku`

**12 — eBay'e yayınlama**
Aynı ürünü eBay'de de açar. Birden fazla eBay ülkesi (Avusturya, Amerika)
ayarlıysa her birine ayrı ayrı yayınlar; biri hata verirse diğerleri devam eder.
*Bozulursa:* Panelde kırmızı "eBay'e yayınlanamadı" satırı; ürün Shopify'da var
ama eBay'de yok.
`panel.py → sync_ebay_listing` ve `_publish_to_ebay`

**13 — eBay kategori ve zorunlu bilgi doldurma**
eBay her ürünü bir kategoriye koymanı ve o kategorinin zorunlu tuttuğu bilgileri
(marka, üretici, ürün tipi gibi) doldurmanı ister. Sistem bunları otomatik bulup
doldurur; bilmediği ölçü gibi bilgilere asla uydurma değer yazmaz.
*Bozulursa:* "kategori bulunamadı" veya Almanca zorunlu-alan hatası ile yayın
başarısız olur. eBay hatalarının en sık sebebi burasıdır.
`ebay_client.py → suggest_category, get_required_aspects`

**14 — eBay fiyat çevirisi**
Mağaza fiyatların Euro. Amerika gibi Euro kullanmayan sitelere yayınlarken
fiyatı o paraya çevirir. Kur elle yazılıdır, zamanla eskir.
*Bozulursa:* Ürünü olduğundan ucuza satarsın — para kaybı. Kur güncellenmeli.
`ebay_client.py → EUR_EXCHANGE_RATES, convert_price_from_eur`

**15 — eBay başlık kısaltma**
eBay başlıkta 80 harf sınırı koyar. Sistem başlığı kelimenin ortasından değil,
son boşluktan keser.
*Bozulursa:* Başlık kelime ortasından kesik görünür, ilan güvensiz durur.
`ebay_client.py → _truncate_title`

**15b — Rakip ilan sayacı (gözden kaçan ürün ölçüsü)**
Bir ürün için eBay'de kaç rakip ilan olduğunu sayar. Az rakip = gözden kaçmış
fırsat, çok rakip = doymuş pazar. Güven skorunun bir parçası.
*Bozulursa:* Sessizce devre dışı kalır, skor o kalemi nötr sayar (hata vermez).
`ebay_client.py → count_competing_listings`

**16 — eBay'in geçici hataları**
eBay bazen sebepsiz hata döner. Sistem sadece bu tip geçici hataları birkaç kez
tekrar dener; gerçek hataları (eksik bilgi vb.) boşuna tekrarlamaz.
*Bozulursa:* Yayın ilk denemede takılır kalır.
`ebay_client.py → _request (retry bölümü)`

---

## C. SİPARİŞ İŞLEME (17-27)

**17 — Shopify siparişlerini toplama (`shopify` komutu)**
Mağazadaki yeni, gönderilmemiş siparişleri çeker.
*Bozulursa:* Yeni siparişler sisteme hiç düşmez.
`main.py → check_shopify_orders`

**18 — eBay siparişlerini toplama (`ebay` komutu)**
Aynı işi eBay için yapar.
*Bozulursa:* eBay siparişleri işlenmez.
`main.py → check_ebay_orders`

**19 — Aynı siparişi iki kez işlememe**
Shopify'da sipariş "ajans-islendi" diye etiketlenir; eBay'de böyle bir imkan
olmadığı için işlenen sipariş numaraları kendi veritabanımıza yazılır.
*Bozulursa:* Aynı sipariş tekrar tekrar işlenir (veya hiç işlenmez).
`shopify_client.py → mark_processed` + `inventory_db.py → mark_order_processed`

**20 — Şef ajan (Master)**
Siparişi alır, hangi ajanın ne yapacağını dağıtır. Sistemin beyni.
*Bozulursa:* Hiçbir ajan çalışmaz, zincir baştan durur.
`agents/master_agent.md` + `main.py → process_order`

**21 — Sipariş ajanı**
Siparişin içeriğini düzenler: müşteri, ürün, adet, adres.
`agents/order_agent.md`

**22 — Tedarikçi ajanı**
Ürünün tedarikçiden nasıl alınacağını yazar.
`agents/supplier_agent.md`

**23 — Ödeme ajanı**
Ödeme durumunu ve kâr hesabını yazar.
`agents/payment_agent.md`

**24 — Kargo ajanı**
Kargo/teslimat sürecini yazar (3 gün hazırlık süresi dahil).
`agents/shipping_agent.md`

**25 — Bilgilendirme ajanı**
Müşteriye gidecek bilgilendirme metnini yazar.
`agents/notify_agent.md`

**26 — TEDARİKÇİ SİPARİŞİ HATIRLATICISI ⚠️ (en kritik yer)**
Ajanlar sadece **metin** yazar — hiçbiri gerçekten AliExpress'ten sipariş
vermez, gerçek kargo etiketi almaz. Bu yüzden her sipariş sonrası panelde en
üstte kırmızı bir görev satırı açılır: "bu siparişi tedarikçiye elle ver".
Bunu sen yapmazsan **müşteri parayı ödemiş ama ürün hiç gönderilmemiş olur**.
*Bozulursa:* Kırmızı görev satırı çıkmaz — ödenmiş sipariş sessizce kaybolur.
`main.py → _warn_supplier_order_required` + `inventory_db.py → add_supplier_task`

**27 — "Sipariş verdim" düğmesi**
26'daki kırmızı görevi kapattığın düğme. Kayıt silinmez, "yapıldı" işaretlenir.
*Bozulursa:* Görev listesi hiç temizlenmez ya da yanlış görev kapanır.
`panel.py → _handle_supplier_task_done`

---

## D. STOK TAKİBİ (28-30)

**28 — Stok eşitleme (`stok` komutu)**
Shopify ve eBay birbirinin stoğunu bilmez. Bu bölüm ikisini karşılaştırıp
ortak bir stok havuzu tutar; bir yerde satılan ürünün adedini diğerinden düşer.
*Bozulursa:* Elde olmayan ürünü satarsın (aşırı satış) veya stok boş görünür.
`main.py → sync_inventory`

**29 — Stok veritabanı**
Stok bilgisinin, işlenmiş siparişlerin ve tedarikçi görevlerinin tutulduğu
yerel dosya (inventory.db).
*Bozulursa/silinirse:* İşlenmiş eBay siparişleri baştan işlenir, görevler
kaybolur.
`inventory_db.py`

**30 — "Stok takibi kapalı" ürün kuralı**
Dropshipping ürünlerinde Shopify stok takibi kapalıdır ve stoğu "0" gösterir —
ama ürün aslında sınırsız satılabilir. Sistem bu 0'ı gerçek stok saymaz.
*Bozulursa:* Sistem her şeyi tükendi sanıp eBay stoklarını sıfırlar.
`shopify_client.py → get_product_quantity`

---

## E. PANEL VE İZLEME (31-38)

**31 — Panel sunucusu**
Program açıldığında tarayıcıdan girdiğin canlı ekranı yayınlar; adresi ekranda
yazar. Başka cihazlardan da girilebilir.
*Bozulursa:* Panel açılmaz, adres cevap vermez.
`panel.py → start`

**32 — Panel giriş ekranı (şifre)**
Panel dışarıya açık olduğu için e-posta+şifre ister.
*Bozulursa:* Giriş yapılamaz veya sürekli giriş ekranına atar.
`panel.py → _handle_login` + `panel_auth.py`

**33 — Admin yönetimi (`admin-ekle` / `admin-liste` / `admin-sil`)**
Panele kim girebilir, buradan belirlenir.
`main.py menü` + `panel_auth.py`

**34 — Olay akışı (yeşil/kırmızı satırlar)**
Sistemin her yaptığı iş buraya bir satır olarak düşer. Yeşil: başarılı.
Kırmızı: hata — **kırmızıları okumadan geçme.**
*Bozulursa:* Hatalar görünmez olur.
`panel.py → log_event` + `activity_log.jsonl`

**35 — Ciro ve sipariş özeti**
Son 7 günün sipariş sayısı ve cirosu; Shopify ve eBay ayrı ayrı. 10 dakikada
bir kendi kendine yenilenir.
*Bozulursa:* Rakamlar boş, sıfır veya eski kalır.
`panel.py → _refresh_analytics`

**36 — Mağaza ve ürün linkleri**
Panelden ürünün Shopify/eBay sayfasına tıklayıp gitmeni sağlar.
*Bozulursa:* Link yanlış ürüne gider veya açılmaz.
`panel.py → _store_links, _shopify_product_url, _ebay_item_url`

**37 — Logo ve marka görselleri**
NorvexGet logosunun panelde ve mağazada kullanılan halleri.
`assets/logo/` + `product_image.py → generate_logo`

**38 — Otomatik mod (`otomatik` komutu)**
Ürün ekleme + sipariş kontrolü + stok eşitlemeyi 5 dakikada bir kendi kendine
tekrarlar. Ctrl+C ile menüye döner. **Bilgisayar açık kalmalı.**
*Bozulursa:* Döngü durur veya aynı hatayı sonsuz tekrarlar.
`main.py → run_automatic`

---

## F. AYARLAR VE DOSYALAR (39-48)

**39 — `.env` — bütün şifreler ve anahtarlar**
Anthropic, OpenAI, Shopify, eBay anahtarları burada. En sık hata kaynağı:
süresi dolmuş veya eksik anahtar.
*Bozulursa:* "ayarları eksik", "yetkisiz", "401/403" tipi hatalar.

**40 — eBay ülke ayarları**
Her eBay ülkesi için ayrı kargo/ödeme/iade kuralı ve depo kodu gerekir
(`EBAY_AT_...`, `EBAY_US_...`). Biri eksikse o ülkeye yayın yapılamaz.
*Bozulursa:* Sadece o ülkede yayın başarısız olur, diğerleri çalışır.

**41 — eBay giriş izni (refresh token)**
eBay'e senin adına işlem yapma izni. Yaklaşık 18 ayda bir tarayıcıdan elle
yenilenmesi gerekir.
*Bozulursa:* Tüm eBay işlemleri durur.

**42 — `products.json` — hazır ürün listesi**
6 numaralı toplu ekleme komutunun okuduğu liste. Buradaki ürünlerde de
`image_urls` (en az 6 gerçek fotoğraf) olmalı, yoksa yayınlanmaz.

**43 — `pending_products.json` — onay bekleyenler dosyası**
2 numaradaki kuyruğun diske yazılmış hali.

**44 — `activity_log.jsonl` — olay geçmişi**
34 numaradaki satırların kalıcı kaydı; program kapansa da durur.

**45 — `panel_admins.json` — panel kullanıcıları**
Şifreler şifrelenmiş halde tutulur, düz metin değildir.

**46 — Yapay zeka modeli**
Sistem `claude-opus-5` modelini kullanır; ajanların düşünen tarafı budur.
`main.py → MODEL`

**47 — Programı başlatma**
`python main.py` ile açılır; `start_ajans.bat` ve `service.py` arka planda
başlatmak içindir.

**48 — Dokümanlar**
`CLAUDE.md` (teknik hafıza), `README.md` (kullanım), `PAZARLAMA_PLANI.md`,
`STORE_PAGES.md`, `HARITA.md` (bu dosya), `agents/scout_agent.md` (keşif
botunun uyacağı ürün seçim kuralları).

---

## Yapamadıklarımız (hata sanma, sistemde yok)

- **Tedarikçiye otomatik sipariş verilemiyor.** DSers bağlantısı sadece ürün
  bulma/aktarma yapıyor, sipariş verme özelliği sunmuyor. Bu yüzden 26 numara
  var — o adımı elle sen yapıyorsun.
- **Gerçek kargo etiketi alınmıyor, takip numarası üretilmiyor.** Ajanların
  yazdığı kargo/takip metinleri örnek metindir, gerçek değildir.
- **Panel bir siteye kurulu değil.** Sadece senin bilgisayarında çalışır;
  bilgisayar kapalıyken panel de keşif botu da çalışmaz.
