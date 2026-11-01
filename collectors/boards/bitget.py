"""Bitget P2P: POST www.bitget.com/v1/p2p/pub/adv/queryAdvList, no key. Side words: 1 is the list of ads that sell dollars (the reader
buys, the higher prices), 2 the list of ads that buy them. Checked live on 31 Oct 2026 for NGN."""
from collectors.boards import num

NAME = "bitget"
REGISTRY = "Bitget P2P"
PAGE_ROWS = 20
URL = "https://www.bitget.com/v1/p2p/pub/adv/queryAdvList"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; margin.wiki; +https://margin.wiki)", "Content-Type": "application/json"}


def request(cfg, side, page):
    return {"method": "POST", "url": cfg.get("endpoint") or URL, "headers": HEADERS,
            "json": {"side": int(side), "pageNo": page, "pageSize": PAGE_ROWS, "coinCode": cfg.get("pair", "USDT"),
                     "fiatCode": cfg["ccy"], "languageType": 0}}


def parse(payload, side):
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or str(payload.get("code")) != "00000" or not isinstance(data.get("dataList"), list):
        raise ValueError("not a Bitget ad list")
    out = []
    for a in data["dataList"]:
        if num((a or {}).get("price")) == "":
            continue
        out.append({"price": num(a.get("price")), "available": num(a.get("amount")),
                    "min_order": num(a.get("minAmount")), "max_order": num(a.get("maxAmount")),
                    "seller": a.get("encryptUserId") or "", "completion_rate": num(a.get("thirtyCompletionRate")),
                    "order_count": num(a.get("thirtyTunoverNum")), "merchant": bool(a.get("certifiedMerchant"))})
    return out
