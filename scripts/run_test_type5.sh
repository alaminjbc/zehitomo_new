#!/usr/bin/env bash
# Boss block-test: 12 type_5 combos, same location (001-0010), ONE account.
#
# Usage (from repo root):
#   ./scripts/run_test_type5.sh              # uses alamin
#   ./scripts/run_test_type5.sh azimon      # override profile
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROFILE="${1:-alamin}"
OPTIONS="combination_creation/options_test_type_5.json"
OUTPUT="output_test_type_5.json"
PYTHON="${PYTHON:-python}"

if [[ ! -f "$OPTIONS" ]]; then
  echo "Building test options..."
  "$PYTHON" combination_creation/build_options_from_type5.py --test
fi

echo "Profile : $PROFILE  (one account only)"
echo "Options : $OPTIONS"
echo "Output  : $OUTPUT"
echo "Service : 民泊清掃"
echo "Goal    : same postal 001-0010, vary Q1–Q4, find block/captcha point"
echo

"$PYTHON" -m app.main "$PROFILE" \
  --service 民泊清掃 \
  --options "$OPTIONS" \
  --output "$OUTPUT"

status=$?
if [[ "$status" -eq 2 ]]; then
  echo
  echo "Captcha / block hit on profile=$PROFILE (exit 2)."
  echo "Check $OUTPUT for which combinations finished before the block."
fi
exit "$status"
