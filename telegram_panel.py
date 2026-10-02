"""Private panel helpers; no network, shell, credentials or registration actions."""
from datetime import datetime, timezone
import asyncio
from contextlib import suppress
import logging
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


LOGGER = logging.getLogger('mulino-admin-cleanup')


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


class AdminChatCleanup:
    """Only explicitly observed owner commands and retired panel IDs; no history scan."""
    def __init__(self, db, owner):
        self.db, self.owner = db, owner
        db.execute("""CREATE TABLE IF NOT EXISTS admin_chat_cleanup (
            owner INTEGER NOT NULL, bot INTEGER NOT NULL, message INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('panel','command')),
            PRIMARY KEY(owner,bot,message))""")
        db.execute("""CREATE TABLE IF NOT EXISTS admin_response_history (
            owner INTEGER NOT NULL, bot INTEGER NOT NULL, message INTEGER NOT NULL,
            category TEXT NOT NULL CHECK(category='queue'),
            sent_at INTEGER NOT NULL CHECK(sent_at>0),
            PRIMARY KEY(owner,bot,message))""")
        self.lock = asyncio.Lock()
        self.retry_at = 0.0

    @staticmethod
    def valid_id(value):
        return type(value) is int and 0 < value < 2**63

    def enqueue(self, bot, message, kind):
        if (not all(self.valid_id(v) for v in (self.owner, bot, message))
                or kind not in ('panel', 'command')):
            raise ValueError('Invalid cleanup target')
        self.db.execute('INSERT OR IGNORE INTO admin_chat_cleanup VALUES (?,?,?,?)',
                        (self.owner, bot, message, kind))

    def track_response(self, bot, message, sent_at):
        """Record only a successfully delivered routine queue response, never its text."""
        if (not all(self.valid_id(v) for v in (self.owner, bot, message))
                or type(sent_at) is not int or not 0 < sent_at <= time.time() + 60):
            raise ValueError('Invalid response metadata')
        self.db.execute('INSERT OR IGNORE INTO admin_response_history VALUES (?,?,?,?,?)',
                        (self.owner, bot, message, 'queue', sent_at))

    async def delete_known(self, bot, message):
        """True means removed or permanently unavailable; False keeps the durable job."""
        try:
            deleted = await bot.delete_message(chat_id=self.owner, message_id=message,
                read_timeout=3, write_timeout=3, connect_timeout=3)
            if deleted is not True:
                raise RuntimeError('Deletion unconfirmed')
        except RetryAfter as exc:
            delay = exc.retry_after
            seconds = delay.total_seconds() if hasattr(delay, 'total_seconds') else float(delay)
            self.retry_at = time.monotonic() + seconds + 1
            return False
        except Forbidden:
            LOGGER.warning('Pulizia amministrativa non consentita da Telegram')
        except BadRequest as exc:
            if not any(reason in str(exc).lower() for reason in (
                    'message to delete not found', "message can't be deleted", 'message_id_invalid')):
                self.retry_at = time.monotonic() + 60
                LOGGER.warning('Pulizia amministrativa rinviata per risposta Telegram inattesa')
                return False
            LOGGER.warning('Messaggio amministrativo assente o non eliminabile')
        except (TelegramError, RuntimeError):
            self.retry_at = time.monotonic() + 10
            LOGGER.warning('Pulizia amministrativa rinviata per connessione non disponibile')
            return False
        return True

    async def drain(self, bot, current_message):
        async with self.lock:
            if time.monotonic() < self.retry_at:
                return
            try:
                rows = self.db.execute('SELECT message FROM admin_chat_cleanup WHERE owner=? AND bot=? ORDER BY message LIMIT 8',
                                       (self.owner, bot.id)).fetchall()
                for (message,) in rows:
                    current = current_message() if callable(current_message) else current_message
                    if not self.valid_id(message) or message == current:
                        # A restored pointer can make an old deletion job current again.
                        self.db.execute('DELETE FROM admin_chat_cleanup WHERE owner=? AND bot=? AND message=?',
                                        (self.owner, bot.id, message))
                        continue
                    if not await self.delete_known(bot, message):
                        return
                    self.db.execute('DELETE FROM admin_chat_cleanup WHERE owner=? AND bot=? AND message=?',
                                    (self.owner, bot.id, message))
                # No command is needed: the existing coordinator loop calls drain while paused too.
                # Telegram IDs are increasing within this private chat, including concurrent sends.
                now = int(time.time())
                rows = self.db.execute('''SELECT message,sent_at FROM admin_response_history
                    WHERE owner=? AND bot=? AND category='queue' AND sent_at<=?
                    AND message < (SELECT MAX(message) FROM admin_response_history
                        WHERE owner=? AND bot=? AND category='queue')
                    ORDER BY sent_at,message LIMIT 8''',
                    (self.owner,bot.id,now-86400,self.owner,bot.id)).fetchall()
                for message, sent_at in rows:
                    current = current_message() if callable(current_message) else current_message
                    latest = self.db.execute('''SELECT MAX(message) FROM admin_response_history
                        WHERE owner=? AND bot=? AND category='queue' ''',(self.owner,bot.id)).fetchone()[0]
                    if message == latest:
                        continue
                    if (self.valid_id(message) and message != current
                            and now - 172800 < sent_at <= now - 86400):
                        if not await self.delete_known(bot, message):
                            return
                    # Expired metadata cannot be used to delete Telegram history older than 48h.
                    # A restored current-panel pointer is protected even if it was tracked wrongly.
                    self.db.execute('DELETE FROM admin_response_history WHERE owner=? AND bot=? AND message=?',
                                    (self.owner,bot.id,message))
            except sqlite3.Error:
                self.retry_at = time.monotonic() + 10
                LOGGER.warning('Registro della pulizia amministrativa non disponibile')


class ReusablePanel:
    """Only numeric message ownership persists; views and jobs remain in memory."""
    def __init__(self, db, owner):
        self.db, self.owner = db, owner
        self.cleanup = AdminChatCleanup(db, owner)
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

    def bind(self, bot, message, *, retired_message=None):
        if not all(type(v) is int and 0 < v < 2**63 for v in (self.owner, bot, message)):
            raise ValueError('Invalid panel ownership')
        self.pointer = dict(owner=self.owner, bot=bot, message=message)
        transaction = False
        try:
            self.db.execute('SAVEPOINT panel_replacement')
            transaction = True
            self.db.execute("INSERT INTO runtime_settings(key,value) VALUES ('admin_panel',?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(self.pointer),))
            if retired_message is not None and retired_message != message:
                self.cleanup.enqueue(bot, retired_message, 'panel')
            self.db.execute('RELEASE panel_replacement')
            self.persistence_error = False
        except sqlite3.Error:
            if transaction:
                with suppress(sqlite3.Error):
                    self.db.execute('ROLLBACK TO panel_replacement')
                    self.db.execute('RELEASE panel_replacement')
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
