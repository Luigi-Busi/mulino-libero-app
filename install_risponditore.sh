#!/usr/bin/env bash
# Installa o aggiorna il secondo bot (bot_risponditore.py) come servizio systemd.
#
# Prima volta:
#   BOT_TOKEN=xxx GRUPPO_ID=0 bash install_risponditore.sh
# Volte successive (aggiornamento dello script):
#   bash install_risponditore.sh
# Per cambiare token o gruppo, rilancialo passando di nuovo BOT_TOKEN e GRUPPO_ID.

set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVIZIO="bot-risponditore"
SCRIPT="$APP_DIR/bot_risponditore.py"
VENV="$APP_DIR/.venv-risponditore"
ENV_FILE="$APP_DIR/bot_risponditore.env"
UNIT="/etc/systemd/system/$SERVIZIO.service"

echo "==> Cartella: $APP_DIR"

if [ ! -f "$SCRIPT" ]; then
  echo "ERRORE: non trovo $SCRIPT"
  exit 1
fi

# --- File con token e id gruppo ---
if [ -n "${BOT_TOKEN:-}" ]; then
  echo "==> Salvo token e id gruppo in $ENV_FILE"
  {
    echo "BOT_TOKEN=$BOT_TOKEN"
    echo "GRUPPO_ID=${GRUPPO_ID:-0}"
    echo "PYTHONUNBUFFERED=1"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "ERRORE: prima installazione, manca il token."
  echo "Rilancia cosi':  BOT_TOKEN=il_tuo_token GRUPPO_ID=0 bash install_risponditore.sh"
  exit 1
fi

# --- Ambiente Python ---
if [ ! -x "$VENV/bin/python" ]; then
  echo "==> Creo l'ambiente Python"
  if ! python3 -m venv "$VENV" 2>/dev/null; then
    rm -rf "$VENV"
    apt-get update -qq
    apt-get install -y -qq python3-venv
    python3 -m venv "$VENV"
  fi
fi

echo "==> Installo/aggiorno python-telegram-bot"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q --upgrade python-telegram-bot

# --- Servizio systemd ---
echo "==> Scrivo il servizio $SERVIZIO"
cat > "$UNIT" <<EOF
[Unit]
Description=Secondo bot Telegram risponditore
After=network-online.target
Wants=network-online.target

[Service]
User=root
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$VENV/bin/python $SCRIPT
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVIZIO" >/dev/null 2>&1
systemctl restart "$SERVIZIO"

sleep 3
echo
systemctl --no-pager --lines=10 status "$SERVIZIO" || true
echo
echo "==> Fatto. Log in tempo reale:  journalctl -u $SERVIZIO -f"
