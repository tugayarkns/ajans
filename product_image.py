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
