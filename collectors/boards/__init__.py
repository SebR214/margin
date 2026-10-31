"""One parser per person-to-person board (SEB-422). A parser module has:

    NAME        the board's key in a config block ("bitget")
    REGISTRY    the board's name in data/source_registry.json
    PAGE_ROWS   ads per page, or None when one request returns the whole book
    request(cfg, side, page) -> kwargs for requests.request (method, url, params or json, headers)
    parse(payload, side)     -> [ad, ...], in the order the board lists them (best price first)

An ad is a dict: price (local money per dollar), available (dollars on offer or ""), min_order and max_order (local money or ""),
seller (the board's own id; the template hashes it and never stores it), completion_rate, order_count, merchant (bool).
`side` is the board's own word for the side, taken from the config's "sides" map. parse raises ValueError on an answer that is not
an ad list. Nothing is guessed: a missing figure is "".
"""
import importlib

BLOCKED = {
    "bybit": "api2.bybit.com does not answer from GitHub Actions or from a home connection (probe of 3 to 25 Oct 2026, data/p2p_board_probes.csv); no payload to write a parser against",
    "noones": "no public ad list found without a key: noones.com/api/v1/offer/all answers 404; its API needs an account",
}
BOARDS = ("binance", "okx", "bybit", "kucoin", "bitget", "htx", "noones")


def num(x):
    """A positive number, or ""."""
    try:
        v = float(x)
        return v if v > 0 else ""
    except (TypeError, ValueError):
        return ""


def get(name):
    if name in BLOCKED:
        raise SystemExit("board %s is blocked: %s" % (name, BLOCKED[name]))
    if name not in BOARDS:
        raise SystemExit("unknown board %r (known: %s)" % (name, ", ".join(BOARDS)))
    return importlib.import_module("collectors.boards." + name)
