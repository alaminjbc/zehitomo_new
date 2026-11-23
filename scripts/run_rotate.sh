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
  mode           : round_robin | until_captcha | batch
  profiles       : ["alamin", "azimon", ...]
  service        : service name in options file
  options        : path to options.json / options_type_5.json
  output         : path to output.json
  sheet          : path to zehitomo_main.csv
  profile_status : path to profile_status.json
  batch_max      : way-2 max combos per profile before switch
  batch_size     : way-3 combos per profile before rotate

Missing path keys keep app/config.py defaults.
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
