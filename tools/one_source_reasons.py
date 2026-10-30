import json
import os

ROOT = os.path.dirname(os.path.dirname(__file__))
GAP_REPORT_PATH = os.path.join(ROOT, "data", "gap_report.json")
INDEX_LATEST_PATH = os.path.join(ROOT, "data", "index_latest.json")
SOURCE_PAIRS_PATH = os.path.join(ROOT, "data", "source_pairs.json")
SOURCE_REGISTRY_PATH = os.path.join(ROOT, "data", "source_registry.json")
OUTPUT_PATH = os.path.join(ROOT, "data", "one_source_reasons.json")


def load_json(path):
    """Load JSON from file, returning {} if file is missing, empty or invalid."""
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def reason_for(source, ccy, behind, index_latest, source_pairs, source_registry):
    """Return a reason string for why a source is not behind the price."""
    
    # 1. Registry status
    registry_entry = source_registry.get("sources", {}).get(source)
    if registry_entry and registry_entry.get("status") != "approved":
        status = registry_entry["status"]
        basis = registry_entry["basis"]
        return f"registry status {status}: {basis}"
    
    # 2. Flagged pair
    pairs = source_pairs.get("markets", {}).get(ccy, {}).get("pairs", [])
    for pair in pairs:
        if (pair.get("a") == source or pair.get("b") == source) and pair.get("flag"):
            other_source = pair.get("b") if pair.get("a") == source else pair.get("a")
            median_gap = str(pair.get("median_gap_pct"))
            hours = str(pair.get("hours"))
            share_over_gap = str(pair.get("share_over_gap"))
            return f"pair with {other_source} is flagged: median gap {median_gap} pct over {hours} hours, share over gap {share_over_gap}"
    
    # 3. Different kind
    for pair in pairs:
        if pair.get("a") == source and pair.get("b") in behind and not pair.get("same_kind"):
            return f"different kind from the priced source {pair['b']}: pair kind is {pair['kind']}"
        if pair.get("b") == source and pair.get("a") in behind and not pair.get("same_kind"):
            return f"different kind from the priced source {pair['a']}: pair kind is {pair['kind']}"
    
    # 4. Withheld
    withheld_entries = index_latest.get("withheld", [])
    for entry in withheld_entries:
        if entry.get("ccy") == ccy and "reason_raw" in entry:
            return entry["reason_raw"]
    
    # 5. Fallback
    return "no stored reason"


def build(gap_report, index_latest, source_pairs, source_registry):
    """Build the one source reasons structure."""
    result = {
        "computed_at": gap_report.get("computed_at"),
        "source_files": [
            "data/gap_report.json",
            "data/index_latest.json", 
            "data/source_pairs.json",
            "data/source_registry.json"
        ],
        "currencies": []
    }
    
    one_source_items = gap_report.get("one_source", [])
    
    for item in one_source_items:
        ccy = item["ccy"]
        sources_seen = item.get("sources_seen", [])
        sources_behind_price = item.get("sources_behind_price", [])
        
        # Create not_behind list with reasons
        not_behind = []
        for source in sources_seen:
            if source not in sources_behind_price:
                reason = reason_for(
                    source, ccy, sources_behind_price, 
                    index_latest, source_pairs, source_registry
                )
                not_behind.append({
                    "source": source,
                    "reason": reason
                })
        
        result["currencies"].append({
            "ccy": ccy,
            "sources_behind_price": sources_behind_price,
            "not_behind": not_behind
        })
    
    return result


def main():
    """Main function to generate one source reasons."""
    gap_report = load_json(GAP_REPORT_PATH)
    index_latest = load_json(INDEX_LATEST_PATH)
    source_pairs = load_json(SOURCE_PAIRS_PATH)
    source_registry = load_json(SOURCE_REGISTRY_PATH)
    
    result = build(gap_report, index_latest, source_pairs, source_registry)
    
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(result, f, indent=1, sort_keys=True)
        f.write('\n')


if __name__ == "__main__":
    main()
