import csv
import json
from datetime import datetime, date
from pathlib import Path


FINDINGS = Path(__file__).resolve().parent.parent / "data" / "findings.json"
TESTS = Path(__file__).resolve().parent.parent / "data" / "finding_tests.csv"
OUT = Path(__file__).resolve().parent.parent / "data" / "retest_coverage.json"


def build_coverage(findings_obj, test_rows, today):
    # Get all finding IDs in order
    finding_ids = [finding["id"] for finding in findings_obj["findings"]]
    
    result_findings = []
    zero_rows = []
    
    for finding_id in finding_ids:
        # Select rows for this finding ID
        rows = [row for row in test_rows if row["finding_id"] == finding_id]
        
        row_count = len(rows)
        
        # Find the latest date
        dates = []
        for row in rows:
            try:
                date_obj = date.fromisoformat(row["ts_utc"][:10])
                dates.append(date_obj)
            except (ValueError, KeyError):
                # Skip rows with invalid dates for date calculation but still count them
                pass
        
        if dates and row_count > 0:
            last_date = max(dates)
            last_retest_date = last_date.isoformat()
            days_since = (today - last_date).days
        else:
            last_retest_date = None
            days_since = None
            
        result_findings.append({
            "id": finding_id,
            "rows": row_count,
            "last_retest_date": last_retest_date,
            "days_since": days_since
        })
        
        if row_count == 0:
            zero_rows.append(finding_id)
    
    return {
        "findings": result_findings,
        "zero_rows": zero_rows
    }


def main():
    # Load findings.json
    with open(FINDINGS, 'r') as f:
        findings_obj = json.load(f)
    
    # Load finding_tests.csv
    with open(TESTS, 'r') as f:
        test_rows = list(csv.DictReader(f))
    
    # Get current time
    now = datetime.now().utcnow()
    
    # Build coverage
    result = build_coverage(findings_obj, test_rows, now.date())
    
    # Add timestamp
    result["as_of_utc"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Write to output file
    with open(OUT, 'w') as f:
        json.dump(result, f, indent=2)
        f.write('\n')


if __name__ == "__main__":
    main()
