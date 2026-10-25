#!/usr/bin/env python3

import argparse
import csv
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPARISON = os.path.join(ROOT, "data", "comparison_quotes.csv")
STORED = os.path.join(ROOT, "data", "provider_quotes.csv")
OUT = os.path.join(ROOT, "data", "unstored_providers.json")
CORRIDOR_COLS = ("corridor", "route")
PROVIDER_COLS = ("provider", "provider_name")


def norm(name):
    """Normalize a name for matching purposes."""
    return " ".join(name.split()).casefold()


def read_providers(path):
    """Read providers from a CSV file, returning {corridor: {norm_name: original_name}}."""
    if not os.path.exists(path):
        return {}
    
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        
        # Find corridor column
        corridor_col = None
        for col in CORRIDOR_COLS:
            if col in header:
                corridor_col = col
                break
        
        # Find provider column
        provider_col = None
        for col in PROVIDER_COLS:
            if col in header:
                provider_col = col
                break
        
        if not corridor_col or not provider_col:
            raise ValueError(f"{path}: expected columns {CORRIDOR_COLS} and {PROVIDER_COLS}, got {header}")
        
        providers = {}
        for row in reader:
            corridor = (row.get(corridor_col) or "").strip()
            provider = (row.get(provider_col) or "").strip()
            
            if not corridor or not provider:
                continue
            
            if corridor not in providers:
                providers[corridor] = {}
            
            norm_provider = norm(provider)
            if norm_provider not in providers[corridor]:
                providers[corridor][norm_provider] = provider
        
        return providers


def build(comparison, stored):
    """Build routes dict with stored and unstored providers for each corridor."""
    routes = {}
    
    for corridor in comparison:
        # Get stored providers for this corridor (empty list if not present)
        stored_providers_dict = stored.get(corridor, {})
        stored_names = sorted(stored_providers_dict.values())
        
        # Get comparison providers for this corridor
        comparison_providers_dict = comparison.get(corridor, {})
        
        # Find unstored providers (those in comparison but not in stored)
        unstored_names = []
        stored_norm_names = set(stored_providers_dict.keys())
        for norm_name, original_name in comparison_providers_dict.items():
            if norm_name not in stored_norm_names:
                unstored_names.append(original_name)
        
        # Sort unstored names
        unstored_names.sort()
        
        routes[corridor] = {
            "stored": stored_names,
            "unstored": unstored_names
        }
    
    return routes


def check_disjoint(routes):
    """Check that no provider appears in both stored and unstored for any route."""
    for route, providers in routes.items():
        stored_norm = {norm(name) for name in providers["stored"]}
        unstored_norm = {norm(name) for name in providers["unstored"]}
        
        overlap = stored_norm & unstored_norm
        if overlap:
            raise AssertionError(f"Route {route} has provider {next(name for name in providers['stored'] if norm(name) in overlap)} in both stored and unstored")


def selftest():
    """Run offline selftests with synthetic data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test comparison file
        comp_path = os.path.join(tmpdir, "comparison.csv")
        with open(comp_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["ts_utc", "corridor", "size_src", "provider"])
            writer.writerow(["2023-01-01T00:00:00Z", "XXX->YYY", "1000", "AlphaPay"])
            writer.writerow(["2023-01-01T00:00:00Z", "XXX->YYY", "1000", "BetaSend"])
            writer.writerow(["2023-01-01T00:00:00Z", "XXX->YYY", "1000", "GammaFX"])
            writer.writerow(["2023-01-01T00:00:00Z", "ZZZ->WWW", "1000", "DeltaTransfer"])
        
        # Create test stored file
        stored_path = os.path.join(tmpdir, "stored.csv")
        with open(stored_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["ts_utc", "corridor", "size_src", "provider"])
            writer.writerow(["2023-01-01T00:00:00Z", "XXX->YYY", "1000", "alphapay "])  # Different case and whitespace
            writer.writerow(["2023-01-01T00:00:00Z", "XXX->YYY", "1000", "BetaSend"])
            writer.writerow(["2023-01-01T00:00:00Z", "ZZZ->WWW", "1000", "EpsilonCash"])  # In stored but not comparison
        
        # Test reading providers
        comparison = read_providers(comp_path)
        stored = read_providers(stored_path)
        
        # Test building routes
        routes = build(comparison, stored)
        
        # Check results
        assert routes["XXX->YYY"]["unstored"] == ["GammaFX"], f"Expected ['GammaFX'], got {routes['XXX->YYY']['unstored']}"
        assert "ZZZ->WWW" in routes, "Should include corridors from comparison even if no stored providers"
        assert routes["ZZZ->WWW"]["unstored"] == ["DeltaTransfer"], "Should include all comparison providers when none stored"
        
        # Check disjoint check passes
        check_disjoint(routes)
        
        # Check disjoint check catches errors
        bad_routes = {
            "XXX->YYY": {
                "stored": ["AlphaPay"],
                "unstored": ["alphapay"]  # Same name, different case
            }
        }
        try:
            check_disjoint(bad_routes)
            assert False, "Should have raised AssertionError"
        except AssertionError:
            pass  # Expected
        
        # Check missing provider column
        bad_csv = os.path.join(tmpdir, "bad.csv")
        with open(bad_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["ts_utc", "corridor", "size_src"])  # Missing provider column
            writer.writerow(["2023-01-01T00:00:00Z", "XXX->YYY", "1000"])
        
        try:
            read_providers(bad_csv)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass  # Expected
    
    print("ALL SELFTESTS PASSED")


def main():
    ap = argparse.ArgumentParser(description="List unstored providers from comparison feed")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    
    if args.selftest:
        selftest()
        return
    
    # Exit with clear message if comparison file doesn't exist
    if not os.path.exists(COMPARISON):
        print(f"Comparison file not found: {COMPARISON}", file=sys.stderr)
        sys.exit(1)
    
    # Read providers from both files
    comparison = read_providers(COMPARISON)
    stored = read_providers(STORED)
    
    # Build routes dictionary
    routes = build(comparison, stored)
    
    # Check for overlaps
    check_disjoint(routes)
    
    # Write output file
    with open(OUT, "w") as f:
        json.dump({"routes": routes}, f, indent=2, sort_keys=True)
        f.write("\n")
    
    # Print summary
    for corridor in sorted(routes.keys()):
        unstored_count = len(routes[corridor]["unstored"])
        print(f"{corridor}: {unstored_count} unstored")


if __name__ == "__main__":
    main()
