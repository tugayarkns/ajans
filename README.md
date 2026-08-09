# AJANS — Multi-Agent Sipariş Yönetim Sistemi

Anthropic API üzerinden çalışan, Türkçe bir çoklu-ajan sipariş yönetim
sistemi. Bir "Master Agent" gelen siparişi analiz eder ve sırasıyla
Order → Supplier → Payment → Shipping → Notify ajanlarını yönlendirir.
Gerçek bir Shopify mağazasına bağlanır: `shopify` komutu mağazadaki yeni
siparişleri çekip otomatik olarak bu ajan zincirinden geçirir.

## Ajanlar

| Ajan | Rol |
|---|---|
| `MASTER_AGENT` | Koordinatör — süreci baştan sona yönetir |
| `ORDER_AGENT` | Siparişi doğrular |
| `SUPPLIER_AGENT` | Tedarikçi/fiyat karşılaştırması yapar |
| `PAYMENT_AGENT` | Ödeme akışını yönetir |
| `SHIPPING_AGENT` | Kargo firması seçer, gönderim yapar |
| `NOTIFY_AGENT` | Müşteriye bildirim gönderir |

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
```

Shopify tarafında bir **custom app** (Dev Dashboard üzerinden) oluşturup
`read_orders, write_orders, read_products, read_fulfillments,
write_fulfillments, read_customers` izinleriyle mağazana kurman gerekiyor —
detaylar için [`CLAUDE.md`](./CLAUDE.md) → "Shopify integration" bölümüne bak.

## Komutlar (uygulama içi)

- Serbest metin → yeni sipariş olarak işlenir (Master Agent çağrılır)
- `ajan <AGENT_ADI>` → belirli bir ajanı doğrudan çağırır (örn. `ajan ORDER_AGENT`)
- `loglar` → işlenen siparişleri listeler
- `shopify` → mağazadaki ödemesi tamamlanmış, henüz işlenmemiş siparişleri
  çekip ajan zincirinden geçirir (her sipariş Shopify'da `ajans-islendi`
  etiketiyle işaretlenir, tekrar işlenmez)
- `çık` → programı kapatır

## Yeni ajan ekleme

`agents/` klasörüne `<isim>_agent.md` formatında bir dosya eklemek yeterli;
`## Rol`, `## Görevler` ve bir `## Çıktı` bölümü içermeli. Dosya adı
(büyük harfe çevrilip `.md` uzantısı silinerek) ajan anahtarı olur — örn.
`shipping_agent.md` → `SHIPPING_AGENT`. Kod değişikliği gerekmez.

## Geliştirme

Lint: `ruff check .` (bkz. `ruff.toml`)

Detaylı geliştirici notları için [`CLAUDE.md`](./CLAUDE.md) dosyasına bakın.
