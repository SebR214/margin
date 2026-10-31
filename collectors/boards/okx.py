"""OKX P2P: GET www.okx.com/v3/c2c/tradingOrders/books, no key. The whole book comes back whatever the page size. Side words: `sell` is
the book of people selling dollars (the reader buys), `buy` the book of people buying them."""
from collectors.boards import num

NAME = "okx"
REGISTRY = "okx_p2p"
PAGE_ROWS = None
URL = "https://www.okx.com/v3/c2c/tradingOrders/books"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def request(cfg, side, page):
    return {"method": "GET", "url": cfg.get("endpoint") or URL, "headers": HEADERS,
            "params": {"side": side, "paymentMethod": "all", "userType": "all", "baseCurrency": cfg.get("pair", "USDT").lower(),
                       "quoteCurrency": cfg["ccy"].lower(), "currentPage": 1, "numberPerPage": 100}}


def parse(payload, side):
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or str(payload.get("code")) != "0" or side not in data:
        raise ValueError("not an OKX book")
    out = []
    for a in data[side] or []:
        if num(a.get("price")) == "":
            continue
        out.append({"price": num(a.get("price")), "available": num(a.get("availableAmount")),
                    "min_order": num(a.get("quoteMinAmountPerOrder")), "max_order": num(a.get("quoteMaxAmountPerOrder")),
                    "seller": a.get("merchantId") or "", "completion_rate": num(a.get("completedRate")),
                    "order_count": num(a.get("completedOrderQuantity")), "merchant": str(a.get("creatorType") or "common").lower() != "common"})
    return out
