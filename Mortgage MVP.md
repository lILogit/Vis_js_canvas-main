# Mortgage MVP (Phase 4 demonstration)

This is the minimal end-to-end Living Code demo, built on the existing Causal Editor stack. It exercises every layer of the architecture (chain → grammar → forge → simulate → enrichment → re-forge) on one realistic Czech mortgage scenario. Once this MVP runs, all other vertical chains (hiring decision, capex, energy audit) reuse the same plumbing.

**Scope:** one chain, six branches, one LLM enrichment cycle, deterministic outputs. **Out of scope:** json file persistence, cron daemon, multi-user, web dashboard, EEL calibration loop.

---

## Reference scenario (immutable, all tests anchor here)

|Parameter|Value|
|---|---|
|Mortgage principal|2 400 000 CZK|
|Annual rate (current)|4.9 %|
|Years remaining|18|
|Net monthly income|85 000 CZK|
|Savings reserve|800 000 CZK|
|Months to fixation end|3|
|Domain|`osobni-finance`|
|Chain id|`mortgage-mvp`|

This scenario is **the seed test fixture**. Every CI run, every regression test, every demo screenshot uses these numbers. Do not parameterize prematurely — concrete > general for MVP.

---

## TODO list (6 tasks, ordered by dependency)

### T1 — Seed chain authoring + grammar validation

**Files:**

- `chains/mortgage-mvp-seed.causal.json` (new — seed file, read-only)
- `chains/mortgage-mvp.causal.json` (new — editable copy)
- `tests/test_mortgage_seed.py` (new)

**Inputs:** the reference scenario above + RCDE Grammar v2.

**Deliverable:** a seed `.causal.json` that:

- Contains exactly **6 decision branches**: `keep_as_is`, `partial_prepay`, `full_prepay`, `refinance`, `fixation_renewal`, `extend_term`
- Has **4 STATE nodes**: `MortgageActive`, `MonthlyIncome`, `SavingsReserve`, `FixationEndingSoon`
- Has **1 EVENT** (`RateReviewEvent`), **1 GATE** (`FinancialViabilityGate`), **1 DECISION** (`MortgageStrategy`)
- Has **2 ASSETs**: `AltBankOffer` (rate=4.2%, fees=15k), `RenewalOffer` (rate=4.5%)
- Has **at least 1 BLACKBOX**: `RateRegime2028` (symptom set, mechanism intentionally absent — Rule G5)
- Has **2-3 GOALs** that branches converge to: `MortgageClosed`, `InterestMinimized`, `PaymentReduced`

**Mapping (1:1 bijective with the python forge output):**

|Chain construct|Python construct|Forge marker|
|---|---|---|
|`node.type=state`|`@STATE @dataclass class`|decorator only|
|`node.type=event`|`@EVENT @certainty(p) def`|decorator only|
|`node.type=gate`|`@GATE(kind, depth) def → bool`|decorator only|
|`node.type=decision`|`@DECISION(branches=[...]) def`|branches list literal|
|`node.type=task`|`@TASK @certainty(p) def(ctx, *assets)`|decorator only|
|`node.type=asset`|`@ASSET @dataclass class`|typed param to TASK|
|`node.type=goal`|`@GOAL(payoff_expr=...) class`|decorator only|
|`node.type=blackbox`|`@BLACKBOX class { symptom = "..." }`|class attribute|
|`edge.relation=CAUSES`|`causes(src_id, dst_id)` in CHAIN list|manifest only|
|`edge.relation=TRIGGERS`|`triggers(src_id, dst_id)` in CHAIN list|manifest only|
|`edge.relation=ENABLES`|`enables(asset_id, task_id)` in CHAIN list|manifest only|
|`edge.relation=REDUCES`|`reduces(task_id, state_id, field, delta)` in CHAIN|manifest only|

**Forbidden locations (anti-patterns) — fail seed validation:**

