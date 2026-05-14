"""Offline country reference data via pycountry.

Wraps pycountry to provide helpers used by the LOCATION field type
validator and JSON Schema extractor. No network calls — all data is
bundled with the pycountry package.

If pycountry is not installed, functions degrade gracefully:
- `is_valid_iso_country_code` returns True (validation skipped).
- `get_country_info` returns None.
- `list_country_options` returns an empty list.
"""

from __future__ import annotations

import logging

from .options import FieldOption

logger = logging.getLogger(__name__)

try:
    import pycountry

    _HAS_PYCOUNTRY = True
except ImportError:
    _HAS_PYCOUNTRY = False

# ISO 3166-1 alpha-2 dial code lookup (subset — most common countries).
# pycountry does not include dial codes, so we maintain a small lookup.
_DIAL_CODES: dict[str, str] = {
    "US": "+1",
    "CA": "+1",
    "GB": "+44",
    "ES": "+34",
    "FR": "+33",
    "DE": "+49",
    "MX": "+52",
    "VE": "+58",
    "CO": "+57",
    "AR": "+54",
    "BR": "+55",
    "CL": "+56",
    "PE": "+51",
    "EC": "+593",
    "UY": "+598",
    "PY": "+595",
    "BO": "+591",
    "GT": "+502",
    "HN": "+504",
    "SV": "+503",
    "NI": "+505",
    "CR": "+506",
    "PA": "+507",
    "DO": "+1-809",
    "CU": "+53",
    "PR": "+1-787",
    "IT": "+39",
    "PT": "+351",
    "NL": "+31",
    "BE": "+32",
    "CH": "+41",
    "AT": "+43",
    "PL": "+48",
    "SE": "+46",
    "NO": "+47",
    "DK": "+45",
    "FI": "+358",
    "AU": "+61",
    "NZ": "+64",
    "JP": "+81",
    "KR": "+82",
    "CN": "+86",
    "IN": "+91",
    "ZA": "+27",
    "NG": "+234",
    "EG": "+20",
    "RU": "+7",
    "TR": "+90",
    "SA": "+966",
    "AE": "+971",
}


def is_valid_iso_country_code(code: str) -> bool:
    """Return True if code is a valid ISO 3166-1 alpha-2 country code.

    Args:
        code: Two-letter country code (case-insensitive).

    Returns:
        True if valid, False otherwise. Returns True if pycountry is not installed.
    """
    if not _HAS_PYCOUNTRY:
        logger.warning("pycountry not installed — LOCATION validation skipped")
        return True
    return pycountry.countries.get(alpha_2=code.upper()) is not None


def get_country_info(code: str) -> dict | None:
    """Return name, flag emoji, and dial code for a country code.

    Args:
        code: ISO 3166-1 alpha-2 country code.

    Returns:
        Dict with keys 'name', 'flag', 'dial_code', or None if not found
        or if pycountry is not installed.
    """
    if not _HAS_PYCOUNTRY:
        return None
    country = pycountry.countries.get(alpha_2=code.upper())
    if country is None:
        return None
    # Build flag emoji from regional indicator symbols (U+1F1E6..U+1F1FF)
    flag = "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper())
    return {
        "name": country.name,
        "flag": flag,
        "dial_code": _DIAL_CODES.get(code.upper(), ""),
    }


def list_country_options() -> list[FieldOption]:
    """Return all countries as a FieldOption list sorted by name.

    Returns:
        List of FieldOption with value=alpha_2, label=name, icon=flag emoji.
        Returns an empty list if pycountry is not installed.
    """
    if not _HAS_PYCOUNTRY:
        return []
    options: list[FieldOption] = []
    for country in sorted(pycountry.countries, key=lambda c: c.name):
        flag = "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in country.alpha_2)
        options.append(
            FieldOption(
                value=country.alpha_2,
                label=country.name,
                icon=flag,
            )
        )
    return options
