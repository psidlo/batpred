"""Calibration of built-in monetary constants, never of supplied tariff prices."""

import copy
import math


MONETARY_UNITS = frozenset(("p", "p/kWh", "p/kg", "£", "£/kWh"))


def validate_currency_scale(value):
    """Return a positive finite calibration or raise a clear configuration error."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("currency_scale must be a positive finite number (not a boolean)")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("currency_scale must be a positive finite number")
    return float(value)


def currency_config_items(items, scale):
    """Copy canonical definitions and scale only built-in monetary metadata."""
    result = copy.deepcopy(items)
    if scale != 1.0:
        for item in result:
            if item.get("unit") in MONETARY_UNITS:
                for field in ("min", "max", "step", "default"):
                    if field in item:
                        item[field] *= scale
    return result


def round_currency(value, scale=1.0, digits=4):
    """Round in calibrated penny units, returning local minor units.

    Keep the original operation at scale one for exact backwards compatibility.
    This is algorithmic precision, not the displayed currency's decimal places.
    """
    if scale == 1.0:
        return round(value, digits)
    return round(value / scale, digits) * scale
