import asyncio
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from test_regressions import worker
import test_telegram_panel as fixtures
from telegram_panel import ReusablePanel
from telegram.error import BadRequest, TimedOut


class ReuseTests(unittest.IsolatedAsyncioTestCase):
    setup_panel = fixtures.PanelTests.setup_panel
    callback = fixtures.PanelTests.callback
    opened = fixtures.PanelTests.opened

    async def test_repeated_menu_edits_one_message(self):
        c,u,ctx,m = await self.opened()
        for _ in range(3):
            await worker.panel_command(u,ctx)
        c.bot.send_message.assert_awaited_once()
        self.assertEqual(c.bot.edit_message_text.await_count,3)
        self.assertTrue(all(call.kwargs['message_id']==42 for call in c.bot.edit_message_text.call_args_list))
        m.reply_text.assert_not_awaited()

    async def test_menu_reuses_persisted_message_after_restart(self):
        c,u,ctx,m = await self.opened()
        c.panel = ReusablePanel(c.outcomes.db,99)
        c.panel_sessions = worker.PanelSessions()
        await worker.panel_command(u,ctx)
        c.bot.send_message.assert_awaited_once()
        self.assertEqual(c.bot.edit_message_text.call_args.kwargs['message_id'],42)

    async def test_close_and_open_keep_message_and_queue(self):
        c,u,ctx,m = await self.opened()
        self.callback(u,m,'close')
        await worker.callback_handler(u,ctx)
        closed = c.bot.edit_message_text.call_args.kwargs
        self.assertIn('chiuso',closed['text'])
        self.assertEqual(len(closed['reply_markup'].inline_keyboard),1)
        self.assertEqual(closed['reply_markup'].inline_keyboard[0][0].text,'🌾 Apri pannello')
        self.callback(u,m,'open')
        await worker.callback_handler(u,ctx)
        self.assertIn('pannello privato',c.bot.edit_message_text.call_args.kwargs['text'])
        c.bot.send_message.assert_awaited_once()
        c.set_paused.assert_not_called()

    async def test_closed_panel_can_reopen_after_restart_without_expired_mutations(self):
        c,u,ctx,m = await self.opened()
        self.callback(u,m,'close')
        await worker.callback_handler(u,ctx)
        q=self.callback(u,m,'open')
        c.panel=ReusablePanel(c.outcomes.db,99)
        c.panel_sessions=worker.PanelSessions()
        await worker.callback_handler(u,ctx)
        self.assertIn('pannello privato',c.bot.edit_message_text.call_args.kwargs['text'])
        q.data=q.data.replace(':open:',':resume:')
        await worker.callback_handler(u,ctx)
        c.set_paused.assert_not_called()
        c.bot.send_message.assert_awaited_once()

    async def test_foreign_bot_or_wrong_owner_pointer_is_never_edited(self):
        c,u,ctx,m=self.setup_panel()
        c.panel.bind(8,44)
        await worker.panel_command(u,ctx)
        c.bot.edit_message_text.assert_not_awaited()
        c.bot.send_message.assert_awaited_once()
        db=c.outcomes.db
        db.execute("UPDATE runtime_settings SET value=? WHERE key='admin_panel'",(json.dumps(dict(owner=11,bot=7,message=44)),))
        c.panel=ReusablePanel(db,99)
        self.assertIsNone(c.panel.message_id(7))

    async def test_deleted_message_is_replaced_once(self):
        c,u,ctx,m=await self.opened()
        c.bot.edit_message_text.side_effect=BadRequest('Message to edit not found')
        replacement=SimpleNamespace(message_id=43,chat=m.chat,from_user=m.from_user)
        c.bot.send_message.return_value=replacement
        await worker.panel_command(u,ctx)
        self.assertEqual(c.bot.send_message.await_count,2)
        self.assertEqual(c.panel.message_id(7),43)
        c.bot.edit_message_text.side_effect=None
        c.bot.edit_message_text.return_value=replacement
        await worker.panel_command(u,ctx)
        self.assertEqual(c.bot.send_message.await_count,2)

    async def test_transport_and_unrelated_bad_request_never_create_duplicate(self):
        for error in (TimedOut(),BadRequest('Invalid reply markup')):
            c,u,ctx,m=await self.opened()
            c.bot.edit_message_text.side_effect=error
            with self.assertRaises(type(error)):
                await worker.panel_command(u,ctx)
            c.bot.send_message.assert_awaited_once()
            self.assertEqual(c.panel.message_id(7),42)

    async def test_storage_failure_keeps_memory_pointer_and_reports_limitation(self):
        c,u,ctx,m=self.setup_panel()
        c.panel.db=Mock(execute=Mock(side_effect=sqlite3.OperationalError('TEST-SECRET')))
        await worker.panel_command(u,ctx)
        await worker.panel_command(u,ctx)
        c.bot.send_message.assert_awaited_once()
        self.assertIn('Non riesco a salvare',c.bot.edit_message_text.call_args.kwargs['text'])
        self.assertNotIn('TEST-SECRET',c.bot.edit_message_text.call_args.kwargs['text'])

    async def test_browser_pause_and_resume_only_edit_existing_panel(self):
        c,u,ctx,m=await self.opened()
        for action in ('browser','pause','resume'):
            self.callback(u,m,action)
            await worker.callback_handler(u,ctx)
        c.bot.send_message.assert_awaited_once()
        m.reply_text.assert_not_awaited()
        self.assertFalse(c.paused)

    async def test_pause_persistence_is_same_as_existing_command(self):
        c,u,ctx,m=await self.opened()
        outcomes=worker.CreatedOutcomes()
        self.addCleanup(outcomes.close)
        c.outcomes=outcomes
        c.pause_persisted=True
        c.set_paused=lambda value: worker.Coordinator.set_paused(c,value)
        self.callback(u,m,'pause')
        await worker.callback_handler(u,ctx)
        self.assertTrue(outcomes.queue_paused())
        self.callback(u,m,'resume')
        await worker.callback_handler(u,ctx)
        self.assertFalse(outcomes.queue_paused())
        c.bot.send_message.assert_awaited_once()

    def backup_fixture(self,c):
        info=dict(created_at=0,filename='manual-fixture.zip',retention_ok=True,
                  files={'created-outcomes.sqlite3':{'database':{'rows':5}}})
        c.backups=SimpleNamespace(create=Mock(return_value=info),latest=Mock(return_value=(None,0)))
        c.backup_lock=asyncio.Lock()
        c.backup_task=None
        c.backup_error=False
        c.persist_before_backup=Mock()
        c.safe_notice=AsyncMock()
        return info

    async def test_backup_success_progress_and_result_are_same_message(self):
        c,u,ctx,m=await self.opened()
        self.backup_fixture(c)
        await worker.start_panel_backup(c,status_only=False)
        await c.backup_task
        self.assertIn('Backup creato e verificato',c.bot.edit_message_text.call_args.kwargs['text'])
        self.assertIn('5 esiti',c.panel.backup_result)
        c.backups.create.assert_called_once_with('manual')
        c.bot.send_message.assert_awaited_once()
        c.safe_notice.assert_not_awaited()
        m.reply_text.assert_not_awaited()

    async def test_backup_confirmation_replay_cannot_duplicate_real_task(self):
        c,u,ctx,m=await self.opened()
        self.backup_fixture(c)
        for action in ('backup','backup_confirm','backup_yes'):
            self.callback(u,m,action)
            await worker.callback_handler(u,ctx)
        await worker.callback_handler(u,ctx)
        await c.backup_task
        c.backups.create.assert_called_once()
        c.bot.send_message.assert_awaited_once()

    async def test_late_result_does_not_reopen_closed_or_overwrite_other_page(self):
        for view in ('closed','controls'):
            c,u,ctx,m=await self.opened()
            self.backup_fixture(c)
            started=asyncio.Event()
            release=asyncio.Event()
            async def delayed_thread(function,*args):
                started.set()
                await release.wait()
                return function(*args)
            with patch.object(worker.asyncio,'to_thread',side_effect=delayed_thread):
                await worker.start_panel_backup(c,status_only=False)
                await started.wait()
                await worker.render_admin_panel(c,m,text='PAGE-FIXTURE',view=view)
                edits=c.bot.edit_message_text.await_count
                release.set()
                await c.backup_task
            self.assertEqual(c.bot.edit_message_text.await_count,edits)
            self.assertEqual(c.panel.view,view)
            self.assertIn('Backup creato',c.panel.backup_result)
            self.callback(u,m,'open' if view=='closed' else 'backup')
            await worker.callback_handler(u,ctx)
            if view=='closed':
                self.callback(u,m,'backup')
                await worker.callback_handler(u,ctx)
            self.assertIn('Ultimo risultato',c.bot.edit_message_text.call_args.kwargs['text'])
            c.bot.send_message.assert_awaited_once()

    async def test_backup_error_remains_private_urgent_notice_even_when_closed(self):
        c,u,ctx,m=await self.opened()
        self.backup_fixture(c)
        c.backups.create.side_effect=OSError('TEST-SECRET')
        revision=await worker.render_admin_panel(c,m,text='busy',view='backup')
        await worker.render_admin_panel(c,m,view='closed')
        await worker.run_backup_command(c,None,False,panel_revision=revision)
        self.assertEqual(c.panel.view,'closed')
        c.safe_notice.assert_awaited_once()
        self.assertEqual(c.safe_notice.call_args.args[0],99)
        self.assertNotIn('TEST-SECRET',c.safe_notice.call_args.args[1])
        self.assertTrue(c.backup_error)

    async def test_delivery_failure_does_not_mark_valid_backup_as_failed_or_retry(self):
        c,u,ctx,m=await self.opened()
        self.backup_fixture(c)
        revision=await worker.render_admin_panel(c,m,text='busy',view='backup')
        c.bot.edit_message_text.side_effect=TimedOut()
        await worker.run_backup_command(c,None,False,panel_revision=revision)
        self.assertFalse(c.backup_error)
        c.backups.create.assert_called_once()
        self.assertIn('Backup creato',c.panel.backup_result)
        c.bot.send_message.assert_awaited_once()

    async def test_direct_backup_command_keeps_existing_replies(self):
        c,u,ctx,m=await self.opened()
        self.backup_fixture(c)
        await worker.backup_command(u,ctx)
        await c.backup_task
        self.assertEqual(m.reply_text.await_count,2)
        self.assertIn('Backup creato',m.reply_text.call_args.args[0])

    async def test_second_backup_while_busy_does_not_start_another_job(self):
        c,u,ctx,m=await self.opened()
        self.backup_fixture(c)
        async with c.backup_lock:
            await worker.start_panel_backup(c,status_only=False)
        c.backups.create.assert_not_called()
        self.assertIsNone(c.backup_task)
        self.assertIn('già in corso',c.bot.edit_message_text.call_args.kwargs['text'])


