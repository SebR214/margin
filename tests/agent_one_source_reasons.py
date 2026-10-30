import sys
import os

# Add repo root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tools.one_source_reasons import build


def test_aed():
    """Test AED with registry statuses."""
    gap_report = {
        "computed_at": "x",
        "one_source": [{
            "ccy": "AED",
            "sources_seen": ["BitOasis", "OKX spot (AED)", "binance_p2p"],
            "sources_behind_price": ["binance_p2p"]
        }]
    }
    
    source_registry = {
        "sources": {
            "BitOasis": {"status": "quarantine", "basis": "test basis"},
            "OKX spot (AED)": {"status": "quarantine", "basis": "test basis"},
            "binance_p2p": {"status": "approved", "basis": "test"}
        }
    }
    
    result = build(gap_report, {}, {}, source_registry)
    
    # Check that we have the right sources in not_behind
    not_behind = result["currencies"][0]["not_behind"]
    names = [item["source"] for item in not_behind]
    
    assert names == ["BitOasis", "OKX spot (AED)"]
    assert "binance_p2p" not in names
    
    # Check that each reason contains "quarantine"
    for item in not_behind:
        assert isinstance(item["reason"], str)
        assert len(item["reason"]) > 0
        assert "quarantine" in item["reason"]


def test_no_stored_fields():
    """Test with all inputs empty."""
    gap_report = {
        "computed_at": "x",
        "one_source": [{
            "ccy": "AED",
            "sources_seen": ["BitOasis", "OKX spot (AED)", "binance_p2p"],
            "sources_behind_price": ["binance_p2p"]
        }]
    }
    
    result = build(gap_report, {}, {}, {})
    
    # Check that every reason is "no stored reason"
    not_behind = result["currencies"][0]["not_behind"]
    for item in not_behind:
        assert item["reason"] == "no stored reason"


def test_one_entry_per_currency():
    """Test that we get exactly one entry per currency."""
    gap_report = {
        "computed_at": "x",
        "one_source": [
            {
                "ccy": "AED",
                "sources_seen": ["BitOasis", "OKX spot (AED)", "binance_p2p"],
                "sources_behind_price": ["binance_p2p"]
            },
            {
                "ccy": "DZD", 
                "sources_seen": ["binance_p2p"],
                "sources_behind_price": ["binance_p2p"]
            },
            {
                "ccy": "SDG",
                "sources_seen": ["source1", "source2"],
                "sources_behind_price": []
            }
        ]
    }
    
    result = build(gap_report, {}, {}, {})
    
    # Check we have exactly 3 currencies
    assert len(result["currencies"]) == 3
    
    # Check the ccys are in order
    assert result["currencies"][0]["ccy"] == "AED"
    assert result["currencies"][1]["ccy"] == "DZD" 
    assert result["currencies"][2]["ccy"] == "SDG"
    
    # Check DZD has empty not_behind (all sources behind price)
    assert result["currencies"][1]["not_behind"] == []


def test_flagged_pair():
    """Test flagged pair reason."""
    gap_report = {
        "computed_at": "x",
        "one_source": [{
            "ccy": "TEST",
            "sources_seen": ["source1", "source2"],
            "sources_behind_price": ["source2"]
        }]
    }
    
    source_pairs = {
        "markets": {
            "TEST": {
                "pairs": [{
                    "a": "source1",
                    "b": "source2", 
                    "flag": True,
                    "median_gap_pct": 5.5,
                    "hours": 100,
                    "share_over_gap": 0.8
                }]
            }
        }
    }
    
    result = build(gap_report, {}, source_pairs, {})
    
    # Check that the reason starts with "pair with"
    not_behind = result["currencies"][0]["not_behind"]
    reason = not_behind[0]["reason"]
    assert reason.startswith("pair with")


if __name__ == "__main__":
    test_aed()
    test_no_stored_fields()
    test_one_entry_per_currency()
    test_flagged_pair()
    print("All tests passed!")
