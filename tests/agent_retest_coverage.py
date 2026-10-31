import sys
from pathlib import Path
from datetime import date

# Add tools directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import retest_coverage


def test_retest_coverage():
    # Inline fixtures
    findings_obj = {"findings": [{"id": "alpha"}, {"id": "beta"}]}
    rows = [
        {"ts_utc": "2026-01-01T00:00:00+00:00", "finding_id": "alpha"}, 
        {"ts_utc": "2026-01-05T00:00:00+00:00", "finding_id": "alpha"}
    ]
    today = date(2026, 1, 10)
    
    # Call function
    out = retest_coverage.build_coverage(findings_obj, rows, today)
    
    # Assertions
    assert len(out["findings"]) == 2
    
    # Find alpha entry
    alpha_entry = next(f for f in out["findings"] if f["id"] == "alpha")
    assert alpha_entry["rows"] == 2
    assert alpha_entry["last_retest_date"] == "2026-01-05"
    assert alpha_entry["days_since"] == 5
    
    assert "beta" in out["zero_rows"]
    assert "alpha" not in out["zero_rows"]
    
    # Find beta entry
    beta_entry = next(f for f in out["findings"] if f["id"] == "beta")
    assert beta_entry["rows"] == 0
    assert beta_entry["last_retest_date"] is None


if __name__ == "__main__":
    test_retest_coverage()
    print("ok")
