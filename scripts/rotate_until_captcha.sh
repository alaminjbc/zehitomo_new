#!/usr/bin/env bash
# Way-2 wrapper. Prefer editing scripts/rotate_config.json and running:
#   ./scripts/run_rotate.sh
# Or force this mode:
#   MODE=until_captcha ./scripts/run_rotate.sh

set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/lib_rotate.sh"

load_rotate_config "$ROTATE_CONFIG"
MODE=until_captcha
if [[ $# -ge 1 ]]; then
  PROFILES=("$@")
fi
require_profiles "${PROFILES[@]}"
print_rotate_settings
echo
run_way_until_captcha
