"""Tracking numbers: find them in text and links, validate them, guess the carrier and build its public tracking link.

The implementation lives in the family library (``hoard_link.tracking``); this module keeps the names the rest of the app
and its tests import (``numbers.find``, ``numbers.classify``, ``numbers.carrier_name`` ...). Nothing here touches the network.
"""

from __future__ import annotations

from .hoard_link.tracking import (  # noqa: F401
    CARRIER_WORDS, CARRIERS, Found, Tracking, carrier_name, carriers_mentioned, classify, clean_url, find, from_url, normalize, plausible,
    s10_valid, tracking_url, unwrap, ups_valid,
)
