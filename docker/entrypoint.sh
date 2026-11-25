#!/bin/bash
# Virtual display for headed Chrome, then run the given command.
# VNC=1 also starts x11vnc on :5900 so you can see/log in to Chrome
# (compose publishes it on the host's 127.0.0.1 only — use an SSH tunnel).
set -euo pipefail

echo "[entrypoint] starting Xvfb on :99 ..."
Xvfb :99 -screen 0 1440x900x24 -ac +extension GLX +render -noreset \
  >/tmp/xvfb.log 2>&1 &
export DISPLAY=:99
sleep 1

if [[ "${VNC:-0}" == "1" ]]; then
  vnc_auth=(-nopw)
  if [[ -n "${VNC_PASSWORD:-}" ]]; then
    x11vnc -storepasswd "$VNC_PASSWORD" /tmp/vncpass >/dev/null 2>&1
    vnc_auth=(-rfbauth /tmp/vncpass)
  fi
  echo "[entrypoint] starting x11vnc on :5900 (display $DISPLAY) ..."
  x11vnc -display "$DISPLAY" -forever -shared -rfbport 5900 "${vnc_auth[@]}" \
    >/tmp/x11vnc.log 2>&1 &
fi

echo "[entrypoint] DISPLAY=$DISPLAY — running: $*"
exec "$@"
