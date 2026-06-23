"""Source-to-asset-class binding for X (Twitter) handles.

DeItaone and financialjuice produce global macro/geopolitical signals that
are relevant across every asset class.  unusual_whales is equity-specific
(options flow, put/call premium) — feeding it into gold or forex would
generate spurious signals.
"""
from __future__ import annotations

from typing import FrozenSet

from core.enums import AssetClass

# --------------------------------------------------------------------------- #
# Handle → valid AssetClass set
# --------------------------------------------------------------------------- #
X_HANDLE_ASSET_SCOPE: dict[str, FrozenSet[AssetClass]] = {
    # Walter Bloomberg — all-caps geopolitical and macro shocks
    "DeItaone": frozenset({
        AssetClass.EQUITY,
        AssetClass.CRYPTO,
        AssetClass.FOREX,
        AssetClass.GOLD,
    }),
    # Financial Juice — squawk board / audio transcriptions, international macro
    "financialjuice": frozenset({
        AssetClass.EQUITY,
        AssetClass.CRYPTO,
        AssetClass.FOREX,
        AssetClass.GOLD,
    }),
    # Unusual Whales — equity options flow, sector rotation, net put/call
    "unusual_whales": frozenset({
        AssetClass.EQUITY,
    }),
}

# Canonical lower-case lookup (X handles are case-insensitive in practice)
X_HANDLE_ASSET_SCOPE_LOWER: dict[str, FrozenSet[AssetClass]] = {
    k.lower(): v for k, v in X_HANDLE_ASSET_SCOPE.items()
}

# All monitored handles as a flat list for the ingestion layer
MONITORED_HANDLES: list[str] = list(X_HANDLE_ASSET_SCOPE.keys())

# Global handles (apply to all asset classes) — used for signal routing
GLOBAL_HANDLES: FrozenSet[str] = frozenset(
    h for h, scope in X_HANDLE_ASSET_SCOPE.items()
    if len(scope) == len(AssetClass)
)


def is_handle_valid_for(handle: str, asset_class: AssetClass) -> bool:
    """Return True if this handle's signals should be applied to the given asset class."""
    scope = X_HANDLE_ASSET_SCOPE_LOWER.get(handle.lower())
    return scope is not None and asset_class in scope