- Certainty value in docstring or comment (must be in `@STATE(certainty=…)` decorator arg)
- BLACKBOX rendered through `print()` or string label (must be `@BLACKBOX class` with `symptom` attribute)
- GOAL as `return dict(...)` (must be `@GOAL class` with `payoff_expr`)
- Edge declaration via call ordering in `if __name__`-block (only the `CHAIN = [...]` manifest carries edges)
- Magic strings instead of node IDs (every reference uses `rcde_id`)
- Missing `_forge_meta` block at module top
- Sections out of canonical order (must be: STATES → ASSETS → EVENTS → GATES → DECISIONS → TASKS → TERMINALS → CHAIN)

**Acceptance criteria:**

- [ ] `python3 cli.py validate chains/mortgage-mvp-seed.causal.json` → "7/7 grammar rules pass"
- [ ] All node IDs use snake_case
- [ ] Every BLACKBOX has `symptom` field set, no `mechanism` field
- [ ] Every TASK either has a `REDUCES` edge to a STATE or a `INSTANTIATES` edge to a GOAL
- [ ] Test `test_mortgage_seed.py::test_grammar_passes` green
- [ ] Test `test_mortgage_seed.py::test_node_count_matches_spec` green (4 STATE + 1 EVENT + 1 GATE + 1 DECISION + 6 TASK + 2 ASSET + ≥2 GOAL + ≥1 BLACKBOX)

**Estimate:** 1 day.

---

### T2 — CHAINFORGE: emit deterministic Python from chain

**Files:**

- `src/forge/__init__.py` (new)
- `src/forge/emit.py` (new — `forge_chain(chain) → str`)
- `src/forge/runtime.py` (new — decorators + edge constructors)
- `src/forge/canonical.py` (new — deterministic ordering + AST hash)
- `runtime/mortgage_mvp.py` (generated, git-tracked for diffs)
- `tests/test_forge.py` (new)

**Inputs:** validated `chains/mortgage-mvp.causal.json` from T1.

**Deliverable:** `forge_chain(chain) → str` produces a Python module with:

1. **Module docstring** (1-line, ignored by future lift)
2. **`_forge_meta` dict** with `source_chain`, `source_hash` (sha256 of canonical-ordered chain JSON), `forge_version`, `timestamp`
3. **Section banners** in fixed order:
    - `# ─── STATES ──────`
    - `# ─── ASSETS ──────`
    - `# ─── EVENTS ──────`
    - `# ─── GATES ──────`
    - `# ─── DECISIONS ──────`
    - `# ─── TASKS ──────`
    - `# ─── TERMINALS ──────`
    - `# ─── CHAIN ──────`
    - `# ─── ENTRY POINT ──────`
4. **Within each section, items sorted alphabetically by `rcde_id`** (determinism)
5. **`CHAIN = [...]` list** with edges sorted by `(edge_type, src_id, dst_id)` — deterministic
6. **`if __name__ == "__main__"`** block with `simulate(CHAIN, mode="monte_carlo", n=10000, seed=42)` + scenario printer

**Determinism contract:**

- Two consecutive `forge_chain()` calls on same chain produce **byte-identical output** (modulo `_forge_meta.timestamp`)
- Section ordering is fixed (alphabetic on `rcde_id`)
- Edge ordering is fixed (`(edge_type, src_id, dst_id)`)
- Float formatting is fixed (`f"{x:.4f}"` for confidence, `f"{x:_}"` for integers)
- No conditional imports, no random ordering anywhere

**Forge runtime stubs (`src/forge/runtime.py`):** decorators must be importable so the generated module runs:

```python
def STATE(certainty=1.0, archetype=None, rcde_id=None):
    def wrap(cls):
        cls._rcde_id = rcde_id
        cls._certainty = certainty
        cls._archetype = archetype
        _REGISTRY[rcde_id] = ("STATE", cls)
        return cls
    return wrap

# similarly for EVENT, GATE, DECISION, TASK, ASSET, GOAL, BLACKBOX

def triggers(src, dst): return ("TRIGGERS", src, dst)
def causes(src, dst): return ("CAUSES", src, dst)
def enables(src, dst): return ("ENABLES", src, dst)
def reduces(src, dst, field=None, delta=None): return ("REDUCES", src, dst, field, delta)

def simulate(chain, mode, n, seed, initial_state=None):
    """Returns SimResult (see T4)."""
    pass  # implemented in T4
```

