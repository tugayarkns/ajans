# AJANS — Multi-Agent Sipariş Yönetim Sistemi

Anthropic API üzerinden çalışan, Türkçe bir çoklu-ajan sipariş yönetim
sistemi. Bir "Master Agent" gelen siparişi analiz eder ve sırasıyla
Order → Supplier → Payment → Shipping → Notify ajanlarını yönlendirir.
Gerçek bir Shopify mağazasına bağlanır: `shopify` komutu mağazadaki yeni
siparişleri çekip otomatik olarak bu ajan zincirinden geçirir, `urunler`
komutu ise yeni ürünleri (yapay zeka manken görseliyle birlikte) mağazaya
ekler. `otomatik` komutuyla ikisi de sürekli, kendi kendine çalışır.

## Ajanlar

| Ajan | Rol |
|---|---|
| `MASTER_AGENT` | Koordinatör — süreci baştan sona yönetir |
| `ORDER_AGENT` | Siparişi doğrular |
| `SUPPLIER_AGENT` | Tedarikçi/fiyat karşılaştırması yapar |
| `PAYMENT_AGENT` | Ödeme akışını yönetir |
| `SHIPPING_AGENT` | Kargo firması seçer, gönderim yapar |
| `NOTIFY_AGENT` | Müşteriye bildirim gönderir |
| `PRODUCT_AGENT` | Yeni ürünleri fiyat/açıklama açısından değerlendirir |
| `MARKETING_AGENT` | Ücretsiz kanallardan müşteri kazanım planı üretir |
| `SUPPORT_AGENT` | Müşteri destek/iade mesajlarını yanıtlar |

## Kurulum

```bash
pip install -r requirements.txt
python main.py
```

`.env` dosyasında şunlar tanımlı olmalı (`.env` `.gitignore` ile takip dışı
bırakılmıştır):

```
ANTHROPIC_API_KEY=<Anthropic API anahtarın>
SHOPIFY_STORE_DOMAIN=<magaza-adin>.myshopify.com
SHOPIFY_CLIENT_ID=<Shopify custom app Client ID>
SHOPIFY_CLIENT_SECRET=<Shopify custom app Client Secret>
OPENAI_API_KEY=<OpenAI API anahtarın>
EBAY_CLIENT_ID=<eBay Production keyset App ID>
EBAY_CLIENT_SECRET=<eBay Production keyset Cert ID>
EBAY_REFRESH_TOKEN=<bir kerelik OAuth consent'ten alinan refresh token>
```

Shopify tarafında bir **custom app** (Dev Dashboard üzerinden) oluşturup
`read_orders, write_orders, read_products, write_products,
read_fulfillments, write_fulfillments, read_customers` izinleriyle mağazana
kurman gerekiyor — detaylar için [`CLAUDE.md`](./CLAUDE.md) → "Shopify
integration" bölümüne bak. `OPENAI_API_KEY`, ürün görseli üretimi için
platform.openai.com üzerinden alınır (Anthropic'ten ayrı bir hesap/anahtar).
`EBAY_*` değerleri developer.ebay.com'da bir Production keyset ve bir kerelik
OAuth consent ile alınır — adımlar için [`CLAUDE.md`](./CLAUDE.md) → "eBay
integration" bölümüne bak.

## Komutlar (uygulama içi)

- Serbest metin → yeni sipariş olarak işlenir (Master Agent çağrılır)
- `ajan <AGENT_ADI>` → belirli bir ajanı doğrudan çağırır (örn. `ajan ORDER_AGENT`)
- `loglar` → işlenen siparişleri listeler
- `shopify` → mağazadaki ödemesi tamamlanmış, henüz işlenmemiş siparişleri
  çekip ajan zincirinden geçirir (her sipariş Shopify'da `ajans-islendi`
  etiketiyle işaretlenir, tekrar işlenmez)
- `ebay` → eBay'deki kargolanmamış siparişleri çekip aynı ajan zincirinden
  geçirir (işlenenler `inventory.db`'de kaydedilir, tekrar işlenmez)
- `urunler` → `products.json`'daki yeni ürünleri (henüz mağazada olmayanları)
  Product Agent'tan geçirip Shopify'a ekler, yapay zeka manken görseli üretip
  ürüne yükler
- `otomatik` → `urunler` + `shopify` + `ebay`'i sırayla, sürekli (varsayılan
  5 dakikada bir) tekrarlar; durdurmak için Ctrl+C (programı kapatmaz,
  menüye döner)
- `pazarlama` → mağazadaki aktif ürünler için Marketing Agent'tan ücretsiz
  müşteri kazanım planı üretir
- `çık` → programı kapatır

## ⚠️ Sipariş geldiğinde ne olur (önemli)

Ajanlar siparişi analiz edip metin üretir, ama **tedarikçiye (DSers/AliExpress)
gerçek sipariş geçmez** — kargo da göndermez. Bu yüzden her işlenen siparişten
sonra panele kırmızı bir "ELLE İŞLEM GEREKİYOR" uyarısı düşer ve hangi
üründen kaç adet sipariş etmeniz gerektiğini yazar. Satış geldiğinde
tedarikçi siparişini elle geçmeniz gerekir.

## Canlı panel ve ürün onay kuyruğu

Program başladığında `http://127.0.0.1:8765` adresinde otomatik bir panel
açılır (URL konsola yazdırılır). Panel şunları gösterir:

- Yüklü ajan sayısı, otomatik mod durumu, son kontrol zamanı
- Canlı olay akışı (siparişler, ürün ekleme/hataları, pazarlama planları)
- **Onay bekleyen yeni ürünler** — tedarikçiden (örn. DSers/AliExpress)
  bulunan ürün adayları buraya düşer; her kartta gerçek maliyet/kâr marjı,
  tüm ürün görselleri ve `PRODUCT_AGENT`'ın ürettiği nihai açıklama önceden
  gösterilir (onay öncesi hiçbir içerik arka planda üretilmez). "Onayla ve
  Yayınla" tek tıkla ürünü gerçek/aktif olarak Shopify'a ekler; "Reddet"
  sadece kuyruktan kaldırır. Adaylar `pending_products.json`'da tutulur
  (gitignored, çalışma zamanı verisi — `products.json`'dan farklı olarak
  git'e commit edilmez).

Bu kuyruğa ürün eklemek şu an elle yapılıyor (bir DSers arama sonucu
`panel.add_pending_products()`'a verilir) — `main.py`'nin otomatik
döngüsüne henüz bağlı bir tedarikçi keşif adımı yok.

## Yeni ajan ekleme

`agents/` klasörüne `<isim>_agent.md` formatında bir dosya eklemek yeterli;
`## Rol`, `## Görevler` ve bir `## Çıktı` bölümü içermeli. Dosya adı
(büyük harfe çevrilip `.md` uzantısı silinerek) ajan anahtarı olur — örn.
`shipping_agent.md` → `SHIPPING_AGENT`. Kod değişikliği gerekmez.

## Geliştirme

Lint: `ruff check .` (bkz. `ruff.toml`)

Detaylı geliştirici notları için [`CLAUDE.md`](./CLAUDE.md) dosyasına bakın.
