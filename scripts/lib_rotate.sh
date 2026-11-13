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

# Print eligible profile names (not on captcha cooldown), one per line.
# Candidates come from the PROFILES bash array.
list_eligible_profiles() {
  CANDIDATE_PROFILES="${PROFILES[*]}" "$PYTHON" - <<'PY'
import os
import sys
from pathlib import Path

# Repo root is cwd (lib_rotate cds there).
sys.path.insert(0, str(Path.cwd()))
from app.services.profile_status import list_eligible

candidates = [p for p in os.environ.get("CANDIDATE_PROFILES", "").split() if p]
for name in list_eligible(candidates):
    print(name)
PY
}

print_cooldown_summary() {
  CANDIDATE_PROFILES="${PROFILES[*]}" "$PYTHON" - <<'PY'
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from app.services.profile_status import cooldown_summary

candidates = [p for p in os.environ.get("CANDIDATE_PROFILES", "").split() if p]
print(cooldown_summary(candidates))
PY
}

# Load currently eligible profiles into the named bash array (quiet).
read_eligible_profiles() {
  local __eligible_var="$1"
  local __line
  local -a __items=()
  while IFS= read -r __line || [[ -n "$__line" ]]; do
    [[ -n "$__line" ]] && __items+=("$__line")
  done < <(list_eligible_profiles)
  eval "$__eligible_var"'=("${__items[@]}")'
}

# Load eligible profiles; return 1 with a summary when none remain.
load_eligible_profiles() {
  local __eligible_var="$1"
  read_eligible_profiles "$__eligible_var"
  local __count
  eval "__count=\${#$__eligible_var[@]}"
  if [[ "$__count" -eq 0 ]]; then
    echo "No eligible profiles — all are on captcha cooldown:"
    print_cooldown_summary
    return 1
  fi
  return 0
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
    # New multi-service shape: services.<name>.combinations_done
    services = data.get("services")
    if isinstance(services, dict) and service in services:
        block = services.get(service) or {}
        done = set((block.get("combinations_done") or {}).keys())
    # Legacy single-service shape
    elif data.get("service") == service:
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
  local -a eligible=()
  read_eligible_profiles eligible
  echo "Config   : $ROTATE_CONFIG"
  echo "Repo     : $ROOT"
  echo "Python   : $PYTHON"
  echo "Mode     : $MODE"
  echo "Profiles : ${PROFILES[*]}"
  if [[ "${#eligible[@]}" -gt 0 ]]; then
    echo "Eligible : ${eligible[*]}"
  else
    echo "Eligible : (none — all on cooldown)"
  fi
  echo "Status   : scripts/profile_status.json"
  echo "Service  : $SERVICE"
  echo "Options  : $OPTIONS"
  echo "Output   : $OUTPUT"
  echo "BATCH_MAX: $BATCH_MAX"
  echo "BATCH_SIZE: $BATCH_SIZE"
}

