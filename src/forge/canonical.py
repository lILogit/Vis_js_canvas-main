"""Deterministic chain serialisation and hashing."""
import hashlib
import json


def canonical_json(data: dict) -> str:
    """Deterministically serialize a dict to JSON with sorted keys, no whitespace."""
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def chain_hash(chain: dict) -> str:
    """SHA-256 of the canonical JSON representation."""
    return "sha256:" + hashlib.sha256(canonical_json(chain).encode()).hexdigest()
