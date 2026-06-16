"""Check the product and intent registries for drift.

Usage:
    python -m agent_benchmarks.config_check

Exits non-zero if ``config/products.yaml`` and ``products.yaml`` disagree on
the GitHub repo of any shared product, or if ``intents.yaml`` references a
product key that is not registered in ``products.yaml``, or if a product's
coverage declaration is broken (``coverage_status: covered`` with no
resolvable task/question set, or a declared questions file that is absent).
Intended for CI.
"""

from __future__ import annotations

import sys

from agent_benchmarks.config import detect_registry_drift
from agent_benchmarks.coverage import coverage_issues
from agent_benchmarks.intents import IntentRegistry


def main() -> int:
    issues = detect_registry_drift()
    issues += IntentRegistry().validate()
    issues += coverage_issues()
    if issues:
        print("✗ registry drift detected:", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1
    print("✓ product and intent registries are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
