"""Observe delivered private messages; retain IDs and dates only, never content."""
import logging
import sqlite3

from telegram.ext import ExtBot

LOGGER = logging.getLogger('mulino-admin-cleanup')
NOTICE_PREFIXES = (
    '⌛ Libero segnala attività anomala.',
    '🙈 Richiesta nascosta dal recupero.',
    'ℹ️ Esiste già una richiesta per questo nominativo.',
    '❌ Username mancante o non valido nella coda:',
    '⚠️ Esito della registrazione Libero da verificare',
    'Usa /creamail Nome | Cognome.',
)


def observe_message(cleanup, bot_id, message, *, outgoing=False):
    if (cleanup is None or message is None
            or getattr(getattr(message, 'chat', None), 'id', None) != cleanup.owner
            or getattr(message.chat, 'type', None) != 'private'
            or getattr(getattr(message, 'from_user', None), 'id', None)
                != (bot_id if outgoing else cleanup.owner)):
        return
    try:
        date = message.date
        if date.tzinfo is None:
            return
        stamp = int(date.timestamp())
        cleanup.observe_message(bot_id, message.message_id, stamp)
        if outgoing and (getattr(message, 'text', '') or '').startswith(NOTICE_PREFIXES):
            cleanup.track_registration_notice(bot_id, message.message_id, stamp)
    except (sqlite3.Error, ValueError, AttributeError, TypeError):
        LOGGER.warning('Messaggio consegnato; metadati di pulizia non registrati')


class CleanupBot(ExtBot):
    __slots__ = ('_admin_cleanup',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        object.__setattr__(self, '_admin_cleanup', None)

    def attach_cleanup(self, cleanup):
        object.__setattr__(self, '_admin_cleanup', cleanup)

    async def send_message(self, *args, **kwargs):
        sent = await super().send_message(*args, **kwargs)
        if self._admin_cleanup is not None:
            observe_message(self._admin_cleanup, self.id, sent, outgoing=True)
        return sent


async def observe_incoming(update, context):
    coordinator = context.application.bot_data['coordinator']
    # New messages only: edits and callback button presses must not count twice.
    observe_message(coordinator.panel.cleanup, coordinator.bot.id, update.message)
    await coordinator.panel.cleanup.drain(coordinator.bot,
        lambda: coordinator.panel.message_id(coordinator.bot.id))
