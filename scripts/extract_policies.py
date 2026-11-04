"""Regenerate data/processed/policies.md from the policy manual PDF.

Usage:  python scripts/extract_policies.py
"""

from emporio_agent.policies import write_policies_markdown

if __name__ == "__main__":
    path = write_policies_markdown()
    print(f"Wrote {path}")