**Acceptance criteria:**

- [ ] `python3 cli.py forge chains/mortgage-mvp.causal.json --out runtime/mortgage_mvp.py` exits 0
- [ ] `python3 runtime/mortgage_mvp.py` runs without import errors (returns dummy result if T4 not yet done)
- [ ] Test `test_forge.py::test_byte_identical_reforge` green: forge twice, compare bytes (excluding timestamp line) — must be identical
- [ ] Test `test_forge.py::test_section_ordering` green: parse forged module, verify sections in canonical order
- [ ] Test `test_forge.py::test_no_anti_patterns` green: scan output for forbidden patterns (cert in docstring, GOAL as dict, etc.)
- [ ] Run `forge_chain` on broken chain (missing certainty) → raises `ForgeError`, does NOT emit best-effort output


---

### T3 — Simulate: branch payoff calculation

**Files:**

- `src/simulate/__init__.py` (new)
- `src/simulate/runner.py` (new — `simulate(chain, mode, n, seed, initial_state)`)
- `src/simulate/payoff.py` (new — domain-specific payoff calculations)
- `src/simulate/recommend.py` (new — ranking + recommendation generation)
- `tests/test_simulate.py` (new)

**Inputs:** forged `runtime/mortgage_mvp.py` from T2.

**Deliverable:** simulator that runs each of the 6 branches once with reference scenario inputs and produces a comparison table identical to:

```
═══════════════════════════════════════════════════════════════
HYPOTÉKA — POROVNÁNÍ VARIANT (před enrichmentem)
jistina 2,4 M · sazba 4,9 % · 18 let · příjem 85k · rezerva 800k
═══════════════════════════════════════════════════════════════

Varianta                       Měs.splát.   Celk.úrok   Úspora    Doba    Rezerva po   DTI
─────────────────────────────────────────────────────────────────────────────────────────
Ponechat beze změny                17 109   1 295 619    —       18 let    800 000    20.1%
Mimořádná splátka 500 000          17 109     895 234   +400 385  13 let   300 000    20.1%
Úplné splacení (konec fixace)           0          0  +1 295 619  splaceno -1 600 000     —
Refinancování @ 4.20% (+15k popl.) 16 234     915 432   +380 187  18 let    785 000    19.1%
Nová fixace @ 4.50%                16 743   1 015 123   +280 496  18 let    800 000    19.7%
Prodloužit na 25 let @ 4.50%       13 363   1 608 856   −313 237  25 let    800 000    15.7%
─────────────────────────────────────────────────────────────────────────────────────────
```

**Functional requirements:**

- Annuity formula: `P × r(1+r)^n / ((1+r)^n − 1)` for monthly payment
- Partial prepay: keep monthly amount, recompute remaining months
- Full prepay: penalty = 0 at end of fixation (Czech law), reserve goes negative — flag in recommendation
- Refinance: include fees in total cost, reserve drops by fees
- Renewal: same months, new rate, no fees
- Extend: new months × current monthly at new rate
- DTI = monthly_payment / monthly_income; flag if > 0.45

**Recommendation engine (`src/simulate/recommend.py`):**

Ranks variants by composite score combining:

