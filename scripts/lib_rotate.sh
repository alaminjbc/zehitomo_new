# Shared helpers for profile-rotation experiment scripts.
# shellcheck shell=bash

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROTATE_CONFIG="${ROTATE_CONFIG:-$SCRIPTS_DIR/rotate_config.json}"

PYTHON="${PYTHON:-python}"
if [[ -x "/Users/alamin/miniconda3/envs/zehitomo/bin/python" ]]; then
  PYTHON="/Users/alamin/miniconda3/envs/zehitomo/bin/python"
fi

SERVICE="${SERVICE:-電気屋・電気工事}"
OPTIONS="${OPTIONS:-combination_creation/options.json}"
OUTPUT="${OUTPUT:-output.json}"
BATCH_MAX="${BATCH_MAX:-6}"
BATCH_SIZE="${BATCH_SIZE:-3}"
MODE="${MODE:-batch}"
CAPTCHA_EXIT=2
PROFILES=()

# Load scripts/rotate_config.json into MODE / SERVICE / PROFILES / …
load_rotate_config() {
  local config_path="${1:-$ROTATE_CONFIG}"
  if [[ ! -f "$config_path" ]]; then
    echo "Config not found: $config_path"
    exit 1
  fi

  # Python emits shell-safe KEY=value lines; shlex.quote keeps Japanese safe.
  eval "$(
    CONFIG_PATH="$config_path" "$PYTHON" - <<'PY'
import json
import os
import shlex
from pathlib import Path

path = Path(os.environ["CONFIG_PATH"])
data = json.loads(path.read_text(encoding="utf-8"))

mode = str(data.get("mode") or "batch").strip()
allowed = {"round_robin", "until_captcha", "batch"}
if mode not in allowed:
    raise SystemExit(
        f"Invalid mode {mode!r}. Use one of: {', '.join(sorted(allowed))}"
    )

profiles = [
    str(p).strip()
    for p in (data.get("profiles") or [])
    if str(p).strip()
]
if not profiles:
    raise SystemExit("rotate_config.json: profiles must be a non-empty list")

python = str(data.get("python") or "").strip()
service = str(data.get("service") or "電気屋・電気工事")
options = str(data.get("options") or "combination_creation/options.json")
output = str(data.get("output") or "output.json")
batch_max = int(data.get("batch_max") or 6)
batch_size = int(data.get("batch_size") or 3)

print(f"MODE={shlex.quote(mode)}")
print(f"SERVICE={shlex.quote(service)}")
print(f"OPTIONS={shlex.quote(options)}")
print(f"OUTPUT={shlex.quote(output)}")
print(f"BATCH_MAX={shlex.quote(str(batch_max))}")
print(f"BATCH_SIZE={shlex.quote(str(batch_size))}")
if python:
    print(f"PYTHON={shlex.quote(python)}")
print("PROFILES=(" + " ".join(shlex.quote(p) for p in profiles) + ")")
PY
  )"
}

require_profiles() {
  local missing=0
  local name
  for name in "$@"; do
    if [[ ! -d "profiles/$name" ]]; then
      echo "Missing profile: profiles/$name  (run: python login_profile.py $name)"
      missing=1
    fi
  done
  if [[ "$missing" -ne 0 ]]; then
    exit 1
  fi
}

# Print pending combination ids for SERVICE, one per line (combination1, ...).
list_pending_combos() {
  OPTIONS_FILE="$OPTIONS" SERVICE_NAME="$SERVICE" OUTPUT_FILE="$OUTPUT" \
    "$PYTHON" - <<'PY'
import json
import os
from pathlib import Path

options_path = Path(os.environ["OPTIONS_FILE"])
service = os.environ["SERVICE_NAME"]
output_path = Path(os.environ["OUTPUT_FILE"])

options = json.loads(options_path.read_text(encoding="utf-8"))
if service not in options:
    raise SystemExit(f"Service not in options.json: {service}")

combos = [
    key for key, value in options[service].items()
    if key.startswith("combination") and isinstance(value, dict)
]

done = set()
if output_path.exists() and output_path.stat().st_size:
    data = json.loads(output_path.read_text(encoding="utf-8"))
    if data.get("service") == service:
        done = set((data.get("combinations_done") or {}).keys())

for key in combos:
    if key not in done:
        print(key)
PY
}

run_combo() {
  local profile="$1"
  local combo="$2"
  echo
  echo "############################################################"
  echo "# profile=$profile  combo=$combo  service=$SERVICE"
  echo "############################################################"
  "$PYTHON" -m app.main "$profile" \
    --service "$SERVICE" \
    --combination "$combo" \
    --options "$OPTIONS" \
    --output "$OUTPUT"
}

# Bash 3.2 (macOS /bin/bash) has no mapfile/readarray.
load_pending_combos() {
  local __pending_var="$1"
  local __line
  local -a __items=()
  while IFS= read -r __line || [[ -n "$__line" ]]; do
    [[ -n "$__line" ]] && __items+=("$__line")
  done < <(list_pending_combos)
  eval "$__pending_var"'=("${__items[@]}")'
}

