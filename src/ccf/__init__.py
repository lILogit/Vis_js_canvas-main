"""CCF v1 — Causal Compact Format public API."""

from .ccf import compress, compress_file, restore, restore_file, to_prompt

__all__ = ["compress", "compress_file", "restore", "restore_file", "to_prompt"]
