#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

if [[ -n "${VNC_PASSWORD_FILE:-}" ]]; then
  MULINO_VNC_PASSWORD="$(< "$VNC_PASSWORD_FILE")"
else
  MULINO_VNC_PASSWORD="${VNC_PASSWORD:-}"
fi

if [[ -z "$MULINO_VNC_PASSWORD" || ${#MULINO_VNC_PASSWORD} -gt 8 ]]; then
  echo "Password VNC mancante o superiore al limite di 8 caratteri" >&2
  exit 1
fi

mkdir -p /data

x11vnc -storepasswd "$MULINO_VNC_PASSWORD" /tmp/mulino-vnc.pass >/dev/null 2>&1
unset MULINO_VNC_PASSWORD
chmod 0600 /tmp/mulino-vnc.pass

mulino_children=()
cleanup() {
  trap - EXIT TERM INT
  for mulino_pid in "${mulino_children[@]}"; do
    kill -TERM "$mulino_pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

Xvfb :99 -screen 0 1365x900x24 -nolisten tcp &
mulino_children+=("$!")

mulino_display_ready=false
for ((mulino_try=0; mulino_try<50; mulino_try++)); do
  if xdpyinfo -display :99 >/dev/null 2>&1; then
    mulino_display_ready=true
    break
  fi
  sleep 0.1
done
if [[ "$mulino_display_ready" != true ]]; then
  echo "Il display del browser non si e avviato" >&2
  exit 1
fi

x11vnc \
  -display :99 \
  -forever \
  -shared \
  -localhost \
  -rfbport 5900 \
  -rfbauth /tmp/mulino-vnc.pass \
  -noxdamage \
  -o /data/x11vnc.log &
mulino_children+=("$!")

websockify \
  --web=/usr/share/novnc/ \
  6080 \
  localhost:5900 &
mulino_children+=("$!")

python /app/libero_mail_bot.py &
mulino_children+=("$!")

# Riavvia l'intero servizio se uno dei componenti termina.
wait -n "${mulino_children[@]}"
