"""Binance P2P: POST p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search, no key. Side words BUY and SELL (BUY = the reader buys dollars)."""
from collectors.boards import num

NAME = "binance"
REGISTRY = "binance_p2p"
PAGE_ROWS = 20
URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def request(cfg, side, page):
    return {"method": "POST", "url": cfg.get("endpoint") or URL, "headers": HEADERS,
            "json": {"page": page, "rows": PAGE_ROWS, "asset": cfg.get("pair", "USDT"), "fiat": cfg["ccy"], "tradeType": side,
                     "payTypes": [], "publisherType": None}}


def parse(payload, side):
    if not isinstance(payload, dict) or "data" not in payload or str(payload.get("code")) not in ("000000", "None"):
        raise ValueError("not a Binance ad list")
    out = []
    for row in payload.get("data") or []:
        adv, who = (row or {}).get("adv") or {}, (row or {}).get("advertiser") or {}
        if num(adv.get("price")) == "":
            continue
        out.append({"price": num(adv.get("price")), "available": num(adv.get("tradableQuantity")),
                    "min_order": num(adv.get("minSingleTransAmount")), "max_order": num(adv.get("maxSingleTransAmount")),
                    "seller": who.get("userNo") or "", "completion_rate": num(who.get("monthFinishRate")),
                    "order_count": num(who.get("monthOrderCount")), "merchant": str(who.get("userType") or "").lower() == "merchant"})
    return out