print_rotate_settings() {
  echo "Config   : $ROTATE_CONFIG"
  echo "Repo     : $ROOT"
  echo "Python   : $PYTHON"
  echo "Mode     : $MODE"
  echo "Profiles : ${PROFILES[*]}"
  echo "Service  : $SERVICE"
  echo "Options  : $OPTIONS"
  echo "Output   : $OUTPUT"
  echo "BATCH_MAX: $BATCH_MAX"
  echo "BATCH_SIZE: $BATCH_SIZE"
}

run_way_round_robin() {
  local -a pending=()
  load_pending_combos pending
  if [[ "${#pending[@]}" -eq 0 ]]; then
    echo "No pending combinations for $SERVICE"
    return 0
  fi

  echo "Way-1 round-robin"
  echo "Pending  : ${pending[*]}"

  local n_profiles=${#PROFILES[@]}
  local i=0
  local combo profile status
  for combo in "${pending[@]}"; do
    profile="${PROFILES[$((i % n_profiles))]}"
    set +e
    run_combo "$profile" "$combo"
    status=$?
    set -e
    if [[ "$status" -eq "$CAPTCHA_EXIT" ]]; then
      echo "Captcha on $profile during $combo — continuing with next profile/combo"
    elif [[ "$status" -ne 0 ]]; then
      echo "Failed ($status) on $profile / $combo — continuing"
    fi
    i=$((i + 1))
  done
  echo
  echo "Way-1 finished."
}

run_way_until_captcha() {
  local -a pending=()
  load_pending_combos pending
  if [[ "${#pending[@]}" -eq 0 ]]; then
    echo "No pending combinations for $SERVICE"
    return 0
  fi

  echo "Way-2 until-captcha (BATCH_MAX=$BATCH_MAX)"
  echo "Pending  : ${pending[*]}"

  local profile_index=0
  local batch_count=0
  local pending_index=0
  local profile combo status

  while [[ "$pending_index" -lt "${#pending[@]}" ]]; do
    if [[ "$profile_index" -ge "${#PROFILES[@]}" ]]; then
      echo
      echo "No profiles left (all hit captcha or BATCH_MAX). Remaining:"
      printf '  %s\n' "${pending[@]:$pending_index}"
      return 1
    fi

    profile="${PROFILES[$profile_index]}"
    combo="${pending[$pending_index]}"

    if [[ "$batch_count" -ge "$BATCH_MAX" ]]; then
      echo "BATCH_MAX=$BATCH_MAX reached on $profile — switching profile"
      profile_index=$((profile_index + 1))
      batch_count=0
      continue
    fi

    set +e
    run_combo "$profile" "$combo"
    status=$?
    set -e

    pending_index=$((pending_index + 1))
    batch_count=$((batch_count + 1))

    if [[ "$status" -eq "$CAPTCHA_EXIT" ]]; then
      echo "Captcha on $profile — switching to next profile"
      pending_index=$((pending_index - 1))
      profile_index=$((profile_index + 1))
      batch_count=0
    elif [[ "$status" -ne 0 ]]; then
      echo "Non-captcha failure ($status) on $profile / $combo — trying next combo on same profile"
    fi
  done

  echo
  echo "Way-2 finished."
}

run_way_batch() {
  local -a pending=()
  load_pending_combos pending
  if [[ "${#pending[@]}" -eq 0 ]]; then
    echo "No pending combinations for $SERVICE"
    return 0
  fi

  echo "Way-3 proactive batch (BATCH_SIZE=$BATCH_SIZE)"
  echo "Pending  : ${pending[*]}"

  local n_profiles=${#PROFILES[@]}
  local profile_index=0
  local batch_count=0
  local pending_index=0
  local wraps=0
  local profile combo status

  while [[ "$pending_index" -lt "${#pending[@]}" ]]; do
    if [[ "$wraps" -ge "$n_profiles" ]]; then
      echo
      echo "Every profile hit captcha without progress. Remaining:"
      printf '  %s\n' "${pending[@]:$pending_index}"
      return 1
    fi

    profile="${PROFILES[$profile_index]}"
    combo="${pending[$pending_index]}"

    if [[ "$batch_count" -ge "$BATCH_SIZE" ]]; then
      echo "BATCH_SIZE=$BATCH_SIZE done on $profile — rotating"
      profile_index=$(((profile_index + 1) % n_profiles))
      batch_count=0
      wraps=0
      continue
    fi

    set +e
    run_combo "$profile" "$combo"
    status=$?
    set -e

    if [[ "$status" -eq "$CAPTCHA_EXIT" ]]; then
      echo "Captcha on $profile during $combo — rotate and retry same combo"
      profile_index=$(((profile_index + 1) % n_profiles))
      batch_count=0
      wraps=$((wraps + 1))
      continue
    fi

    wraps=0
    pending_index=$((pending_index + 1))
    batch_count=$((batch_count + 1))

    if [[ "$status" -ne 0 ]]; then
      echo "Non-captcha failure ($status) on $profile / $combo — continuing"
    fi
  done

  echo
  echo "Way-3 finished."
}

dispatch_rotate_mode() {
  case "$MODE" in
    round_robin) run_way_round_robin ;;
    until_captcha) run_way_until_captcha ;;
    batch) run_way_batch ;;
    *)
      echo "Unknown mode: $MODE"
      echo "Set mode in rotate_config.json to: round_robin | until_captcha | batch"
      exit 1
      ;;
  esac
}
