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
declare -A mulino_components=()
mulino_watchdog_pid=
diagnostic() {
  printf 'MULINO_DIAG {"schema":1,"source":"launcher","event":"%s","component":"%s","exit_code":%s,"signal":%s,"expected":%s}\n' "$1" "$2" "$3" "$4" "$5"
}
cleanup() {
  trap - EXIT TERM INT
  diagnostic cleanup_start service 0 0 true
  if [[ -n "$mulino_watchdog_pid" ]]; then
    kill -TERM "$mulino_watchdog_pid" 2>/dev/null || true
  fi
  for mulino_pid in "${mulino_children[@]}"; do
    kill -TERM "$mulino_pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'diagnostic signal service 143 15 true; exit 143' TERM
trap 'diagnostic signal service 130 2 true; exit 130' INT

Xvfb :99 -screen 0 1365x900x24 -nolisten tcp &
mulino_children+=("$!")
mulino_components["$!"]=display

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
  diagnostic display_failed display 1 0 false
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
mulino_components["$!"]=vnc

websockify \
  --web=/usr/share/novnc/ \
  6080 \
  localhost:5900 &
mulino_children+=("$!")
mulino_components["$!"]=websocket

python /app/libero_mail_bot.py &
mulino_children+=("$!")
mulino_components["$!"]=bot

# Anche un componente gia terminato durante l'avvio deve essere rilevato:
# wait -n da solo puo ignorare un job gia concluso. Il timer chiude quella
# finestra senza cambiare il comportamento di arresto del servizio.
finish_component() {
  diagnostic component_exit "${mulino_components[$1]:-unknown}" "$2" 0 false
  exit "$2"
}
while true; do
  for mulino_pid in "${mulino_children[@]}"; do
    if ! kill -0 "$mulino_pid" 2>/dev/null; then
      if wait "$mulino_pid"; then mulino_exit_code=0; else mulino_exit_code=$?; fi
      finish_component "$mulino_pid" "$mulino_exit_code"
    fi
  done
  sleep 1 &
  mulino_watchdog_pid=$!
  if wait -n -p mulino_exited "${mulino_children[@]}" "$mulino_watchdog_pid" 2>/dev/null; then
    mulino_exit_code=0
  else
    mulino_exit_code=$?
  fi
  if [[ "${mulino_exited:-}" != "$mulino_watchdog_pid" && -n "${mulino_exited:-}" ]]; then
    finish_component "$mulino_exited" "$mulino_exit_code"
  fi
  wait "$mulino_watchdog_pid" 2>/dev/null || true
  mulino_watchdog_pid=
done
