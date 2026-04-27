"""
JSONL trace emitter for mortgage MVP simulation runs.
Writes to runs/trace_<chain_name>_<UTC_TIMESTAMP>.jsonl.
Append-only; never mutates written records.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import IO


def _utcnow() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _runs_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    # Project root is three levels up: src/simulate/ → src/ → project root
    root = os.path.join(here, "..", "..", "runs")
    os.makedirs(root, exist_ok=True)
    return os.path.abspath(root)


class TraceWriter:
    """
    Context manager that writes one JSONL record per simulation step.

    Usage::

        with TraceWriter("mortgage_mvp") as tw:
            tw.step(run_id="r_001", step=0, node_id="mortgage_active",
                    node_type="STATE", certainty_declared=1.0)
    """

    def __init__(self, chain_name: str) -> None:
        ts    = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        fname = f"trace_{chain_name}_{ts}.jsonl"
        self.path: str = os.path.join(_runs_dir(), fname)
        self._fh: IO | None = None

    def __enter__(self) -> "TraceWriter":
        self._fh = open(self.path, "w", encoding="utf-8")
        return self

    def __exit__(self, *_) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None

    def step(
        self,
        *,
        run_id: str,
        step: int,
        node_id: str,
        node_type: str,
        certainty_declared: float,
        certainty_sampled: float | None = None,
        branch_taken: str | None = None,
        goal_reached: str | None = None,
        payoff: float | None = None,
    ) -> None:
        record: dict = {
            "run_id":             run_id,
            "step":               step,
            "node_id":            node_id,
            "node_type":          node_type,
            "certainty_declared": round(certainty_declared, 4),
            "branch_taken":       branch_taken,
            "timestamp_utc":      _utcnow(),
        }
        if certainty_sampled is not None:
            record["certainty_sampled"] = round(certainty_sampled, 4)
        if goal_reached is not None:
            record["goal_reached"] = goal_reached
        if payoff is not None:
            record["payoff"] = round(payoff)

        assert self._fh is not None, "TraceWriter used outside context manager"
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ── Convenience: write a deterministic single-run trace ───────────────────────

_SPINE_STEPS = [
    ("mortgage_active",          "STATE",    1.00),
    ("fixation_ending_soon",     "STATE",    0.95),
    ("rate_review_event",        "EVENT",    0.95),
    ("monthly_income",           "STATE",    1.00),
    ("savings_reserve",          "STATE",    1.00),
    ("financial_viability_gate", "GATE",     0.90),
    ("mortgage_strategy",        "DECISION", 0.85),
]

_BRANCH_STEPS = {
    "keep_as_is":       [("keep_as_is",       "TASK", 0.90)],
    "partial_prepay":   [("partial_prepay",    "TASK", 0.80)],
    "full_prepay":      [("full_prepay",       "TASK", 0.70)],
    "refinance":        [("alt_bank_offer",    "ASSET", 0.75),
                         ("refinance",          "TASK",  0.75)],
    "fixation_renewal": [("renewal_offer",     "ASSET", 0.85),
                         ("fixation_renewal",   "TASK",  0.85)],
    "extend_term":      [("renewal_offer",     "ASSET", 0.85),
                         ("extend_term",        "TASK",  0.70)],
}

_BRANCH_GOALS = {
    "keep_as_is":       "mortgage_closed",
    "partial_prepay":   "interest_minimized",
    "full_prepay":      "mortgage_closed",
    "refinance":        "interest_minimized",
    "fixation_renewal": "interest_minimized",
    "extend_term":      "payment_reduced",
}


def write_deterministic_trace(
    chain_name: str,
    branch_payoffs: list[dict],
    node_certainties: dict[str, float] | None = None,
) -> str:
    """
    Write a deterministic trace covering all 6 branches (one pass each).
    Returns the path of the written file.
    """
    from .montecarlo import DEFAULT_CERTAINTIES  # noqa: PLC0415
    certs = node_certainties if node_certainties is not None else DEFAULT_CERTAINTIES

    payoff_map = {b["branch"]: b["total_interest"] for b in branch_payoffs}

    with TraceWriter(chain_name) as tw:
        for branch_idx, branch_id in enumerate(
            ["keep_as_is", "partial_prepay", "full_prepay",
             "refinance", "fixation_renewal", "extend_term"]
        ):
            run_id = f"r_{branch_idx:03d}"
            step   = 0

            # Spine
            for nid, ntype, c_decl in _SPINE_STEPS:
                is_gate  = ntype == "GATE"
                tw.step(
                    run_id=run_id, step=step,
                    node_id=nid, node_type=ntype,
                    certainty_declared=c_decl,
                    branch_taken="pass" if is_gate else None,
                )
                step += 1

            # Branch-specific steps
            branch_steps = _BRANCH_STEPS.get(branch_id, [])
            for i, (nid, ntype, c_decl) in enumerate(branch_steps):
                is_last = (i == len(branch_steps) - 1)
                tw.step(
                    run_id=run_id, step=step,
                    node_id=nid, node_type=ntype,
                    certainty_declared=certs.get(nid, c_decl),
                    certainty_sampled=certs.get(nid, c_decl),
                    branch_taken=None,
                    goal_reached=_BRANCH_GOALS[branch_id] if is_last else None,
                    payoff=payoff_map.get(branch_id) if is_last else None,
                )
                step += 1

    return tw.path
