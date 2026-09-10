#!/usr/bin/env bash
set -euo pipefail

DISPLAY_NUMBER=2
VNC_PORT=5902
WEB_PORT=5000
APP_DIR="Projekte/Python/pyhart"

NOVNC_BIN="/nix/store/n7h60i6lqysmya4clas5vghfsjc6sspa-novnc-1.6.0/bin/novnc"
NOVNC_WEB="$(dirname "$(dirname "$NOVNC_BIN")")/share/webapps/novnc"
WEB_ROOT="/tmp/pyhart-novnc"

cleanup() {
  kill "${APP_PID:-}" "${VNC_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [[ -d "$WEB_ROOT" ]]; then
  chmod -R u+w "$WEB_ROOT"
  rm -rf "$WEB_ROOT"
fi
cp -R "$NOVNC_WEB" "$WEB_ROOT"
chmod -R u+w "$WEB_ROOT"
cat > "$WEB_ROOT/index.html" <<'EOF'
<!doctype html>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0; url=/vnc.html?autoconnect=true&resize=scale&path=websockify">
<title>Opening PyHART…</title>
EOF

Xvnc ":${DISPLAY_NUMBER}" \
  -rfbport="$VNC_PORT" \
  -SecurityTypes=None \
  -geometry 1024x600 \
  -localhost &
VNC_PID=$!

for _ in {1..50}; do
  if python - "$VNC_PORT" <<'PY'
import socket
import sys

with socket.socket() as sock:
    sock.settimeout(0.1)
    sys.exit(sock.connect_ex(("127.0.0.1", int(sys.argv[1]))))
PY
  then
    break
  fi
  sleep 0.1
done

(
  cd "$APP_DIR"
  DISPLAY=":${DISPLAY_NUMBER}" python main.py
) &
APP_PID=$!

exec "$NOVNC_BIN" \
  --listen "0.0.0.0:${WEB_PORT}" \
  --vnc "127.0.0.1:${VNC_PORT}" \
  --web "$WEB_ROOT" \
  --file-only