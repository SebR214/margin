"""Is this board row believable? (SEB-302.) One check, shared by the collectors.

A person-to-person board row has a buy price (what it costs to get a dollar)
and a sell price (what a dollar fetches), both in local money per dollar, and
the official rate for the same moment. Two things make a row not believable:

  crossed        the buy price is below the sell price. On a real market you
                 cannot buy a dollar for less than you can sell it for, so the
                 two sides are not the same market (or one side is mislabelled).
  out of band    a price is not within BAND_LOW to BAND_HIGH times the official
                 rate: an upside-down price, or the wrong currency. The band is
                 wide on purpose: the highest honest ratio on record is 20.3 (the
                 Sudanese pound on 7 Oct), the lowest 0.88 (the Bolivian
                 boliviano on 16 Sep), across 49,000 stored rows.

A row that fails is written by the collector with source_ok=false and the reason
in `error`, and keeps its medians as evidence. It is never priced. The crossed
text is the same sentence tools/emit_countries.py has always given for a
withheld crossed board, so the site's stated reason does not change.

    python3 board_guard.py --self-test
"""
import sys

BAND_LOW = 0.5
BAND_HIGH = 30.0
CROSSED = ("not enough evidence this hour: the buy side is below the sell side, "
           "so the two are not the same market")


def problem(buy, sell, fx):
    """None if the row is believable, else the reason as one line for `error`."""
    if buy is None or sell is None or not fx:
        return None                         # missing sides are the collector's own failure, handled there
    for name, price in (("buy", buy), ("sell", sell)):
        ratio = price / fx
        if not (BAND_LOW <= ratio <= BAND_HIGH):
            return ("guard: %s price %s is %.4g times the official rate %s, outside %g to %g"
                    % (name, price, ratio, fx, BAND_LOW, BAND_HIGH))
    if buy < sell:
        return "%s (buy %s, sell %s)" % (CROSSED, buy, sell)
    return None


def is_guard_error(error):
    """True for a row the guard refused, so callers can tell it from a failed pull."""
    return (error or "").startswith(("guard:", CROSSED))


def self_test():
    assert problem(101.0, 99.0, 100.0) is None                      # a normal board
    assert problem(100.0, 100.0, 100.0) is None                     # a tie is allowed
    assert problem(962.355, 1119.67, 926.18).startswith(CROSSED)    # Angola, 11 Oct, as stored
    assert problem(46.375, 48.6, 44.895).startswith(CROSSED)        # Ukraine
    assert "outside" in problem(1 / 926.18, 1 / 926.18, 926.18)     # upside down
    assert "outside" in problem(926.18 * 40, 926.18 * 39, 926.18)   # wrong market
    assert problem(926.18 * 20.3, 926.18 * 19.7, 926.18) is None    # Sudan at its honest peak
    assert problem(0.88 * 100, 0.8 * 100, 100.0) is None            # Bolivia at its honest low
    assert is_guard_error(problem(1.0, 2.0, 1.0)) and not is_guard_error("ValueError:no ads")
    assert problem(None, 1.0, 1.0) is None and problem(1.0, 1.0, None) is None
    print("board_guard self-test: ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        print(__doc__)
