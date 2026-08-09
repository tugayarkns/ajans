# AJANS — Multi-Agent Sipariş Yönetim Sistemi

Anthropic API üzerinden çalışan, Türkçe bir çoklu-ajan sipariş yönetim
demosu. Bir "Master Agent" gelen siparişi analiz eder ve sırasıyla
Order → Supplier → Payment → Shipping → Notify ajanlarını yönlendirir.

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

`.env` dosyasında `ANTHROPIC_API_KEY=<kendi-anahtarın>` tanımlı olmalı
(`.env` `.gitignore` ile takip dışı bırakılmıştır).

## Komutlar (uygulama içi)

- Serbest metin → yeni sipariş olarak işlenir (Master Agent çağrılır)
- `ajan <AGENT_ADI>` → belirli bir ajanı doğrudan çağırır (örn. `ajan ORDER_AGENT`)
- `loglar` → işlenen siparişleri listeler
- `çık` → programı kapatır

## Yeni ajan ekleme

`agents/` klasörüne `<isim>_agent.md` formatında bir dosya eklemek yeterli;
`## Rol`, `## Görevler` ve bir `## Çıktı` bölümü içermeli. Dosya adı
(büyük harfe çevrilip `.md` uzantısı silinerek) ajan anahtarı olur — örn.
`shipping_agent.md` → `SHIPPING_AGENT`. Kod değişikliği gerekmez.

## Geliştirme

Lint: `ruff check .` (bkz. `ruff.toml`)

Detaylı geliştirici notları için [`CLAUDE.md`](./CLAUDE.md) dosyasına bakın.
