"""Private panel helpers; no network, shell, credentials or registration actions."""
from datetime import datetime, timezone
import asyncio
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


COMPONENTS = {
    'mugnaio': 'Mugnaio', 'browser': 'Browser remoto',
    'risponditore': 'Risponditore', 'disco': 'Spazio sul VPS',
    'backup_creazione': 'Backup completo sul VPS',
    'backup_esportazione': 'Archivio cifrato esportato', 'backup_pc': 'Copia sul PC',
}
PROBLEMS = {
    'OK': 'regolare', 'PROCESSO_FERMO': 'processo fermo',
    'SEGNALE_ASSENTE': 'segnale assente', 'CICLO_BLOCCATO': 'ciclo non aggiornato',
    'TELEGRAM_NON_RAGGIUNTO': 'Telegram non raggiunto',
    'CODA_NON_AGGIORNATA': 'coda non aggiornata',
    'ACCESSO_NON_DISPONIBILE': 'accesso non disponibile',
    'SESSIONE_NON_RISPONDE': 'sessione non risponde',
    'SPAZIO_INSUFFICIENTE': 'spazio insufficiente',
    'COPIA_ASSENTE_O_FALLITA': 'copia assente o fallita',
    'ARCHIVIO_NON_INTEGRO': 'archivio non integro',
    'ARCHIVIO_NON_VERIFICABILE': 'archivio non verificabile',
    'COPIA_PC_OBSOLETA': 'copia sul PC non aggiornata',
    'RICEVUTA_PC_ASSENTE': 'conferma della copia PC assente',
}


def controls_text(path=Path('/run/mulino-panel/status.json'), now=None):
    try:
        if path.is_symlink():
            raise ValueError('symlink')
        with path.open('rb') as stream:
            raw = stream.read(8193)
        if len(raw) > 8192:
            raise ValueError('size')
        report = json.loads(raw)
        if set(report) != {'schema', 'checked_utc', 'codes'} or type(report['schema']) is not int or report['schema'] != 1:
            raise ValueError('schema')
        if set(report['codes']) != set(COMPONENTS) or any(c not in PROBLEMS for c in report['codes'].values()):
            raise ValueError('codes')
        checked = datetime.fromisoformat(report['checked_utc'])
        if checked.tzinfo is None:
            raise ValueError('timezone')
        now = now or datetime.now(timezone.utc)
        age = (now - checked).total_seconds()
        if age < -30:
            raise ValueError('future')
        when = checked.astimezone().strftime('%d/%m/%Y %H:%M:%S %Z')
        lines = ['🩺 Ultimo controllo del monitor: ' + when]
        if age > 360:
            lines.append('⚠️ Riepilogo vecchio: questi esiti non confermano lo stato attuale.')
        for component, label in COMPONENTS.items():
            code = report['codes'][component]
            lines.append(('✅ ' if code == 'OK' else '⚠️ ') + label + ': ' + PROBLEMS[code])
        lines.append('Il monitor aggiorna il riepilogo ogni due minuti. Questo pulsante rilegge l’ultimo controllo.')
        return '\n'.join(lines)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return '⚠️ Riepilogo dei controlli non disponibile o non valido. Non posso confermare lo stato dei servizi. Gli avvisi Healthchecks restano separati.'


class ReusablePanel:
    """Only numeric message ownership persists; views and jobs remain in memory."""
    def __init__(self, db, owner):
        self.db, self.owner = db, owner
        self.pointer = None
        self.persistence_error = False
        self.lock = asyncio.Lock()
        self.revision = 0
        self.view = 'home'
        self.backup_result = ''
        try:
            row = db.execute("SELECT value FROM runtime_settings WHERE key='admin_panel'").fetchone()
            value = json.loads(row[0]) if row else None
            if (isinstance(value, dict) and set(value) == {'owner', 'bot', 'message'}
                    and all(type(v) is int and 0 < v < 2**63 for v in value.values())
                    and value['owner'] == owner):
                self.pointer = value
        except (sqlite3.Error, ValueError, TypeError):
            self.persistence_error = True

    def message_id(self, bot):
        return self.pointer['message'] if self.pointer and self.pointer['bot'] == bot else None

    def bind(self, bot, message):
        if not all(type(v) is int and 0 < v < 2**63 for v in (self.owner, bot, message)):
            raise ValueError('Invalid panel ownership')
        self.pointer = dict(owner=self.owner, bot=bot, message=message)
        try:
            self.db.execute("INSERT INTO runtime_settings(key,value) VALUES ('admin_panel',?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(self.pointer),))
            self.persistence_error = False
        except sqlite3.Error:
            self.persistence_error = True


class PanelReply:
    """Capture existing command output for the panel; never send a new message."""
    def __init__(self):
        self.texts = []

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)


class PanelSessions:
    """Bounded, short-lived, message-bound, one-use keyboard capabilities."""
    def __init__(self):
        self.entries = {}

    def remember(self, token, chat_id, message_id, actions, payload=None):
        now = time.monotonic()
        self.entries = {t: r for t, r in self.entries.items()
                        if r['expires'] > now and (r['chat'], r['message']) != (chat_id, message_id)}
        while len(self.entries) >= 32:
            self.entries.pop(next(iter(self.entries)))
        self.entries[token] = dict(chat=chat_id, message=message_id,
                                   actions=frozenset(actions), expires=now + 900, payload=payload)

    def take(self, data, chat_id, message_id):
        if not isinstance(data, str) or not re.fullmatch(r'panel:[a-z][a-z0-9_]*:[a-f0-9]{16}', data):
            return None
        _, action, token = data.split(':')
        record = self.entries.get(token)
        if (not record or record['expires'] <= time.monotonic()
                or (record['chat'], record['message']) != (chat_id, message_id)
                or action not in record['actions']):
            return None
        self.entries.pop(token)
        return action


def keyboard(paused, view='home', *, extra_rows=()):
    token = secrets.token_hex(8)
    rows = list(extra_rows)
    if view == 'closed':
        markup = InlineKeyboardMarkup([[InlineKeyboardButton('🌾 Apri pannello', callback_data=f'panel:open:{token}')]])
        return token, {'open'}, markup
    if view == 'confirm_backup':
        rows.append([('✅ Crea copia del registro', 'backup_yes'), ('↩️ Annulla', 'backup')])
    elif view == 'backup':
        rows.append([('📋 Ultime copie del registro', 'backup_status')])
        rows.append([('💾 Crea copia del registro', 'backup_confirm')])
    rows.extend([
        [('📊 Stato', 'status'), ('▶️ Riprendi', 'resume') if paused else ('⏸ Pausa', 'pause')],
        [('🌐 Browser remoto', 'browser'), ('🩺 Controlli', 'controls')],
        [('💾 Backup', 'backup'), ('👥 Tester', 'testers')],
        [('🔄 Menu', 'home')],
        [('✖️ Chiudi', 'close')],
    ])
    actions = {action for row in rows for _, action in row}
    markup = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f'panel:{action}:{token}')
                                     for label, action in row] for row in rows])
    return token, actions, markup
