"""Private panel helpers; no network, shell, credentials or registration actions."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
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


class PanelSessions:
    """Bounded, short-lived, message-bound, one-use keyboard capabilities."""
    def __init__(self):
        self.entries = {}

    def remember(self, token, chat_id, message_id, actions):
        now = time.monotonic()
        self.entries = {t: r for t, r in self.entries.items()
                        if r['expires'] > now and (r['chat'], r['message']) != (chat_id, message_id)}
        while len(self.entries) >= 32:
            self.entries.pop(next(iter(self.entries)))
        self.entries[token] = dict(chat=chat_id, message=message_id,
                                   actions=frozenset(actions), expires=now + 900)

    def take(self, data, chat_id, message_id):
        if not isinstance(data, str) or not re.fullmatch(r'panel:[a-z_]+:[a-f0-9]{16}', data):
            return None
        _, action, token = data.split(':')
        record = self.entries.get(token)
        if (not record or record['expires'] <= time.monotonic()
                or (record['chat'], record['message']) != (chat_id, message_id)
                or action not in record['actions']):
            return None
        self.entries.pop(token)
        return action


def keyboard(paused, view='home'):
    token = secrets.token_hex(8)
    rows = []
    if view == 'confirm_backup':
        rows.append([('✅ Crea copia del registro', 'backup_yes'), ('↩️ Annulla', 'backup')])
    elif view == 'backup':
        rows.append([('📋 Ultime copie del registro', 'backup_status')])
        rows.append([('💾 Crea copia del registro', 'backup_confirm')])
    rows.extend([
        [('📊 Stato', 'status'), ('▶️ Riprendi', 'resume') if paused else ('⏸ Pausa', 'pause')],
        [('🌐 Browser remoto', 'browser'), ('🩺 Controlli', 'controls')],
        [('💾 Backup', 'backup'), ('🔄 Menu', 'home')],
    ])
    actions = {action for row in rows for _, action in row}
    markup = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f'panel:{action}:{token}')
                                     for label, action in row] for row in rows])
    return token, actions, markup
