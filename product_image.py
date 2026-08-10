from openai import OpenAI

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def generate_model_photo(product_title, product_description):
    """Urunu tasiyan/sergileyen profesyonel bir yapay zeka manken gorseli uretir.

    Shopify'a dogrudan yuklenebilecek base64 PNG verisi dondurur.
    """
    prompt = (
        f"Professional e-commerce catalog photo: a realistic AI-generated model "
        f"showcasing the product '{product_title}'. {product_description} "
        f"Studio lighting, clean neutral background, high-end fashion/product "
        f"catalog style, photorealistic, no text or watermark."
    )
    client = _get_client()
    result = client.images.generate(model="gpt-image-2", prompt=prompt, size="1024x1024")
    return result.data[0].b64_json


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
