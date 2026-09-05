"""
DMS to Decimal Degree Converter

Owner: M-B (Data Extractors & Storage) — DMS coordinate helper
Module: scripts/dms_to_decimal.py

Converts coordinates from DMS (Degrees Minutes Seconds) format
to decimal degrees. Used by INCOIS TextData parser and Copernicus fallback.

INCOIS TextData format examples:
  "9°55'52\"N" -> 9.931111
  "9 55 52 N"   -> 9.931111
  "76°16'02\"E" -> 76.267222
  "72 18 55 E"  -> 72.315278
  "9d 55m 52s N" -> 9.931111
  "9.9311 N"    -> 9.931100

Usage:
  python scripts/dms_to_decimal.py "9°55'52\"N"
"""

import re
import sys
from typing import Optional


def dms_to_decimal(dms_string: str) -> Optional[float]:
    """
    Convert DMS string to decimal degrees.

    Supports multiple DMS variations:
    e.g. 9°55'52"N, 9 55 52 N, 76°16'02"E, 72 18 55 E, 9d 55m 52s N, 9.9311 N.
    Correctly negates S / W coordinates.
    Returns float rounded to 5-6 decimals, or None on invalid input.
    """
    if not dms_string or not isinstance(dms_string, str):
        return None

    s = dms_string.strip()
    if not s:
        return None

    # Determine direction (N, S, E, W) and sign
    is_negative = False
    direction = None

    # Check for leading direction (e.g., "N 9 55 52", "S 9°55'")
    m_lead = re.match(r'^([NSEWnsew])\s*(.*)$', s)
    if m_lead and re.search(r'\d', m_lead.group(2)):
        direction = m_lead.group(1).upper()
        s = m_lead.group(2).strip()
    else:
        # Check for trailing direction (e.g. "9°55'52\"N", "9 55 52 N", "9.9311 N", "9d 55m 52s N")
        m_trail = re.search(r'(?i)(?:\b|(?<=[\d°\'"″′dms]))([NSEW])\s*$', s)
        if m_trail:
            char = m_trail.group(1)
            # If the char is 'S'/'s', and matches \d+s$ and string has \d+d and \d+m:
            if char.upper() == 'S' and re.search(r'(?i)\d+d\b.*\d+m\b.*\d+s$', s):
                # 's' is seconds, not hemisphere
                pass
            else:
                direction = char.upper()
                s = s[:m_trail.start(1)].strip()

    if direction in ('S', 'W'):
        is_negative = True

    # Check leading sign if any
    if s.startswith('-'):
        is_negative = not is_negative
        s = s[1:].strip()
    elif s.startswith('+'):
        s = s[1:].strip()

    # Replace written units with spaces
    cleaned = re.sub(r'(?i)\b(degrees?|deg|minutes?|min|seconds?|sec)\b', ' ', s)
    # Replace symbols (°dD'"″′msMS,;) with space
    cleaned = re.sub(r'[°dD\'"″′msMS,;]', ' ', cleaned)

    # Check for any invalid characters left (only digits, dots, whitespace allowed)
    invalid_chars = re.sub(r'[\d\.\s]', '', cleaned)
    if invalid_chars:
        return None

    parts = re.findall(r'\d+(?:\.\d+)?', cleaned)
    if not parts or len(parts) > 3:
        return None

    try:
        if len(parts) == 1:
            val = float(parts[0])
        elif len(parts) == 2:
            deg = float(parts[0])
            minutes = float(parts[1])
            if minutes < 0 or minutes >= 60:
                return None
            val = deg + minutes / 60.0
        elif len(parts) == 3:
            deg = float(parts[0])
            minutes = float(parts[1])
            seconds = float(parts[2])
            if minutes < 0 or minutes >= 60 or seconds < 0 or seconds >= 60:
                return None
            val = deg + minutes / 60.0 + seconds / 3600.0
        else:
            return None

        # Check bounds: coordinates cannot exceed 180 degrees
        if val < 0 or val > 180.0:
            return None

        result = -val if is_negative else val
        return round(result, 6)
    except (ValueError, TypeError):
        return None


def decimal_to_dms(deg: float, is_lat: bool = True) -> str:
    """Convert decimal degrees to a standard DMS string (e.g., '9 55 52 N')."""
    hemisphere = ("N" if deg >= 0 else "S") if is_lat else ("E" if deg >= 0 else "W")
    abs_deg = abs(deg)
    d = int(abs_deg)
    m_float = (abs_deg - d) * 60.0
    m = int(m_float)
    s = int(round((m_float - m) * 60.0))
    if s >= 60:
        s -= 60
        m += 1
    if m >= 60:
        m -= 60
        d += 1
    return f"{d} {m} {s} {hemisphere}"


def main():
    """CLI entry point for DMS conversion."""
    if len(sys.argv) < 2:
        print("Usage: python dms_to_decimal.py <DMS_STRING>")
        sys.exit(1)

    dms_input = sys.argv[1]
    result = dms_to_decimal(dms_input)
    if result is not None:
        print(f"{result:.6f}")
    else:
        print(f"ERROR: Could not parse '{dms_input}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
