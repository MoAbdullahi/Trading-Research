"""Per-asset-class session metadata and VWAP anchoring rules.

This is the single source of truth that stops the US-equity assumptions from
leaking into 24/7 crypto or 24/5 FX. The feature engine asks this module
"when does the session/anchor start for this bar?" rather than hard-coding 09:30.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from enum import Enum

from core.enums import AssetClass


class VwapAnchorMode(str, Enum):
    SESSION_OPEN = "session_open"     # equities: reset at 09:30 ET
    ROLLING_24H = "rolling_24h"       # crypto: trailing 24h window
    UTC_MIDNIGHT = "utc_midnight"     # crypto alt: reset 00:00 UTC
    MULTI_SESSION = "multi_session"   # fx/gold: Tokyo / London / NY anchors


@dataclass(frozen=True)
class SessionWindow:
    name: str
    open_t: time   # in the profile's reference timezone
    close_t: time


@dataclass(frozen=True)
class SessionProfile:
    asset_class: AssetClass
    tz: str                       # IANA tz the windows are expressed in
    continuous: bool              # True for 24/7 crypto
    vwap_anchor: VwapAnchorMode
    orb_minutes: int              # opening-range length
    windows: tuple[SessionWindow, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #
EQUITY_PROFILE = SessionProfile(
    asset_class=AssetClass.EQUITY,
    tz="America/New_York",
    continuous=False,
    vwap_anchor=VwapAnchorMode.SESSION_OPEN,
    orb_minutes=5,
    windows=(SessionWindow("rth", time(9, 30), time(16, 0)),),
)

CRYPTO_PROFILE = SessionProfile(
    asset_class=AssetClass.CRYPTO,
    tz="UTC",
    continuous=True,
    vwap_anchor=VwapAnchorMode.UTC_MIDNIGHT,  # swap to ROLLING_24H per strategy
    orb_minutes=15,  # "open" must be a *defined* window for 24/7 assets
    windows=(SessionWindow("utc_day", time(0, 0), time(23, 59)),),
)

# FX / Gold: three rolling session anchors. The London-open breakout is the
# meaningful ORB analogue here, not a single daily open.
FX_GOLD_WINDOWS = (
    SessionWindow("tokyo", time(0, 0), time(9, 0)),     # times in UTC
    SessionWindow("london", time(7, 0), time(16, 0)),
    SessionWindow("new_york", time(12, 0), time(21, 0)),
)

FOREX_PROFILE = SessionProfile(
    asset_class=AssetClass.FOREX,
    tz="UTC",
    continuous=False,
    vwap_anchor=VwapAnchorMode.MULTI_SESSION,
    orb_minutes=15,
    windows=FX_GOLD_WINDOWS,
)

GOLD_PROFILE = SessionProfile(
    asset_class=AssetClass.GOLD,
    tz="UTC",
    continuous=True,   # preserve all 24h bars — rth_filter must not trim gold;
                       # H4 resampling in CRTSignalProvider needs the full stream.
                       # Session logic (Asian KZ, London open) lives in the provider.
    vwap_anchor=VwapAnchorMode.MULTI_SESSION,
    orb_minutes=15,
    windows=FX_GOLD_WINDOWS,
)

PROFILES: dict[AssetClass, SessionProfile] = {
    AssetClass.EQUITY: EQUITY_PROFILE,
    AssetClass.CRYPTO: CRYPTO_PROFILE,
    AssetClass.FOREX: FOREX_PROFILE,
    AssetClass.GOLD: GOLD_PROFILE,
}


def profile_for(asset_class: AssetClass) -> SessionProfile:
    return PROFILES[asset_class]
