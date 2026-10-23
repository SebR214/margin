#!/usr/bin/env python3
"""
List providers present in the comparison feed but absent from stored quotes.

This script reads the comparison quotes and the stored provider quotes,
then outputs a JSON file listing, for each route, the providers that
appear in the comparison feed but are not stored yet.
"""

import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

COMPARISON_QUOTES = os.path.join(ROOT, "data", "comparison_quotes.csv")
PROVIDER_QUOTES = os.path.join(ROOT, "data", "provider_quotes.csv")
UNSTORED_PROVIDERS = os.path.join(ROOT, "data", "unstored_providers.json")


def read_routes_and_providers(filepath):
    """Read all (route, provider) pairs from a CSV file."""
    route_providers = set()
    if os.path.exists(filepath):
        with open(filepath, newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                route = row.get('route')
                provider = row.get('provider')
                if route and provider:
                    route_providers.add((route, provider))
    return route_providers


def main():
    # Read comparison feed providers
    comparison_route_providers = read_routes_and_providers(COMPARISON_QUOTES)
    
    # Read stored provider quotes
    stored_route_providers = read_routes_and_providers(PROVIDER_QUOTES)
    
    # Find unstored providers per route
    unstored = {}
    for route, provider in comparison_route_providers:
        if (route, provider) not in stored_route_providers:
            if route not in unstored:
                unstored[route] = []
            if provider not in unstored[route]:
                unstored[route].append(provider)
    
    # Sort providers for consistent output
    for route in unstored:
        unstored[route].sort()
    
    # Write to JSON file
    with open(UNSTORED_PROVIDERS, 'w') as f:
        json.dump(unstored, f, indent=2, sort_keys=True)
    
    print(f"Unstored providers written to {UNSTORED_PROVIDERS}")


if __name__ == "__main__":
    main()
