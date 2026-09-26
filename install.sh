#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ "$PWD" != /opt/mulino-libero/app ]]; then
  echo "Estrai il pacchetto in /opt/mulino-libero/app e ripeti da quella cartella." >&2
  exit 1
fi

for mulino_file in \
  ../.env \
  ../secrets/google-service-account.json \
  ../secrets/telegram-bot-token \
  ../secrets/libero-password; do
  if [[ ! -s "$mulino_file" ]]; then
    printf 'File mancante o vuoto: %s\n' "$mulino_file" >&2
    exit 1
  fi
  chmod 600 "$mulino_file"
done
chmod 700 ../secrets
mkdir -p ../data

if [[ ! -s ../secrets/vnc-password ]]; then
  python3 -c 'import secrets,string; print("".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8)), end="")' > ../secrets/vnc-password
fi
chmod 600 ../secrets/vnc-password

docker compose --env-file ../.env config --quiet
docker compose --env-file ../.env build
docker compose --env-file ../.env run --rm --no-deps --entrypoint python libero-mail-bot /app/libero_mail_bot.py --check
docker compose --env-file ../.env up -d
docker compose --env-file ../.env ps
echo "Installazione completata. Apri @Il_Mugnaio_Bot in privato e invia /start."
