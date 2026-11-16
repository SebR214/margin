"""SEB-463: the source gate reads the shared venue files, the Bitget and HTX boards and the cash day files. Fixture rows only."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import source_gate as g  # noqa: E402

VENUE = "ts_utc,venue,ccy,kind,n_board,n_ads,ask_best,ask_ref,bid_best,bid_ref,source_ok,error\n"
BOARD = "ts_utc,board,ccy,buy_median,sell_median,n_ads,source_ok,error\n"
CASH = "ts_utc,tracker,ccy,buy,sell,mid,updated_by_source,source_ok,error\n"


def w(d, name, text):
    os.makedirs(os.path.dirname(os.path.join(d, name)), exist_ok=True)
    with open(os.path.join(d, name), "w") as f:
        f.write(text)


with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as raw:
    w(data, "zar_luno.csv", VENUE
      + "2026-11-01T10:05:00Z,Luno ZAR,ZAR,book,1,1,17.5,17.5,17.4,17.4,True,\n"
      + "2026-11-01T11:05:00Z,Luno ZAR,ZAR,book,0,0,,,,,False,empty book\n")
    w(data, "p2p_kucoin.csv", VENUE + "2026-11-01T10:05:00Z,KuCoin P2P,GHS,board,3,3,15.2,15.2,,,True,\n")
    w(data, "p2p_basis_boards.csv", BOARD
      + "2026-11-01T10:05:00Z,bitget,NGN,1500.0,1490.0,5,True,\n"
      + "2026-11-01T10:05:00Z,htx,VND,26000.0,25800.0,9,True,\n"
      + "2026-11-01T11:05:00Z,htx,VND,,,0,False,429\n"
      + "2026-11-01T10:05:00Z,other,VND,1.0,1.0,1,True,\n")
    w(data, "cash_rates/2026-11-01.csv", CASH
      + "2026-11-01T10:05:00Z,dolarapi_ve_paralelo,VES,40.0,41.0,40.5,,True,\n"
      + "2026-11-01T11:05:00Z,dolarapi_ve_paralelo,VES,,,,,False,down\n")
    w(raw, "cash_rates/2026-11-02.csv", CASH + "2026-11-02T10:05:00Z,dolarapi_ve_paralelo,VES,41.0,,42.0,,True,\n")
    p = g.venue_prices(data=data, raw=raw)
    assert p["Luno ZAR"]["ZAR"] == {"2026-11-01T10": 17.5}, dict(p["Luno ZAR"])  # failed row is a gap, not a price
    assert p["KuCoin P2P"]["GHS"] == {"2026-11-01T10": 15.2}
    assert p["Bitget P2P"]["NGN"] == {"2026-11-01T10": 1500.0}
    assert p["HTX P2P"]["VND"] == {"2026-11-01T10": 26000.0}
    assert "other" not in p and "Other P2P" not in p
    cash = p["Cash: dolarapi_ve_paralelo"]["VES"]
    assert cash == {"2026-11-01T10": 41.0, "2026-11-02T10": 42.0}, cash  # sell, else mid; day files from both dirs
    # a missing file is an empty source, not a crash and not a made-up price
    assert dict(g.venue_prices(data=raw)).keys() == {"Cash: dolarapi_ve_paralelo"}
print("agent_source_gate_venues: ok")