- Total interest saved (positive contribution)
- Reserve depletion penalty (heavy penalty if reserve goes < 100k)
- DTI penalty (heavy penalty if DTI > 0.45)
- Time horizon match (penalty if extending beyond user's preference)

Returns top-3 with text rationale per variant. Format:

```
DOPORUČENÍ (před enrichmentem)
─────────────────────────────────────────────
1. ★ Refinancování @ 4.20%  (skóre 0.847)
   důvod: ušetří 380k CZK, DTI klesne na 19.1%, rezerva intaktní
   pozor:  poplatky 15k, 4 měsíce procesu
   confidence:  0.75 (závisí na schválení Alt banky)

2. Mimořádná splátka 500k  (skóre 0.812)
   důvod: ušetří 400k CZK, zkrátí dobu o 5 let
   pozor:  rezerva klesne na 300k (hraniční), nelze refinancovat za běžné sazby

3. Nová fixace @ 4.50%  (skóre 0.756)
   důvod: ušetří 280k CZK bez nákladů, jistá varianta u stejné banky
   pozor:  méně agresivní úspora než refinancování
─────────────────────────────────────────────
```

**Acceptance criteria:**

- [ ] All 6 branches produce numerical output (no NaN, no errors)
- [ ] Numbers match hand-calculated reference within 1 CZK (tolerance for float)
- [ ] DTI flagging works: artificially set income to 30k → all branches except `extend_term` fail DTI gate
- [ ] Reserve depletion warning triggers on `full_prepay` (reserve < 0) and `partial_prepay` if amount > savings
- [ ] Recommendation top-3 is stable across 10 simulation runs (deterministic ranking)
- [ ] Test `test_simulate.py::test_reference_scenario_payoffs` green with hardcoded expected values



---

### T4 — Monte Carlo + sensitivity + path probability

**Files:**

- `src/simulate/montecarlo.py` (new)
- `src/simulate/sensitivity.py` (new)
- `src/simulate/trace.py` (new — JSONL trace emitter)
- `tests/test_montecarlo.py` (new)

**Inputs:** simulator from T3, forge runtime from T2.

**Deliverable:** add probabilistic dimension to the deterministic comparison from T3.

**Three modes:**

1. **Deterministic** (T3 output) — single best path, exact numbers
2. **Monte Carlo** — n=10000 runs, sample certainties as noise around declared values, output distribution
3. **Sensitivity** — for each node, compute `Δ output / Δ certainty` (perturb ±10%, observe shift)

Path probability per branch = product of certainties along the branch path: `P(branch) = Π certainties`. With reference scenario:

```
─── path probabilities (Monte Carlo n=10000) ─────────────
keep_as_is               0.836  ← baseline
partial_prepay           0.748
full_prepay              0.862  ← highest, since cert(full)=0.98
refinance                0.660  ← lowest, AltBankOffer cert=0.75
fixation_renewal         0.792
extend_term              0.774

─── sensitivity (top 3) ──────────────────────────────────
1. refinance         exposure 0.340  ← collect data here first
2. partial_prepay    exposure 0.252
3. extend_term       exposure 0.226
```

**Trace format (JSONL, one line per simulated step):**

```json
{"run_id":"r_abc123","step":0,"node_id":"MortgageActive","node_type":"STATE","certainty_declared":1.00,"branch_taken":null,"timestamp_utc":"2026-04-23T14:30:01.123Z"}
{"run_id":"r_abc123","step":1,"node_id":"RateReviewEvent","node_type":"EVENT","certainty_declared":0.95,"certainty_sampled":0.93,"branch_taken":null,"timestamp_utc":"2026-04-23T14:30:01.124Z"}
{"run_id":"r_abc123","step":2,"node_id":"FinancialViabilityGate","node_type":"GATE","certainty_declared":0.88,"branch_taken":"pass","timestamp_utc":"2026-04-23T14:30:01.124Z"}
{"run_id":"r_abc123","step":3,"node_id":"refinance","node_type":"TASK","certainty_declared":0.75,"certainty_sampled":0.74,"branch_taken":null,"goal_reached":"InterestMinimized","payoff":380187,"timestamp_utc":"2026-04-23T14:30:01.125Z"}
```

Output to `runs/trace_mortgage_mvp_<UTC_TIMESTAMP>.jsonl`. Append-only. Never mutate after write.

**Acceptance criteria:**

- [ ] Monte Carlo with n=10000, seed=42 → reproducible bit-exact across runs
- [ ] Sensitivity ranking stable across 5 consecutive runs (same top-3 in same order)
- [ ] Trace JSONL is valid (parseable line-by-line, no truncated records)
- [ ] `simulate(..., mode="monte_carlo", n=10000)` completes in < 5 seconds on dev laptop
- [ ] Path probabilities sum > 1.0 across all branches (they're not mutually exclusive in this case — each is a what-if)
- [ ] Test `test_montecarlo.py::test_sensitivity_finds_lowest_certainty_node` green

**Estimate:** 3 days.

---

### T5 — Enrichment from text: LLM extraction → typed evidence → graph mutation

**Files:**

- `src/enrichment/__init__.py` (new)
- `src/enrichment/extract.py` (new — schema-bound LLM call)
- `src/enrichment/classify.py` (new — E1-E6 classification)
- `src/enrichment/gate.py` (new — 5-gate pipeline)
- `src/enrichment/apply.py` (new — graph mutation)
- `llm/prompts.py` (modify — add `URL_EXTRACT` constant)
- `tests/test_enrichment.py` (new)
- `tests/fixtures/komercka_rate_cut_2026.txt` (new — verbatim test article)

**Inputs:** chain from T1, simulator from T3-T4, this article text:

> Komerční banka snížila hypoteční sazbu na 3.95 % u 5leté fixace, čímž se stala nejnižší na trhu. Nabídka platí do konce Q2 2026 pro klienty s LTV < 80 %.

**Deliverable:** end-to-end enrichment cycle that:

**Step 1 — LLM extraction** (`extract.py`):

Schema (passed as `response_format` to Claude API):

```json
{
  "type": "object",
  "required": ["events"],
  "properties": {
    "events": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "class", "target_node_id", "direction", "magnitude",
          "extraction_confidence", "text_span"
        ],
        "properties": {
          "class": {"enum": ["E1", "E2", "E3", "E4", "E5", "E6"]},
          "target_node_id": {
            "enum": ["AltBankOffer.rate", "RenewalOffer.rate",
                     "MortgageActive.annual_rate", "FixationEndingSoon",
                     "RateRegime2028", "MonthlyIncome", "SavingsReserve"]
          },
          "direction": {"enum": ["up", "down", "neutral"]},
          "magnitude": {"type": "number", "minimum": 0, "maximum": 1},
          "new_value_hint": {"type": "number"},
          "extraction_confidence": {"type": "number", "minimum": 0, "maximum": 1},
          "text_span": {"type": "string", "maxLength": 500},
          "reasoning": {"type": "string", "maxLength": 500}
        }
      }
    }
  }
}
```

Expected LLM output for the test article:

```json
{
  "events": [{
    "class": "E1",
    "target_node_id": "AltBankOffer.rate",
    "direction": "down",
    "magnitude": 0.025,
    "new_value_hint": 0.0395,
    "extraction_confidence": 0.92,
    "text_span": "Komerční banka snížila hypoteční sazbu na 3.95 %",
    "reasoning": "Specific numeric claim from named institution; conditional on LTV<80% but that fits borrower profile"
  }]
}
```

**Step 2 — Classify** (`classify.py`): map raw event to E1-E6 with archetype. For E1 (certainty/value update) auto-eligible for application.

**Step 3 — Five gates** (`gate.py`), in this exact order:

1. **Schema validation** — already enforced by Claude API response_format; if return is malformed, drop event
2. **Credibility gate** — `source_credibility × extraction_confidence ≥ 0.75`. For MVP hardcode source credibilities:
    - `hn.cz`: 0.88
    - `cnb.cz`: 0.95
    - `unknown`: 0.50
3. **Bounded shift** — proposed delta ≤ ±0.10 per cycle. Event proposes shift; gate caps it.
4. **Grammar re-check** — apply mutation in-memory, run all 7 RCDE rules, abort if any fails
5. **Circuit breaker** — run T3 simulation before/after, if any branch's payoff shifts by > 15% → human gate

**Step 4 — Apply** (`apply.py`): if all gates pass and event class is E1, write to chain JSON, append to `chain.evidence` ledger:

```json
"evidence": [{
  "id": "ev_2026-04-23_komercka_rate_cut",
  "timestamp": "2026-04-23T09:14:23Z",
  "source": "hn.cz",
  "source_credibility": 0.88,
  "extraction_confidence": 0.92,
  "text_span": "Komerční banka snížila hypoteční sazbu na 3.95 %",
  "reasoning": "Specific numeric claim from named institution",
  "class": "E1",
  "target_node_id": "AltBankOffer.rate",
  "old_value": 0.042,
  "new_value": 0.0400,
  "shift_proposed": 0.0025,
  "shift_applied": 0.0025,
  "shift_capped_by_bounds": false,
  "applied": true
}]
```

For E2-E6 (structural changes): do **not** auto-apply, write to `chain.pending_review` array, return to user via CLI/UI.

**Acceptance criteria:**

- [ ] `python3 cli.py enrich-text chains/mortgage-mvp.causal.json --text-file tests/fixtures/komercka_rate_cut_2026.txt` exits 0
- [ ] LLM call returns schema-conformant JSON (no preamble, no markdown)
- [ ] `target_node_id` enum prevents hallucination (test: feed article about unrelated topic → no events extracted)
- [ ] `AltBankOffer.rate` after enrichment = 0.0400 (was 0.042, capped from 0.025 shift to 0.10 max — actually 0.025 < 0.10 so no cap)
- [ ] `chain.evidence` array has exactly one entry after enrichment
- [ ] `_status` flag on AltBankOffer node updated to reflect modification
- [ ] Test `test_enrichment.py::test_komercka_article_yields_e1` green
- [ ] Test `test_enrichment.py::test_unrelated_article_yields_zero_events` green (feed weather article, expect empty)
- [ ] Test `test_enrichment.py::test_low_credibility_source_blocks_apply` green



---

### T6 — Re-forge + byte-level diff + post-enrichment recommendation

**Files:**

- `runtime/mortgage_mvp.py` (regenerated after T5 mutation)
- `runs/diff_mortgage_mvp_<TIMESTAMP>.txt` (new — diff output)
- `src/forge/diff.py` (new — semantic diff between chain versions)
- `tests/test_reforge.py` (new)

**Inputs:** mutated chain from T5, original forged Python from T2.

**Deliverable:** show end-to-end Living Code loop closing.

**Step 1 — Re-forge:** rerun `forge_chain()` on the post-enrichment chain. Output to same `runtime/mortgage_mvp.py`.

**Step 2 — Byte-level diff:** show exactly what changed in Python. Expected diff:

```diff
--- runtime/mortgage_mvp.py  (2026-04-23T08:00:00Z, hash a7f3c9e2…)
+++ runtime/mortgage_mvp.py  (2026-04-23T09:15:00Z, hash b8e4d1f7…)
@@ -8,9 +8,10 @@
     "source_chain":  "mortgage-mvp",
-    "source_hash":   "sha256:a7f3c9e2…",
-    "timestamp":     "2026-04-23T08:00:00Z",
+    "source_hash":   "sha256:b8e4d1f7…",
+    "timestamp":     "2026-04-23T09:15:00Z",
+    "last_enrichment": "ev_2026-04-23_komercka_rate_cut",
 }

@@ -47,8 +48,12 @@
-@ASSET(rcde_id="AltBankOffer")
+@ASSET(
+    rcde_id="AltBankOffer",
+    confidence=0.82,
+    _evidence_refs=["ev_2026-04-23_komercka_rate_cut"]
+)
 @dataclass
 class AltBankOffer:
-    rate: float = 0.0420
+    rate: float = 0.0400
     fees: float = 15_000
```

**Three lines changed.** Each carries provenance via `_evidence_refs`. Diff is human-readable.

**Step 3 — Re-run simulation** on enriched chain. Generate **new comparison table** with refinance branch now using 4.00% rate (was 4.20%):

```
═══════════════════════════════════════════════════════════════
HYPOTÉKA — POROVNÁNÍ VARIANT (po enrichmentu z 2026-04-23)
ZMĚNA: AltBankOffer.rate 4.20% → 4.00% (zdroj: hn.cz/komercka)
═══════════════════════════════════════════════════════════════

Varianta                       Měs.splát.   Celk.úrok   Úspora    Změna
─────────────────────────────────────────────────────────────────────────
Ponechat beze změny                17 109   1 295 619    —          —
Mimořádná splátka 500 000          17 109     895 234   +400 385    —
Úplné splacení                          0          0  +1 295 619    —
Refinancování @ 4.00% (+15k popl.) 15 952     872 187   +423 432  +43 245  ← shift!
Nová fixace @ 4.50%                16 743   1 015 123   +280 496    —
Prodloužit na 25 let               13 363   1 608 856   −313 237    —

DOPORUČENÍ (po enrichmentu)
─────────────────────────────────────────────
1. ★ Refinancování @ 4.00%  (skóre 0.892, +0.045 oproti minulému)
   důvod: ušetří 423k CZK (o 43k více než před zprávou), DTI 18.0%
   pozor:  poplatky 15k, čas do konce nabídky: ~67 dní (Q2 2026 deadline)
   confidence:  0.82 (vyšší než minule, evidence z HN)

2. Mimořádná splátka 500k  (beze změny — 0.812)
3. Nová fixace @ 4.50%      (beze změny — 0.756)
─────────────────────────────────────────────

UPOZORNĚNÍ
─────────────────────────────────────────────
- AltBankOffer (Komerční banka) má time-bound nabídku do konce Q2 2026
- Doporučujeme rozhodnutí do 30 dnů, dokud nabídka platí
- BLACKBOX 'RateRegime2028' stále nezměněn — refinancování dnes
  vás nechrání proti rate spike po 5leté fixaci
─────────────────────────────────────────────
```

**Note the recommendation engine pulls **deadline awareness** from the article's text span (`text_span: "Nabídka platí do konce Q2 2026"`). The original `RenewalOffer` had no time bound, so it remains stable across enrichments. This is a real benefit of provenance: time-sensitivity propagates from text to recommendation.**

**Acceptance criteria:**

- [ ] Re-forge produces byte-identical diff structure as expected (timestamp + hash + 3 substantive lines)
- [ ] Old runtime can be restored via `git checkout runtime/mortgage_mvp.py`
- [ ] Post-enrichment simulation correctly uses 4.00% rate
- [ ] Recommendation #1 changes ranking score by +0.045 (consistent with 43k CZK additional savings)
- [ ] Deadline warning extracted from `text_span` and shown in recommendation
- [ ] `chain.evidence` ledger linked from each modified node via `_evidence_refs`
- [ ] Test `test_reforge.py::test_byte_identical_after_enrichment` green
- [ ] Test `test_reforge.py::test_recommendation_changes_after_e1` green
- [ ] Test `test_reforge.py::test_provenance_chain_complete` green (every modification points to an evidence id)



---

## End-to-end demo script

After T1-T6 complete, this single command runs the full Living Code cycle:

```bash
#!/bin/bash
# demo_mortgage_mvp.sh
set -e

echo "═══ STEP 1: Validate seed chain ═══"
python3 cli.py validate chains/mortgage-mvp-seed.causal.json

echo "═══ STEP 2: Reset to seed (clean state) ═══"
python3 cli.py reset-demo

echo "═══ STEP 3: Forge to Python ═══"
python3 cli.py forge chains/mortgage-mvp.causal.json --out runtime/mortgage_mvp.py

echo "═══ STEP 4: Run simulation (PRE-enrichment) ═══"
python3 runtime/mortgage_mvp.py > runs/recommendation_pre.txt
cat runs/recommendation_pre.txt

echo "═══ STEP 5: Enrich from Komerční banka article ═══"
python3 cli.py enrich-text chains/mortgage-mvp.causal.json \
  --text-file tests/fixtures/komercka_rate_cut_2026.txt \
  --source hn.cz

echo "═══ STEP 6: Re-forge ═══"
python3 cli.py forge chains/mortgage-mvp.causal.json --out runtime/mortgage_mvp.py

echo "═══ STEP 7: Show byte-level diff ═══"
git diff --no-index runtime/mortgage_mvp.py.before runtime/mortgage_mvp.py | tee runs/diff_post_enrichment.txt

echo "═══ STEP 8: Run simulation (POST-enrichment) ═══"
python3 runtime/mortgage_mvp.py > runs/recommendation_post.txt
cat runs/recommendation_post.txt

echo "═══ STEP 9: Show what changed in recommendation ═══"
diff runs/recommendation_pre.txt runs/recommendation_post.txt | tee runs/recommendation_change.txt

echo "═══ DEMO COMPLETE ═══"
echo "Artifacts: runs/recommendation_pre.txt, runs/recommendation_post.txt,"
echo "           runs/diff_post_enrichment.txt, runs/recommendation_change.txt"
```

**This script IS the demo.** Record it as asciinema cast for landing page (`hypoteka.jiri.cz`). Three minutes of terminal output that shows the entire Living Code loop on real Czech data with real news article. Nobody else in the SME tooling space can produce this.

---

## Dependencies graph between tasks

```
T1 (seed) ──┬──> T2 (forge) ──┬──> T3 (simulate) ──┬──> T5 (enrich) ──> T6 (reforge)
            │                 │                     │
            │                 └──> T4 (montecarlo) ──┘
            │
            └──> validate (existing CLI)
```

T2 and T3 unblock everything else. T4 (Monte Carlo) can run parallel with T5 (enrichment) since they use different parts of the codebase. T6 is the integration test, requires all above.

**Earliest finish:** day 12 (assuming 1 day buffer). **Realistic finish with single-track work:** day 15.

---

## Out of scope for MVP (defer to Phase 5+)

- **Multiple chains in same enrichment cycle** — MVP is one chain
- **N8N daemon scheduling** — MVP is manual `cli.py enrich-text`
- **EEL calibration loop** — MVP doesn't run simulations enough to calibrate
- **Browser UI for enrichment review** — MVP uses CLI output
- **Neo4j persistence** — MVP uses `.causal.json` files only
- **Multi-perspective views** (cognitive flexibility item #1) — MVP is single perspective
- **Confidence intervals** (cognitive flexibility item #2) — MVP uses point estimates
- **HYPOTHESIS nodes** — MVP uses concrete decision trees only

These will land in subsequent MVPs (hiring decision, energy audit). Their absence in mortgage MVP is intentional — keep it shipping.

---

## Open questions for resolution before T1 starts

1. **Rounding convention for CZK display** — round to whole crowns, or keep two decimal places? (Recommend: whole crowns for display, 4 decimals internally.)
2. **DTI threshold** — is 0.45 the standard for Czech banks today? Verify with one phone call.
3. **Czech mortgage prepayment penalty rules** — is "0 at end of fixation" universally true, or does it depend on contract? Verify.
4. **Time-of-day for daily enrichment runs** (relevant for Phase 7+) — 06:00 CET feels right for European morning briefing. Confirm.
5. **First demo audience** — who sees this first? CASHPULSE existing users? OSVČ peer network? Cold outreach? (Recommend: CASHPULSE users with mortgages first; warm intro.)

Resolve these in 1-2 hour conversation before starting T1. None of them block design, but each affects acceptance criteria.

---

## Definition of MVP done

The MVP is complete when **a stranger can reproduce the demo in under 5 minutes**:

```bash
cp .env.example .env  # paste their own ANTHROPIC_API_KEY
pip install -r requirements.txt
bash demo_mortgage_mvp.sh
```

…and they see the recommendation flip from "refinance saves 380k" to "refinance saves 423k" with a fully audit-trailable diff between the two states, all from one news article that the system parsed itself.

That's the demo. That's what gets recorded for the landing page. That's what gets shown to the first lighthouse client. Everything else is roadmap.