class PointerTests(unittest.TestCase):
    def test_pointer_roundtrip_preserves_other_runtime_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'fixture.sqlite3'
            db=sqlite3.connect(path,isolation_level=None)
            db.execute('CREATE TABLE runtime_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute("INSERT INTO runtime_settings VALUES ('queue_paused','1')")
            panel=ReusablePanel(db,99)
            panel.bind(7,42)
            db.close()
            db=sqlite3.connect(path,isolation_level=None)
            try:
                restored=ReusablePanel(db,99)
                self.assertEqual(restored.message_id(7),42)
                self.assertIsNone(restored.message_id(8))
                self.assertEqual(db.execute("SELECT value FROM runtime_settings WHERE key='queue_paused'").fetchone(),('1',))
                self.assertEqual(set(json.loads(db.execute("SELECT value FROM runtime_settings WHERE key='admin_panel'").fetchone()[0])),{'owner','bot','message'})
            finally:
                db.close()

    def test_corrupt_or_nonnumeric_pointer_cannot_select_message(self):
        db=sqlite3.connect(':memory:',isolation_level=None)
        self.addCleanup(db.close)
        db.execute('CREATE TABLE runtime_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        for value in ('{',json.dumps(dict(owner=99,bot=True,message=42)),json.dumps(dict(owner=99,bot=7,message=-2)),json.dumps(dict(owner=99,bot=7,message=42,secret='TEST-SECRET'))):
            db.execute("INSERT OR REPLACE INTO runtime_settings VALUES ('admin_panel',?)",(value,))
            self.assertIsNone(ReusablePanel(db,99).message_id(7))
