import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from test_regressions import worker
from telegram_panel import COMPONENTS, PanelSessions, controls_text


class PanelTests(unittest.IsolatedAsyncioTestCase):
    def setup_panel(self, user=99, chat=99, kind='private'):
        message = SimpleNamespace(chat=SimpleNamespace(id=chat, type=kind), message_id=42, is_accessible=True)
        message.reply_text = AsyncMock(return_value=message)
        message.edit_text = AsyncMock(return_value=message)
        coordinator = SimpleNamespace(settings=SimpleNamespace(admin_id=99, remote_browser_url='https://example.test/view'),
                                      paused=False, active=None, registration_busy=Mock(return_value=False),
                                      outcomes=SimpleNamespace(pending_count=Mock(return_value=0)),
                                      panel_sessions=PanelSessions(), store=SimpleNamespace(whitelist_map=Mock()))
        coordinator.queue_status_text = lambda: 'Coda: IN PAUSA.' if coordinator.paused else 'Coda: ATTIVA.'
        def pause(value):
            coordinator.paused = value
        coordinator.set_paused = Mock(side_effect=pause)
        update = SimpleNamespace(effective_user=SimpleNamespace(id=user), effective_chat=message.chat,
                                 effective_message=message, callback_query=None)
        context = SimpleNamespace(application=SimpleNamespace(bot_data={'coordinator': coordinator}), args=[])
        return coordinator, update, context, message

    def callback(self, update, message, action, token=None, user=99):
        coordinator = self.coordinator
        token = token or next(iter(coordinator.panel_sessions.entries))
        query = SimpleNamespace(from_user=SimpleNamespace(id=user), message=message,
                                data=f'panel:{action}:{token}', answer=AsyncMock())
        update.callback_query = query
        return query

    async def test_only_owner_private_chat_can_open_panel(self):
        for user, chat, kind in ((11, 11, 'private'), (99, -1, 'group'), (99, -1, 'supergroup'), (99, 11, 'private')):
            c, u, ctx, m = self.setup_panel(user, chat, kind)
            await worker.panel_command(u, ctx)
            m.reply_text.assert_not_awaited()
            self.assertFalse(c.panel_sessions.entries)

    async def test_missing_fields_do_not_open_panel(self):
        for field in ('effective_user', 'effective_chat', 'effective_message'):
            c, u, ctx, m = self.setup_panel()
            setattr(u, field, None)
            await worker.panel_command(u, ctx)
            m.reply_text.assert_not_awaited()

    async def test_owner_start_opens_panel_without_google_request(self):
        c, u, ctx, m = self.setup_panel()
        await worker.start_command(u, ctx)
        c.store.whitelist_map.assert_not_called()
        labels = [b.text for row in m.reply_text.call_args.kwargs['reply_markup'].inline_keyboard for b in row]
        for word in ('Stato', 'Pausa', 'Browser remoto', 'Controlli', 'Backup'):
            self.assertTrue(any(word in label for label in labels))
        self.assertNotIn('Riprendi', ' '.join(labels))

    async def opened(self):
        c, u, ctx, m = self.setup_panel()
        self.coordinator = c
        await worker.panel_command(u, ctx)
        return c, u, ctx, m

    async def test_other_user_forwarded_group_and_inaccessible_callbacks_have_no_effect(self):
        for condition in ('other', 'forwarded', 'group', 'inaccessible', 'absent'):
            c, u, ctx, m = await self.opened()
            q = self.callback(u, m, 'pause', user=11 if condition == 'other' else 99)
            if condition == 'forwarded':
                m.message_id = 43
            elif condition == 'group':
                m.chat = SimpleNamespace(type='group', id=-1)
            elif condition == 'inaccessible':
                m.is_accessible = False
            elif condition == 'absent':
                q.message = None
            await worker.callback_handler(u, ctx)
            c.set_paused.assert_not_called()
            m.edit_text.assert_not_awaited()
            self.assertTrue(q.answer.call_args.kwargs['show_alert'])

    async def test_expired_and_post_restart_buttons_do_not_act(self):
        for state in ('expired', 'restart'):
            c, u, ctx, m = await self.opened()
            q = self.callback(u, m, 'pause')
            if state == 'expired':
                next(iter(c.panel_sessions.entries.values()))['expires'] = 0
            else:
                c.panel_sessions = PanelSessions()
            await worker.callback_handler(u, ctx)
            c.set_paused.assert_not_called()

    async def test_pause_uses_existing_persistence_and_does_not_cancel_active_request(self):
        c, u, ctx, m = await self.opened()
        c.active = SimpleNamespace(request_id='fixture', status='ATTESA_SMS')
        c.registration_busy.return_value = True
        q = self.callback(u, m, 'pause')
        await worker.callback_handler(u, ctx)
        c.set_paused.assert_called_once_with(True)
        self.assertEqual(c.active.request_id, 'fixture')
        self.assertIn('continua', m.reply_text.call_args.args[0])
        self.assertTrue(any('Riprendi' in b.text for row in m.edit_text.call_args.kwargs['reply_markup'].inline_keyboard for b in row))
        # Same callback cannot perform a second pause or toggle back to active.
        await worker.callback_handler(u, ctx)
        c.set_paused.assert_called_once()
        self.assertTrue(c.paused)

    async def test_pause_save_error_is_not_reported_as_saved(self):
        c, u, ctx, m = await self.opened()
        c.set_paused.side_effect = worker.RegistrationError('Pausa non salvata')
        self.callback(u, m, 'pause')
        await worker.callback_handler(u, ctx)
        self.assertIn('non salvata', m.reply_text.call_args.args[0])

    async def test_resume_uses_existing_handler_and_button_changes(self):
        c, u, ctx, m = await self.opened()
        c.paused = True
        await worker.render_admin_panel(c, m, edit=True)
        self.callback(u, m, 'resume')
        await worker.callback_handler(u, ctx)
        c.set_paused.assert_called_once_with(False)
        self.assertFalse(c.paused)

    async def test_status_reloads_current_state_without_mutation(self):
        c, u, ctx, m = await self.opened()
        c.outcomes.pending_count.return_value = 7
        self.callback(u, m, 'status')
        await worker.callback_handler(u, ctx)
        self.assertIn('Sheets: 7', m.edit_text.call_args.args[0])
        c.set_paused.assert_not_called()

    async def test_browser_link_remains_private_and_does_not_start_registration(self):
        c, u, ctx, m = await self.opened()
        self.callback(u, m, 'browser')
        await worker.callback_handler(u, ctx)
        self.assertIn(c.settings.remote_browser_url, m.reply_text.call_args.args[0])
        self.assertTrue(m.reply_text.call_args.kwargs['disable_web_page_preview'])
        c.set_paused.assert_not_called()

    async def test_controls_only_reads_report_and_does_not_change_queue(self):
        c, u, ctx, m = await self.opened()
        self.callback(u, m, 'controls')
        with patch.object(worker, 'controls_text', return_value='Ultimo controllo: fixture') as read:
            await worker.callback_handler(u, ctx)
        read.assert_called_once_with()
        self.assertEqual(m.edit_text.call_args.args[0], 'Ultimo controllo: fixture')
        c.set_paused.assert_not_called()

    async def test_backup_requires_confirmation_and_replay_cannot_create_two_copies(self):
        c, u, ctx, m = await self.opened()
        # Forging a confirmation from a home keyboard must fail.
        self.callback(u, m, 'backup_yes')
        with patch.object(worker, 'backup_command', new_callable=AsyncMock) as backup:
            await worker.callback_handler(u, ctx)
            backup.assert_not_awaited()
            self.callback(u, m, 'backup')
            await worker.callback_handler(u, ctx)
            self.assertIn('non avvia il backup completo', m.edit_text.call_args.args[0])
            self.callback(u, m, 'backup_confirm')
            await worker.callback_handler(u, ctx)
            backup.assert_not_awaited()
            self.callback(u, m, 'backup_yes')
            await worker.callback_handler(u, ctx)
            backup.assert_awaited_once()
            self.assertEqual(backup.call_args.args[1].args, [])
            await worker.callback_handler(u, ctx)
            backup.assert_awaited_once()

    async def test_backup_status_routes_read_only_option_and_cancel_does_not_create(self):
        c, u, ctx, m = await self.opened()
        with patch.object(worker, 'backup_command', new_callable=AsyncMock) as backup:
            self.callback(u, m, 'backup')
            await worker.callback_handler(u, ctx)
            self.callback(u, m, 'backup_confirm')
            await worker.callback_handler(u, ctx)
            self.callback(u, m, 'backup')  # cancel
            await worker.callback_handler(u, ctx)
            backup.assert_not_awaited()
            self.callback(u, m, 'backup_status')
            await worker.callback_handler(u, ctx)
            self.assertEqual(backup.call_args.args[1].args, ['stato'])

    def test_session_storage_is_bounded_and_invalid_data_is_rejected(self):
        sessions = PanelSessions()
        for n in range(50):
            sessions.remember(f'{n:016x}', 99, n, {'pause'})
        self.assertEqual(len(sessions.entries), 32)
        for data in (None, 123, 'panel:pause:invalid', 'panel:deploy:'+'a'*16, 'panel:pause:'+'f'*16):
            self.assertIsNone(sessions.take(data, 99, 49))


class ControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'status.json'
        self.now = datetime.now(timezone.utc)
        self.report = dict(schema=1, checked_utc=self.now.isoformat(), codes={c: 'OK' for c in COMPONENTS})

    def read(self):
        self.path.write_text(json.dumps(self.report))
        return controls_text(self.path, self.now)

    def test_fresh_report_contains_seven_labels_and_time(self):
        text = self.read()
        self.assertEqual(text.count('✅'), 7)
        self.assertIn('Ultimo controllo', text)

    def test_failed_component_is_described(self):
        self.report['codes']['backup_pc'] = 'COPIA_PC_OBSOLETA'
        self.assertIn('⚠️ Copia sul PC: copia sul PC non aggiornata', self.read())

    def test_stale_report_never_confirms_current_health(self):
        self.report['checked_utc'] = (self.now - timedelta(minutes=10)).isoformat()
        self.assertIn('non confermano lo stato attuale', self.read())

    def test_missing_malformed_oversized_or_symlink_report_is_not_healthy(self):
        self.assertIn('non disponibile', controls_text(self.path, self.now))
        for raw in ('{', 'x'*8193):
            self.path.write_text(raw)
            self.assertIn('non valido', controls_text(self.path, self.now))
        self.path.unlink()
        self.path.symlink_to(Path(self.temp.name) / 'missing')
        self.assertIn('non valido', controls_text(self.path, self.now))

    def test_unknown_codes_future_dates_and_extra_secret_fields_are_rejected(self):
        for change in ('code', 'future', 'naive', 'extra', 'schema'):
            with self.subTest(change=change):
                self.report = dict(schema=1, checked_utc=self.now.isoformat(), codes={c: 'OK' for c in COMPONENTS})
                if change == 'code': self.report['codes']['mugnaio'] = 'PRIVATE-CONTENT'
                if change == 'future': self.report['checked_utc'] = (self.now + timedelta(minutes=5)).isoformat()
                if change == 'naive': self.report['checked_utc'] = self.now.replace(tzinfo=None).isoformat()
                if change == 'extra': self.report['private'] = 'TEST-SECRET'
                if change == 'schema': self.report['schema'] = True
                text = self.read()
                self.assertIn('non valido', text)
                self.assertNotIn('TEST-SECRET', text)
