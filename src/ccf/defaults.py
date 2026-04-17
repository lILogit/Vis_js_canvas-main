"""Default field values for CCF v1 compress/restore."""

from typing import Any

NODE_DEFAULTS: dict[str, Any] = {
    "confidence": 0.7,
    "source": "user",
    "deprecated": False,
    "flagged": False,
    "chain_link": None,
    "description": "",
    "tags": [],
    "version": 1,
}

EDGE_DEFAULTS: dict[str, Any] = {
    "weight": 0.5,
    "confidence": 0.5,
    "direction": "forward",
    "source": "user",
    "deprecated": False,
    "flagged": False,
    "version": 1,
    "condition": None,
    "evidence": "",
}

META_DEFAULTS: dict[str, Any] = {
    "version": 1,
    "author": "",
    "description": "",
    "summaries": [],
}
