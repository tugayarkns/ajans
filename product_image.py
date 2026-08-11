"""Marka gorseli uretimi (OpenAI).

DIKKAT: Burada bilerek **urun** gorseli ureten bir fonksiyon yoktur.
Eskiden `generate_model_photo()` / `generate_model_photos()` vardi ve eksik
urun fotograflarini yapay zekayla tamamliyordu; bu kaldirildi cunku uretilen
gorsel musteriye gidecek gercek urunu gostermiyor — dikis, renk, cep sayisi
gibi detaylar tutmuyor ve bu dogrudan **iade riski** demek. Urun gorselleri
artik yalnizca tedarikcinin gercek fotograflaridir (bkz. panel.py
attach_product_images ve CLAUDE.md "Urun gorselleri" bolumu).

Logo uretimi kaliyor: marka gorseli bir urunu temsil etmiyor, dolayisiyla
ayni riski tasimiyor.
"""

from openai import OpenAI

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def generate_logo(brand_name="NorvexGet", size="1024x1024"):
    """Marka icin ikon+yazi (wordmark) logo uretir.

    Shopify/eBay profil fotografi veya banner olarak kullanilabilecek
    base64 PNG verisi dondurur.
    """
    prompt = (
        f"Professional modern minimal logo for an e-commerce brand called "
        f"'{brand_name}'. Icon + wordmark combination mark, clean geometric "
        f"symbol paired with the brand name in a modern sans-serif typeface. "
        f"Neutral, versatile style suitable for a general lifestyle/tech "
        f"accessories store (desk, car, and home gadgets) — not tied to any "
        f"single product category. Flat vector design, solid clean "
        f"background, high contrast, no gradients, no photorealism, no "
        f"mockup, no extra text."
    )
    client = _get_client()
    result = client.images.generate(model="gpt-image-2", prompt=prompt, size=size)
    return result.data[0].b64_json
