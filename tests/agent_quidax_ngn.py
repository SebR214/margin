import os
import sys
import tempfile

# Add parent directory to path to import collector_quidax_ngn
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import collector_quidax_ngn as q


def test_row_has_bid_and_ask():
    """Test parsing a valid ticker response."""
    payload = {"status": "success", "data": {"ticker": {"buy": "1500", "sell": "1510", "last": "1505"}}}
    row = q.parse_ticker(payload, "test-ts")
    
    assert row is not None
    assert row["bid"] == 1500.0
    assert row["ask"] == 1510.0
    
    # Test writing to file
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = os.path.join(tmpdir, "test.csv")
        result = q.collect(payload, path=tmppath, ts="test-ts")
        assert result is True
        
        # Read back and verify
        with open(tmppath, "r") as f:
            lines = f.read().strip().split("\n")
        
        assert lines[0] == ",".join(q.FIELDS)
        assert len(lines) == 2  # header + 1 data row


def test_missing_sell_writes_nothing():
    """Test that a ticker without sell key writes nothing."""
    payload = {"status": "success", "data": {"ticker": {"buy": "1500", "last": "1505"}}}
    
    assert q.parse_ticker(payload, "test-ts") is None
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = os.path.join(tmpdir, "test.csv")
        result = q.collect(payload, path=tmppath, ts="test-ts")
        assert result is False
        
        # Verify no file was created or file is empty
        assert not os.path.exists(tmppath) or os.path.getsize(tmppath) == 0


def test_selftest():
    """Run the module's selftest."""
    q.selftest()


if __name__ == "__main__":
    test_row_has_bid_and_ask()
    test_missing_sell_writes_nothing()
    test_selftest()
    print("agent_quidax_ngn OK")
