#!/usr/bin/env bash
# Run profile rotation using settings from scripts/rotate_config.json.
#
# Edit the JSON, then:
#   ./scripts/run_rotate.sh
#
# Optional:
#   ./scripts/run_rotate.sh /path/to/other_config.json
#   MODE=round_robin ./scripts/run_rotate.sh   # overrides JSON mode for one run

set -euo pipefail

# Capture before sourcing lib (lib sets MODE default).
OVERRIDE_MODE="${MODE-__UNSET__}"

source "$(cd "$(dirname "$0")" && pwd)/lib_rotate.sh"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage: ./scripts/run_rotate.sh [config.json]

Edit scripts/rotate_config.json:
  mode      : round_robin | until_captcha | batch
  profiles  : ["alamin", "azimon", ...]
  service   : service name in options.json
  options   : path to options.json
  output    : path to output.json
  batch_max : way-2 max combos per profile before switch
  batch_size: way-3 combos per profile before rotate
EOF
  exit 0
fi

if [[ $# -ge 1 ]]; then
  ROTATE_CONFIG="$1"
fi

load_rotate_config "$ROTATE_CONFIG"
# MODE=round_robin ./scripts/run_rotate.sh overrides JSON for one run.
if [[ "$OVERRIDE_MODE" != "__UNSET__" ]]; then
  MODE="$OVERRIDE_MODE"
fi

require_profiles "${PROFILES[@]}"
print_rotate_settings
echo
dispatch_rotate_mode
