"""
Forge runtime — decorators and edge constructors used by generated chain modules.
Import this module; do not execute it directly.
"""
from __future__ import annotations

_REGISTRY: dict = {}


def _node_decorator(kind: str):
    """Factory that produces a parametric node decorator."""
    def decorator(certainty: float = 1.0, archetype: str | None = None,
                  rcde_id: str | None = None, **kwargs):
        def wrap(cls):
            cls._rcde_id    = rcde_id
            cls._certainty  = certainty
            cls._archetype  = archetype
            if rcde_id:
                _REGISTRY[rcde_id] = (kind, cls)
            return cls
        return wrap
    return decorator


STATE    = _node_decorator("STATE")
ASSET    = _node_decorator("ASSET")
EVENT    = _node_decorator("EVENT")
GATE     = _node_decorator("GATE")
DECISION = _node_decorator("DECISION")
TASK     = _node_decorator("TASK")
GOAL     = _node_decorator("GOAL")
BLACKBOX = _node_decorator("BLACKBOX")

# ── Edge constructors ─────────────────────────────────────────────────────────

def causes(src: str, dst: str) -> tuple:
    return ("CAUSES", src, dst)

def enables(src: str, dst: str) -> tuple:
    return ("ENABLES", src, dst)

def triggers(src: str, dst: str) -> tuple:
    return ("TRIGGERS", src, dst)

def reduces(src: str, dst: str, field: str | None = None,
            delta: float | None = None) -> tuple:
    return ("REDUCES", src, dst, field, delta)

def frames(src: str, dst: str) -> tuple:
    return ("FRAMES", src, dst)

def instantiates(src: str, dst: str) -> tuple:
    return ("INSTANTIATES", src, dst)

def precondition_of(src: str, dst: str) -> tuple:
    return ("PRECONDITION_OF", src, dst)

def diverges_to(src: str, dst: str) -> tuple:
    return ("DIVERGES_TO", src, dst)

def blocks(src: str, dst: str) -> tuple:
    return ("BLOCKS", src, dst)

def amplifies(src: str, dst: str) -> tuple:
    return ("AMPLIFIES", src, dst)

def resolves(src: str, dst: str) -> tuple:
    return ("RESOLVES", src, dst)

def requires(src: str, dst: str) -> tuple:
    return ("REQUIRES", src, dst)


# ── Simulation (delegates to simulate.runner when installed) ──────────────────

try:
    from simulate.runner import simulate  # T3+ real implementation
except ImportError:
    def simulate(chain: list, mode: str = "deterministic",  # type: ignore[misc]
                 n: int = 10_000, seed: int = 42,
                 initial_state: dict | None = None):
        """Stub — install simulate package (T3) for real implementation."""
        return None
