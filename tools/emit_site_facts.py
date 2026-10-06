#!/usr/bin/env python3
"""data/site_facts.json: facts about how the site is run, read from the repo's own config.

  agents       how many AI agents have a role file in agents/ (BUILDER.md, REVIEWER.md, WRITER.md);
               the other files there are rules, a spec template and briefs, not agents.
  agent_roles  their names.
Stdlib only, no wall clock. Usage: python3 tools/emit_site_facts.py
"""
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROLE_FILES = ("BUILDER.md", "REVIEWER.md", "WRITER.md")


def build():
    present = [f for f in ROLE_FILES if os.path.exists(os.path.join(HERE, "agents", f))]
    return {"agents": len(present), "agent_roles": [f[:-3].lower() for f in present],
            "source": "agents/ role files"}


def main():
    doc = build()
    with open(os.path.join(HERE, "data", "site_facts.json"), "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    print("site_facts:", doc)


if __name__ == "__main__":
    main()
