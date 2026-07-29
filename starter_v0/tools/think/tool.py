from __future__ import annotations

from typing import Any


def think(reflection: str = "") -> dict[str, Any]:
    """Record a strategic reflection between research steps.

    Mirrors the ``think_tool`` pattern from deep research agents: it creates a
    deliberate pause so the model can analyze findings, assess gaps, and plan the
    next step. It fetches nothing and has no side effects; the reflection is
    returned verbatim as evidence that it was recorded.

    Args:
        reflection: What was found, what is still missing, and the next action.

    Returns:
        A dict echoing the reflection with a ``recorded`` status.
    """
    return {
        "tool": "think",
        "reflection": reflection,
        "status": "recorded",
    }
