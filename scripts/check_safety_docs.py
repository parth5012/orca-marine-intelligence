"""Safety-docs check — README must point to canonical thresholds.

Owner: M-A (Agents)
Usage: python scripts/check_safety_docs.py
Fails when README restates wave/wind bands instead of referencing
backend/agents/safety_thresholds.py (ADR-0003: wave 2.0/3.5m, wind 22/27kt).
"""

from __future__ import annotations

import sys
from pathlib import Path


def check(readme: str) -> list[str]:
    """Return errors if README hardcodes stale bands without pointer."""
    errors = []
    if "safety_thresholds" not in readme:
        errors.append("README missing pointer to backend/agents/safety_thresholds.py")
    # Stale pre-ADR bands that must not appear as current truth
    stale = ["< 1.5 m", "<1.5m", "< 15 kt", "<15kt", "1.5 m — 2.5 m", "15 kt — 25 kt"]
    for token in stale:
        if token in readme:
            errors.append(f"README contains stale band '{token}' (see ADR-0003)")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    readme = (root / "README.md").read_text()
    errors = check(readme)
    if errors:
        print("SAFETY DOCS DRIFT:\n- " + "\n- ".join(errors))
        return 1
    print("safety docs ok: README points to canonical thresholds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
