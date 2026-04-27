#!/bin/bash
# demo_mortgage_mvp.sh — full Living Code cycle: T1→T6
# Usage: bash demo_mortgage_mvp.sh
#
# Requirements:
#   - ANTHROPIC_API_KEY in .env (needed for Step 5 only)
#   - All other steps run without a key
set -e

mkdir -p runs

echo "═══ STEP 1: Validate seed chain ═══"
python3 cli.py validate chains/mortgage-mvp-seed.causal.json

echo ""
echo "═══ STEP 2: Reset to seed (clean state) ═══"
python3 cli.py reset-demo

echo ""
echo "═══ STEP 3: Forge to Python (pre-enrichment) ═══"
python3 cli.py forge chains/mortgage-mvp.causal.json --out runtime/mortgage_mvp.py
echo "  Forged → runtime/mortgage_mvp.py"

echo ""
echo "═══ STEP 4: Run simulation PRE-enrichment ═══"
python3 runtime/mortgage_mvp.py | tee runs/recommendation_pre.txt

echo ""
echo "═══ STEP 5: Enrich from Komerční banka article ═══"
python3 cli.py enrich-text chains/mortgage-mvp.causal.json \
  --text-file tests/fixtures/komercka_rate_cut_2026.txt \
  --source hn.cz

echo ""
echo "═══ STEP 6: Re-forge (post-enrichment) ═══"
python3 cli.py reforge chains/mortgage-mvp.causal.json --out runtime/mortgage_mvp.py \
  --diff-out runs/diff_post_enrichment.txt

echo ""
echo "═══ STEP 7: Run simulation POST-enrichment ═══"
python3 runtime/mortgage_mvp.py | tee runs/recommendation_post.txt

echo ""
echo "═══ STEP 8: Show what changed in recommendation ═══"
diff runs/recommendation_pre.txt runs/recommendation_post.txt \
  | tee runs/recommendation_change.txt || true   # diff exits 1 on any difference

echo ""
echo "═══ DEMO COMPLETE ═══"
echo "Artifacts:"
echo "  runs/recommendation_pre.txt   — pre-enrichment comparison"
echo "  runs/recommendation_post.txt  — post-enrichment comparison"
echo "  runs/diff_post_enrichment.txt — byte-level forge diff"
echo "  runs/recommendation_change.txt — what shifted in the table"
