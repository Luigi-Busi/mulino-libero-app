import asyncio
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut
from telegram_panel import AdminChatCleanup, ReusablePanel
from test_regressions import worker
import test_telegram_panel as fixtures


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:', isolation_level=None)
        self.db.execute('CREATE TABLE runtime_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        self.addCleanup(self.db.close)
        self.panel = ReusablePanel(self.db, 99)
        self.bot = SimpleNamespace(id=7, delete_message=AsyncMock(return_value=True))

    async def test_atomic_pointer_replacement_queues_only_previous_panel(self):
        self.panel.bind(7, 42)
        self.panel.bind(7, 44, retired_message=42)
        self.assertFalse(self.panel.persistence_error)
        self.assertEqual(ReusablePanel(self.db,99).message_id(7),44)
        await self.panel.cleanup.drain(self.bot,44)
        self.bot.delete_message.assert_awaited_once()
        self.assertEqual(self.bot.delete_message.call_args.kwargs['message_id'],42)

    async def test_failed_queue_write_keeps_durable_old_pointer_and_never_deletes_it(self):
        self.panel.bind(7,42)
        self.db.execute("CREATE TRIGGER fail_cleanup BEFORE INSERT ON admin_chat_cleanup BEGIN SELECT RAISE(ABORT,'TEST-SECRET'); END")
        self.panel.bind(7,44,retired_message=42)
        self.assertTrue(self.panel.persistence_error)
        self.assertEqual(self.panel.message_id(7),44)
        self.assertEqual(ReusablePanel(self.db,99).message_id(7),42)
        await self.panel.cleanup.drain(self.bot,44)
        self.bot.delete_message.assert_not_awaited()

    async def test_current_pointer_foreign_owner_and_other_bot_are_protected(self):
        self.panel.bind(7,44)
        self.panel.cleanup.enqueue(7,44,'panel')
        AdminChatCleanup(self.db,11).enqueue(7,45,'command')
        self.panel.cleanup.enqueue(8,46,'panel')
        await self.panel.cleanup.drain(self.bot,44)
        self.bot.delete_message.assert_not_awaited()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM admin_chat_cleanup').fetchone()[0],2)

    async def test_rotation_while_waiting_for_cleanup_lock_uses_current_pointer(self):
        self.panel.bind(7,42)
        await self.panel.cleanup.lock.acquire()
        task=asyncio.create_task(self.panel.cleanup.drain(self.bot, lambda:self.panel.message_id(7)))
        await asyncio.sleep(0)
        self.panel.bind(7,44,retired_message=42)
        self.panel.cleanup.lock.release()
        await task
        self.bot.delete_message.assert_awaited_once()
        self.assertEqual(self.bot.delete_message.call_args.kwargs['message_id'],42)
        self.assertEqual(self.panel.message_id(7),44)

    async def test_transient_failure_retains_target_and_retry_is_idempotent(self):
        self.panel.cleanup.enqueue(7,42,'panel')
        self.bot.delete_message.side_effect=TimedOut()
        await self.panel.cleanup.drain(self.bot,44)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM admin_chat_cleanup').fetchone()[0],1)
        self.bot.delete_message.side_effect=None
        self.panel.cleanup.retry_at=0
        await self.panel.cleanup.drain(self.bot,44)
        await self.panel.cleanup.drain(self.bot,44)
        self.assertEqual(self.bot.delete_message.await_count,2)

    async def test_rate_limit_respected_and_unexpected_bad_request_retained(self):
        for error in (RetryAfter(4),BadRequest('TEST-SECRET unexpected')):
            self.panel.cleanup.enqueue(7,42,'command')
            self.bot.delete_message.side_effect=error
            self.panel.cleanup.retry_at=0
            with patch('telegram_panel.time.monotonic',return_value=100):
                await self.panel.cleanup.drain(self.bot,None)
                before=self.bot.delete_message.await_count
                await self.panel.cleanup.drain(self.bot,None)
                self.assertEqual(self.bot.delete_message.await_count,before)
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM admin_chat_cleanup').fetchone()[0],1)

    async def test_known_permanent_deletion_failures_do_not_loop(self):
        for error in (BadRequest('Message to delete not found'),BadRequest("Message can't be deleted"),Forbidden('denied')):
            self.panel.cleanup.enqueue(7,42,'command')
            self.bot.delete_message.side_effect=error
            await self.panel.cleanup.drain(self.bot,44)
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM admin_chat_cleanup').fetchone()[0],0)

    async def test_unconfirmed_response_keeps_job_and_storage_errors_are_nonfatal(self):
        self.panel.cleanup.enqueue(7,42,'command')
        self.bot.delete_message.return_value=False
        await self.panel.cleanup.drain(self.bot,44)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM admin_chat_cleanup').fetchone()[0],1)
        self.panel.cleanup.retry_at=0
        self.db.execute('DROP TABLE admin_chat_cleanup')
        await self.panel.cleanup.drain(self.bot,44)

    async def test_restart_retains_job_and_database_records_no_message_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'fixture.sqlite3'
            db=sqlite3.connect(path,isolation_level=None)
            db.execute('CREATE TABLE runtime_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            p=ReusablePanel(db,99);p.bind(7,42);p.bind(7,44,retired_message=42)
            db.close()
            db=sqlite3.connect(path,isolation_level=None)
            try:
                p=ReusablePanel(db,99)
                await p.cleanup.drain(self.bot,p.message_id(7))
                self.assertEqual(self.bot.delete_message.call_args.kwargs['message_id'],42)
                self.assertEqual([r[1] for r in db.execute('PRAGMA table_info(admin_chat_cleanup)')],['owner','bot','message','kind'])
            finally:
                db.close()

    async def test_invalid_targets_are_rejected(self):
        for value in (True,0,-1,'42',2**63):
            with self.assertRaises(ValueError):
                self.panel.cleanup.enqueue(7,value,'command')
        with self.assertRaises(ValueError):
            self.panel.cleanup.enqueue(7,42,'ordinary')


class MenuMoveTests(unittest.IsolatedAsyncioTestCase):
    setup_panel = fixtures.PanelTests.setup_panel
    callback = fixtures.PanelTests.callback
    opened = fixtures.PanelTests.opened

    def command(self, message_id=50, text='/menu'):
        return SimpleNamespace(chat=SimpleNamespace(id=99,type='private'),message_id=message_id,
                               from_user=SimpleNamespace(id=99),text=text)

    async def test_new_panel_is_sent_saved_then_old_and_command_are_deleted(self):
        c,u,ctx,m=await self.opened()
        incoming=self.command();u.effective_message=incoming
        sent=SimpleNamespace(chat=m.chat,message_id=52,from_user=m.from_user)
        events=[]
        async def send(**kwargs):
            self.assertEqual(c.panel.message_id(7),42)
            events.append('send')
            return sent
        async def delete(**kwargs):
            self.assertEqual(ReusablePanel(c.panel.db,99).message_id(7),52)
            events.append(kwargs['message_id'])
            return True
        c.bot.send_message.side_effect=send;c.bot.delete_message.side_effect=delete
        await worker.admin_command(worker.panel_command)(u,ctx)
        self.assertEqual(events,['send',42,50])
        self.assertEqual(c.panel.message_id(7),52)
        self.callback(u,m,'resume')
        await worker.callback_handler(u,ctx)
        c.set_paused.assert_not_called()
        c.bot.edit_message_text.assert_not_awaited()

    async def test_send_failure_leaves_old_panel_and_incoming_command(self):
        c,u,ctx,m=await self.opened()
        u.effective_message=self.command()
        c.bot.send_message.side_effect=TimedOut()
        with self.assertRaises(TimedOut):
            await worker.admin_command(worker.panel_command)(u,ctx)
        self.assertEqual(c.panel.message_id(7),42)
        c.bot.delete_message.assert_not_awaited()
        self.assertEqual(c.panel.cleanup.db.execute('SELECT COUNT(*) FROM admin_chat_cleanup').fetchone()[0],0)

    async def test_delete_failure_keeps_new_panel_and_buttons_work_without_resend(self):
        c,u,ctx,m=await self.opened()
        u.effective_message=self.command()
        sent=SimpleNamespace(chat=m.chat,message_id=52,from_user=m.from_user,is_accessible=True)
        c.bot.send_message.return_value=sent;c.bot.edit_message_text.return_value=sent
        c.bot.delete_message.side_effect=TimedOut()
        await worker.admin_command(worker.panel_command)(u,ctx)
        self.assertEqual(c.panel.message_id(7),52)
        self.callback(u,sent,'close')
        await worker.callback_handler(u,ctx)
        self.callback(u,sent,'open')
        await worker.callback_handler(u,ctx)
        self.assertEqual(c.bot.send_message.await_count,2)

    async def test_pannello_and_start_aliases_edit_without_retiring_current(self):
        c,u,ctx,m=await self.opened()
        for text in ('/pannello','/start'):
            u.effective_message=self.command(text=text)
            await worker.admin_command(worker.panel_command)(u,ctx)
        c.bot.send_message.assert_awaited_once()
        self.assertTrue(all(call.kwargs['message_id']==50 for call in c.bot.delete_message.call_args_list))
        self.assertEqual(c.panel.message_id(7),42)

    async def test_back_to_back_menu_moves_and_pending_backup_never_reopens_old_panel(self):
        c,u,ctx,m=await self.opened()
        revision=c.panel.revision
        for command_id,panel_id in ((50,52),(54,56)):
            sent=SimpleNamespace(chat=m.chat,message_id=panel_id,from_user=m.from_user)
            c.bot.send_message.return_value=sent
            u.effective_message=self.command(command_id)
            await worker.admin_command(worker.panel_command)(u,ctx)
        await worker.finish_panel_backup(c,'completed',revision)
        self.assertEqual(c.panel.message_id(7),56)
        c.bot.edit_message_text.assert_not_awaited()
        self.assertEqual(c.panel.backup_result,'completed')
        self.assertEqual([call.kwargs['message_id'] for call in c.bot.delete_message.call_args_list],[42,50,52,54])

    async def test_command_wrapper_deletes_only_registered_owner_input_after_handler(self):
        c,u,ctx,m=self.setup_panel()
        u.effective_message=self.command(text='/stato')
        async def handler(update,context):
            c.bot.delete_message.assert_not_awaited()
        await worker.admin_command(handler)(u,ctx)
        c.bot.delete_message.assert_awaited_once()
        self.assertEqual(c.bot.delete_message.call_args.kwargs['message_id'],50)

    async def test_failed_handler_does_not_delete_input_or_add_job(self):
        c,u,ctx,m=self.setup_panel()
        u.effective_message=self.command(text='/azzera 11')
        callback=AsyncMock(side_effect=RuntimeError('failure'))
        with self.assertRaises(RuntimeError):
            await worker.admin_command(callback)(u,ctx)
        c.bot.delete_message.assert_not_awaited()

    async def test_groups_testers_plain_text_unknown_forwarded_and_bot_messages_not_deleted(self):
        for condition in ('group','tester','plain','unknown','forwarded','bot','wrong_chat','missing'):
            c,u,ctx,m=self.setup_panel()
            incoming=self.command(text='/stato')
            u.effective_message=incoming
            if condition=='group': u.effective_chat.type='group'
            if condition=='tester': u.effective_user.id=11;incoming.from_user.id=11
            if condition=='plain': incoming.text='123456'
            if condition=='unknown': incoming.text='/unknown'
            if condition=='forwarded': incoming.forward_origin=object()
            if condition=='bot': incoming.from_user.id=7
            if condition=='wrong_chat': incoming.chat.id=11
            if condition=='missing': u.effective_message=None
            await worker.admin_command(AsyncMock())(u,ctx)
            c.bot.delete_message.assert_not_awaited()

    async def test_command_tracking_failure_does_not_repeat_a_successful_action(self):
        c,u,ctx,m=self.setup_panel()
        u.effective_message=self.command(text='/pausa')
        callback=AsyncMock()
        with patch.object(c.panel.cleanup,'enqueue',side_effect=sqlite3.OperationalError('TEST-SECRET')):
            await worker.admin_command(callback)(u,ctx)
        callback.assert_awaited_once()
        c.bot.delete_message.assert_not_awaited()
