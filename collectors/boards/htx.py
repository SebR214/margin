"""HTX P2P: GET www.htx.com/-/x/otc/v1/data/trade-market, no key. The currency is HTX's own integer id, which the config carries as
extra.currency_id and which comes from HTX's own list (www.htx.com/-/x/otc/v1/data/config-list?type=currency, nameShort is the ISO code):
5 is VND, 15 NGN. Side words: `sell` is the list of ads that sell dollars (the reader buys), `buy` the list of ads that buy them.
The page size is fixed at 10 by the board."""
from collectors.boards import num

NAME = "htx"
REGISTRY = "HTX P2P"
PAGE_ROWS = 10
URL = "https://www.htx.com/-/x/otc/v1/data/trade-market"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; margin.wiki; +https://margin.wiki)"}


def request(cfg, side, page):
    ex = cfg.get("extra") or {}
    return {"method": "GET", "url": cfg.get("endpoint") or URL, "headers": HEADERS,
            "params": {"coinId": ex.get("coin_id", 2), "currency": ex["currency_id"], "tradeType": side, "currPage": page,
                       "payMethod": 0, "acceptOrder": 0, "country": "", "blockType": "general", "online": 1, "range": 0, "amount": "",
                       "isThumbsUp": "false", "isMerchant": "false", "isTraded": "false", "onlyTradable": "false", "isFollowed": "false"}}


def parse(payload, side):
    if not isinstance(payload, dict) or payload.get("code") != 200 or not isinstance(payload.get("data"), list):
        raise ValueError("not an HTX ad list")
    out = []
    for a in payload["data"]:
        if num((a or {}).get("price")) == "":
            continue
        out.append({"price": num(a.get("price")), "available": num(a.get("tradeCount")),
                    "min_order": num(a.get("minTradeLimit")), "max_order": num(a.get("maxTradeLimit")),
                    "seller": a.get("uid") or "", "completion_rate": num(a.get("orderCompleteRate")),
                    "order_count": num(a.get("tradeMonthTimes")), "merchant": (a.get("merchantLevel") or 0) > 0})
    return out
