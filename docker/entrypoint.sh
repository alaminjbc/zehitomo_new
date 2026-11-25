#!/bin/bash
# Virtual display for headed Chrome, then run the given command.
set -euo pipefail

echo "[entrypoint] starting Xvfb on :99 ..."
Xvfb :99 -screen 0 1440x900x24 -ac +extension GLX +render -noreset \
  >/tmp/xvfb.log 2>&1 &
export DISPLAY=:99
sleep 1
echo "[entrypoint] DISPLAY=$DISPLAY — running: $*"
exec "$@"
