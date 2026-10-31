"""KuCoin P2P: GET www.kucoin.com/_api/otc/ad/list, no key. Side words: SELL is the list of ads that sell dollars (the reader buys). The
price of an ad is 1 / fiatToCryptoPrice."""
from collectors.boards import num

NAME = "kucoin"
REGISTRY = "KuCoin P2P"
PAGE_ROWS = 20
URL = "https://www.kucoin.com/_api/otc/ad/list"
HEADERS = {"User-Agent": "margin.wiki/1.0 (+https://margin.wiki)"}


def request(cfg, side, page):
    return {"method": "GET", "url": cfg.get("endpoint") or URL, "headers": HEADERS,
            "params": {"currency": cfg.get("pair", "USDT"), "legal": cfg["ccy"], "side": side, "page": page, "pageSize": PAGE_ROWS}}


def parse(payload, side):
    if not isinstance(payload, dict) or not payload.get("success") or not isinstance(payload.get("items"), list):
        raise ValueError("not a KuCoin ad list")
    out = []
    for x in payload["items"]:
        f = num((x or {}).get("fiatToCryptoPrice"))
        if f == "":
            continue
        out.append({"price": 1.0 / f, "available": "", "min_order": num(x.get("limitMinQuote")), "max_order": num(x.get("limitMaxQuote")),
                    "seller": "", "completion_rate": "", "order_count": "", "merchant": False})
    return out