run_way_round_robin() {
  local -a pending=()
  local -a eligible=()
  load_pending_combos pending
  if [[ "${#pending[@]}" -eq 0 ]]; then
    echo "No pending combinations for $SERVICE"
    return 0
  fi
  load_eligible_profiles eligible || return 1

  echo "Way-1 round-robin (on captcha: retry same combo with next eligible profile)"
  echo "Pending  : ${pending[*]}"
  echo "Eligible : ${eligible[*]}"

  local n_profiles=${#eligible[@]}
  local profile_index=0
  local pending_index=0
  local wraps=0
  local combo profile status

  while [[ "$pending_index" -lt "${#pending[@]}" ]]; do
    n_profiles=${#eligible[@]}
    if [[ "$n_profiles" -eq 0 ]]; then
      echo
      echo "No eligible profiles left (captcha cooldown). Remaining:"
      printf '  %s\n' "${pending[@]:$pending_index}"
      print_cooldown_summary
      return 1
    fi
    if [[ "$wraps" -ge "$n_profiles" ]]; then
      echo
      echo "Every eligible profile hit captcha on ${pending[$pending_index]}. Remaining:"
      printf '  %s\n' "${pending[@]:$pending_index}"
      print_cooldown_summary
      return 1
    fi

    combo="${pending[$pending_index]}"
    profile="${eligible[$((profile_index % n_profiles))]}"

    set +e
    run_combo "$profile" "$combo"
    status=$?
    set -e

    if [[ "$status" -eq "$CAPTCHA_EXIT" ]]; then
      echo "Captcha on $profile during $combo — refresh eligible and retry same combo"
      local before=${#eligible[@]}
      load_eligible_profiles eligible || return 1
      profile_index=0
      if [[ "${#eligible[@]}" -lt "$before" ]]; then
        wraps=0
      else
        wraps=$((wraps + 1))
      fi
      continue
    fi

    wraps=0
    pending_index=$((pending_index + 1))
    profile_index=$((profile_index + 1))

    if [[ "$status" -ne 0 ]]; then
      echo "Failed ($status) on $profile / $combo — moving to next combo"
    fi
  done

  echo
  echo "Way-1 finished."
}

run_way_until_captcha() {
  local -a pending=()
  local -a eligible=()
  load_pending_combos pending
  if [[ "${#pending[@]}" -eq 0 ]]; then
    echo "No pending combinations for $SERVICE"
    return 0
  fi
  load_eligible_profiles eligible || return 1

  echo "Way-2 until-captcha (BATCH_MAX=$BATCH_MAX)"
  echo "Pending  : ${pending[*]}"
  echo "Eligible : ${eligible[*]}"

  local profile_index=0
  local batch_count=0
  local pending_index=0
  local profile combo status

  while [[ "$pending_index" -lt "${#pending[@]}" ]]; do
    if [[ "$profile_index" -ge "${#eligible[@]}" ]]; then
      echo
      echo "No eligible profiles left (all hit captcha or BATCH_MAX). Remaining:"
      printf '  %s\n' "${pending[@]:$pending_index}"
      print_cooldown_summary
      return 1
    fi

    profile="${eligible[$profile_index]}"
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
      echo "Captcha on $profile — refresh eligible and switch profile"
      pending_index=$((pending_index - 1))
      load_eligible_profiles eligible || return 1
      # Stay at same index: cooled profile dropped, next candidate shifts here.
      if [[ "$profile_index" -ge "${#eligible[@]}" ]]; then
        profile_index=${#eligible[@]}
      fi
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
  local -a eligible=()
  load_pending_combos pending
  if [[ "${#pending[@]}" -eq 0 ]]; then
    echo "No pending combinations for $SERVICE"
    return 0
  fi
  load_eligible_profiles eligible || return 1

  echo "Way-3 proactive batch (BATCH_SIZE=$BATCH_SIZE)"
  echo "Pending  : ${pending[*]}"
  echo "Eligible : ${eligible[*]}"

  local n_profiles=${#eligible[@]}
  local profile_index=0
  local batch_count=0
  local pending_index=0
  local wraps=0
  local profile combo status

  while [[ "$pending_index" -lt "${#pending[@]}" ]]; do
    n_profiles=${#eligible[@]}
    if [[ "$n_profiles" -eq 0 ]]; then
      echo
      echo "No eligible profiles left (captcha cooldown). Remaining:"
      printf '  %s\n' "${pending[@]:$pending_index}"
      print_cooldown_summary
      return 1
    fi
    if [[ "$wraps" -ge "$n_profiles" ]]; then
      echo
      echo "Every eligible profile hit captcha without progress. Remaining:"
      printf '  %s\n' "${pending[@]:$pending_index}"
      print_cooldown_summary
      return 1
    fi

    if [[ "$profile_index" -ge "$n_profiles" ]]; then
      profile_index=0
    fi
    profile="${eligible[$profile_index]}"
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
      echo "Captcha on $profile during $combo — refresh eligible and retry same combo"
      local before=${#eligible[@]}
      load_eligible_profiles eligible || return 1
      profile_index=0
      batch_count=0
      if [[ "${#eligible[@]}" -lt "$before" ]]; then
        wraps=0
      else
        wraps=$((wraps + 1))
      fi
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
