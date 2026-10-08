"""Deps consistency check — pyproject range must allow requirements pin.

Owner: M-C (Backend API & Platform)
Usage: python scripts/check_deps.py
Exit 0 when backend/pyproject.toml + backend/requirements.txt agree.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def parse_pyproject_ranges(text: str) -> dict[str, str]:
    """Extract {name: min_version} for >= pins in pyproject dependencies."""
    found: dict[str, str] = {}
    for name, ver in re.findall(r'"([a-zA-Z0-9_-]+)>=([0-9][^"]*)"', text):
        found[name.lower()] = ver.strip()
    return found


def parse_requirements_pins(text: str) -> dict[str, str]:
    """Extract {name: pinned_version} for == pins in requirements.txt."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"([a-zA-Z0-9_.\[\]-]+)==([0-9][^;\s]*)", line)
        if m:
            found[m.group(1).lower().split("[")[0]] = m.group(2).strip()
    return found


def to_tuple(ver: str) -> tuple[int, ...]:
    """'2.0.35' -> (2, 0, 35) for comparison (non-numeric parts ignored)."""
    parts = []
    for p in re.split(r"[.\-+]", ver):
        m = re.match(r"(\d+)", p)
        parts.append(int(m.group(1)) if m else 0)
    return tuple(parts)


def check(ranges: dict[str, str], pins: dict[str, str]) -> list[str]:
    """Return error strings for pins violating pyproject minimums."""
    errors = []
    for name in ("fastapi", "sqlalchemy", "geoalchemy2", "asyncpg"):
        if name in ranges and name in pins:
            if to_tuple(pins[name]) < to_tuple(ranges[name]):
                errors.append(f"{name}: pin {pins[name]} < pyproject >={ranges[name]}")
    # psycopg must not be the only driver when code imports asyncpg
    if "psycopg-binary" in ranges and "asyncpg" not in ranges:
        errors.append("pyproject lists psycopg-binary but code uses asyncpg driver")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    ranges = parse_pyproject_ranges((root / "backend/pyproject.toml").read_text())
    pins = parse_requirements_pins((root / "backend/requirements.txt").read_text())
    errors = check(ranges, pins)
    if errors:
        print("DEPS DRIFT:\n- " + "\n- ".join(errors))
        return 1
    print("deps ok: pyproject ranges allow requirements pins")
    return 0


if __name__ == "__main__":
    sys.exit(main())
