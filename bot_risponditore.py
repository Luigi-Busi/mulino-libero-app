"""
Secondo bot: risponde nel gruppo ai messaggi "Nuova registrazione Libero"
inviati dal primo bot, con: GG/MM/AAAA | M/F | Città (PR)

Requisiti:
    pip install python-telegram-bot

Variabili d'ambiente:
    BOT_TOKEN  = token del SECONDO bot (da BotFather)
    GRUPPO_ID  = id del gruppo (opzionale; se assente risponde in qualsiasi gruppo)

Per scoprire l'id del gruppo: avvia il bot, scrivi /chatid nel gruppo.
"""

import logging
import os
import random
import re
from collections import deque
from datetime import date, timedelta

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# ================== CONFIGURAZIONE ==================
TOKEN = os.environ["BOT_TOKEN"]
GRUPPO_ID = int(os.environ.get("GRUPPO_ID", "0"))   # 0 = qualsiasi gruppo
BOT_A_USERNAME = 'Il_Mugnaio_Bot'
TESTO_CHIAVE = "Nuova registrazione Libero"
# ====================================================

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("risponditore")

MASCHILI_IN_A = {
    "andrea", "luca", "nicola", "mattia", "elia", "enea", "tobia",
    "gianluca", "battista", "giona", "zaccaria", "geremia", "isaia",
    "evangelista", "leonida",
}

FEMMINILI_NON_A = {
    "beatrice", "adele", "irene", "alice", "agnese", "rachele", "ester",
    "noemi", "miriam", "carmen", "ines", "matilde", "nicole", "michelle",
    "desiree", "cloe", "chloe", "zoe", "marie", "denise", "consuelo",
    "rosy", "jenny", "sharon", "karin", "ingrid", "doris", "iris",
}

CITTA = [
    "Pompei (NA)", "Torre del Greco (NA)", "Pozzuoli (NA)", "Caserta (CE)",
    "Aversa (CE)", "Salerno (SA)", "Battipaglia (SA)", "Avellino (AV)",
    "Benevento (BN)", "Roma (RM)", "Latina (LT)", "Frosinone (FR)",
    "Viterbo (VT)", "Milano (MI)", "Monza (MB)", "Bergamo (BG)",
    "Brescia (BS)", "Como (CO)", "Torino (TO)", "Novara (NO)",
    "Genova (GE)", "La Spezia (SP)", "Bologna (BO)", "Modena (MO)",
    "Parma (PR)", "Rimini (RN)", "Firenze (FI)", "Prato (PO)",
    "Pisa (PI)", "Livorno (LI)", "Perugia (PG)", "Terni (TR)",
    "Ancona (AN)", "Pescara (PE)", "Chieti (CH)", "L'Aquila (AQ)",
    "Campobasso (CB)", "Bari (BA)", "Lecce (LE)", "Taranto (TA)",
    "Foggia (FG)", "Potenza (PZ)", "Matera (MT)", "Cosenza (CS)",
    "Catanzaro (CZ)", "Reggio Calabria (RC)", "Palermo (PA)",
    "Catania (CT)", "Messina (ME)", "Siracusa (SR)", "Cagliari (CA)",
    "Sassari (SS)", "Venezia (VE)", "Padova (PD)", "Verona (VR)",
    "Vicenza (VI)", "Treviso (TV)", "Trieste (TS)", "Udine (UD)",
    "Trento (TN)", "Bolzano (BZ)",
]

# Anti-loop / anti-duplicati: ricorda gli ultimi messaggi a cui ha già risposto
gia_risposti = deque(maxlen=1000)


def _sposta_anni(d: date, anni: int) -> date:
    try:
        return d.replace(year=d.year - anni)
    except ValueError:  # 29 febbraio
        return d.replace(year=d.year - anni, day=28)


def data_casuale() -> str:
    """Data tra 60 anni fa e (20 anni fa - 1 giorno), formato GG/MM/AAAA."""
    oggi = date.today()
    minima = _sposta_anni(oggi, 60)
    massima = _sposta_anni(oggi, 20) - timedelta(days=1)
    d = minima + timedelta(days=random.randint(0, (massima - minima).days))
    return d.strftime("%d/%m/%Y")


def sesso_da_nome(nome_completo: str) -> str:
    """M/F dal primo nome; se non determinabile restituisce M."""
    parti = nome_completo.strip().split()
    if not parti:
        return "M"
    nome = parti[0].lower().strip(".,;:")
    if nome in MASCHILI_IN_A:
        return "M"
    if nome in FEMMINILI_NON_A or nome.endswith("a"):
        return "F"
    return "M"


def estrai_nome(testo: str) -> str:
    m = re.search(r"Nome presente nel foglio:\s*(.+)", testo)
    return m.group(1).strip() if m else ""


async def gestisci(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg or not msg.text:
        return
    if GRUPPO_ID and msg.chat_id != GRUPPO_ID:
        return
    if TESTO_CHIAVE not in msg.text:
        return

    chiave = (msg.chat_id, msg.message_id)
    if chiave in gia_risposti:
        return
    gia_risposti.append(chiave)

    nome = estrai_nome(msg.text)
    risposta = f"{data_casuale()} | {sesso_da_nome(nome)} | {random.choice(CITTA)}"
    await msg.reply_text(risposta)  # risposta diretta: il primo bot la riceve
    log.info("[OK] %s -> %s", nome or "(nome non trovato)", risposta)


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(f"Chat ID: {update.effective_chat.id}")


def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("chatid", chatid))
    app.add_handler(
        MessageHandler(filters.TEXT & filters.User(username=BOT_A_USERNAME), gestisci)
    )
    log.info("Bot avviato, in ascolto...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
