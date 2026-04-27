"""
simulate() — branch comparison for a mortgage causal chain.
Supports deterministic (T3) and monte_carlo (T4) modes.
"""
from __future__ import annotations

from .payoff import BRANCH_IDS, REFERENCE_SCENARIO, compute_branch
from .recommend import recommend as _recommend


def simulate(
    chain,
    mode: str = "deterministic",
    n: int = 10_000,
    seed: int = 42,
    initial_state: dict | None = None,
) -> dict:
    """
    Run branch comparison for the mortgage MVP chain.

    Args:
        chain:         CHAIN list from a forged module (graph structure; used by MC path builder)
        mode:          "deterministic" or "monte_carlo"
        n:             Monte Carlo sample count
        seed:          RNG seed (Monte Carlo)
        initial_state: Override scenario parameters; defaults to REFERENCE_SCENARIO

    Returns:
        {mode, scenario, branches, recommendations}
        Monte Carlo mode adds: {path_probabilities, sensitivity}
    """
    scenario = initial_state if initial_state is not None else REFERENCE_SCENARIO
    branches = [compute_branch(bid, scenario) for bid in BRANCH_IDS]
    recs     = _recommend(branches, scenario)

    result: dict = {
        "mode":            mode,
        "scenario":        scenario,
        "branches":        branches,
        "recommendations": recs,
    }

    if mode == "monte_carlo":
        from .montecarlo import get_registry_certainties, monte_carlo  # noqa: PLC0415
        from .sensitivity import branch_exposures, sensitivity_analysis  # noqa: PLC0415

        certs = get_registry_certainties()
        result["path_probabilities"] = monte_carlo(n=n, seed=seed, node_certainties=certs)
        result["sensitivity"]        = sensitivity_analysis(node_certainties=certs)
        result["branch_exposures"]   = branch_exposures(node_certainties=certs)

    return result


def print_comparison(result: dict) -> None:
    """Pretty-print the comparison table to stdout."""
    s   = result["scenario"]
    sep = "─" * 89

    print("═" * 89)
    print("HYPOTÉKA — POROVNÁNÍ VARIANT")
    print(
        f"jistina {s['principal']:,} · sazba {s['annual_rate']*100:.1f} % "
        f"· {s['years_remaining']} let · příjem {s['monthly_income']:,} · "
        f"rezerva {s['reserve']:,}"
    )
    print("═" * 89)
    print(f"{'Varianta':<32}  {'Měs.splát.':>10}  {'Celk.úrok':>11}  "
          f"{'Úspora':>11}  {'Měsíce':>7}  {'Rezerva po':>11}  {'DTI':>6}")
    print(sep)

    _NAMES = {
        "keep_as_is":       "Ponechat beze změny",
        "partial_prepay":   "Mimořádná splátka 500k",
        "full_prepay":      "Úplné splacení",
        "refinance":        "Refinancování @ 4.20% (+15k)",
        "fixation_renewal": "Nová fixace @ 4.50%",
        "extend_term":      "Prodloužit na 25 let @ 4.50%",
    }

    for b in result["branches"]:
        name    = _NAMES.get(b["branch"], b["branch"])
        monthly = f"{b['monthly_payment']:>10,.0f}"
        total_i = f"{b['total_interest']:>11,.0f}"
        saved   = b["interest_saved"]
        saved_s = f"{'+' if saved > 0 else ''}{saved:>+10,.0f}" if saved != 0 else f"{'—':>11}"
        months  = f"{b['months']:>7.0f}"
        res     = f"{b['reserve_after']:>11,.0f}"
        dti_s   = f"{b['dti']*100:>5.1f}%" if b["dti"] > 0 else f"{'—':>6}"
        print(f"{name:<32}  {monthly}  {total_i}  {saved_s}  {months}  {res}  {dti_s}")

    print(sep)
    print()
    print("DOPORUČENÍ")
    print("─" * 50)
    for rec in result["recommendations"]:
        print(f"{rec['rank']}. ★ {rec['label']}  (skóre {rec['score']:.3f})")
        print(f"   důvod:  {rec['reason']}")
        print(f"   pozor:  {rec['caveat']}")
        print()
