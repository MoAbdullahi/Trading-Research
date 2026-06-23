"""Anthropic transport for the agent lane.

Isolated here so agent logic never imports the SDK directly. A failure to reach
the API is converted by the caller into an ABSTAIN vote — a transport outage can
never produce a trade, only a no-trade.
"""
from __future__ import annotations

import functools

from core.settings import get_settings


@functools.lru_cache(maxsize=1)
def _client():
    from anthropic import Anthropic

    return Anthropic(api_key=get_settings().anthropic_api_key)


def call_anthropic(
    model: str,
    system: str,
    user: str,
    max_tokens: int = 1024,
    temperature: float = 0.0,
) -> str:
    """Single-turn call. Returns concatenated text blocks. temperature=0 keeps
    the structured-JSON output stable for the deterministic parser downstream."""
    msg = _client().messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "\n".join(
        b.text for b in msg.content if getattr(b, "type", None) == "text"
    ).strip()
