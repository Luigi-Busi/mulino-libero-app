import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from telegram.error import BadRequest, RetryAfter, TimedOut
from telegram_panel import AdminChatCleanup, ReusablePanel
from test_regressions import worker
import test_telegram_panel as fixtures


NOW = 1800000000


class ResponseAgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:', isolation_level=None)
        self.db.execute('CREATE TABLE runtime_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        self.addCleanup(self.db.close)
        self.panel = ReusablePanel(self.db, 99)
        self.cleanup = self.panel.cleanup
        self.bot = SimpleNamespace(id=7, delete_message=AsyncMock(return_value=True))
        self.clock = patch('telegram_panel.time.time', return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def response(self, message, age=0):
        self.cleanup.track_response(7, message, NOW-age)

    def recorded(self):
        return [r[0] for r in self.db.execute('SELECT message FROM admin_response_history ORDER BY message')]

    async def test_exact_12_hour_threshold_keeps_latest_and_younger_replies(self):
        self.response(40, 43200)
        self.response(41, 43199)
        self.response(42, 0)
        await self.cleanup.drain(self.bot, None)
        self.assertEqual([c.kwargs['message_id'] for c in self.bot.delete_message.call_args_list], [40])
        self.assertEqual(self.recorded(), [41, 42])

    async def test_background_pass_without_new_command_keeps_only_latest_after_half_day(self):
        self.response(40, 0); self.response(41, 0); self.response(42, 0)
        with patch('telegram_panel.time.time', return_value=NOW+43200):
            await self.cleanup.drain(self.bot, None)
        self.assertEqual([c.kwargs['message_id'] for c in self.bot.delete_message.call_args_list], [40, 41])
        self.assertEqual(self.recorded(), [42])

    async def test_latest_always_survives_even_if_weeks_old(self):
        self.response(42, 20*86400)
        await self.cleanup.drain(self.bot, None)
        self.bot.delete_message.assert_not_awaited()
        self.assertEqual(self.recorded(), [42])

    async def test_48_hour_expiry_forgets_only_old_metadata_without_telegram_deletion(self):
        self.response(40, 172800); self.response(41, 172799); self.response(42, 0)
        await self.cleanup.drain(self.bot, None)
        self.assertEqual([c.kwargs['message_id'] for c in self.bot.delete_message.call_args_list], [41])
        self.assertEqual(self.recorded(), [42])

    async def test_foreign_owner_bot_and_current_panel_never_deleted(self):
        AdminChatCleanup(self.db, 11).track_response(7, 39, NOW-86400)
        AdminChatCleanup(self.db, 11).track_response(7, 43, NOW)
        self.cleanup.track_response(8, 38, NOW-86400)
        self.cleanup.track_response(8, 44, NOW)
        self.response(40, 86400); self.response(42, 0)
        await self.cleanup.drain(self.bot, lambda: 40)
        self.bot.delete_message.assert_not_awaited()
        self.assertEqual(self.recorded(), [38, 39, 42, 43, 44])

    async def test_restart_preserves_age_latest_and_only_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'fixture.sqlite3'
            db = sqlite3.connect(path, isolation_level=None)
            c = AdminChatCleanup(db, 99)
            c.track_response(7, 40, NOW-86400); c.track_response(7, 42, NOW)
            db.close()
            db = sqlite3.connect(path, isolation_level=None)
            try:
                c = AdminChatCleanup(db, 99)
                await c.drain(self.bot, None)
                self.assertEqual([r[0] for r in db.execute('SELECT message FROM admin_response_history')], [42])
                self.assertEqual([r[1] for r in db.execute('PRAGMA table_info(admin_response_history)')],
                                 ['owner', 'bot', 'message', 'category', 'sent_at'])
            finally:
                db.close()

    async def test_response_network_failure_and_rate_limit_retain_job_without_resending(self):
        for error in (TimedOut(), RetryAfter(4), BadRequest('unexpected')):
            self.response(40, 86400); self.response(42, 0)
            self.bot.delete_message.side_effect = error
            self.cleanup.retry_at = 0
            await self.cleanup.drain(self.bot, None)
            before = self.bot.delete_message.await_count
            await self.cleanup.drain(self.bot, None)
            self.assertEqual(self.bot.delete_message.await_count, before)
            self.assertEqual(self.recorded(), [40, 42])
        self.bot.delete_message.side_effect = None
        self.cleanup.retry_at = 0
        await self.cleanup.drain(self.bot, None)
        self.assertEqual(self.recorded(), [42])

    async def test_permanent_failure_keeps_latest_and_does_not_retry_forever(self):
        self.response(40, 86400); self.response(42, 0)
        self.bot.delete_message.side_effect = BadRequest("Message can't be deleted")
        await self.cleanup.drain(self.bot, None)
        await self.cleanup.drain(self.bot, None)
        self.bot.delete_message.assert_awaited_once()
        self.assertEqual(self.recorded(), [42])

    async def test_late_out_of_order_tracking_and_duplicates_do_not_change_newest_or_age(self):
        self.response(42, 0); self.response(40, 86400)
        self.response(40, 0); self.response(42, 86400)
        await self.cleanup.drain(self.bot, None)
        self.assertEqual(self.bot.delete_message.call_args.kwargs['message_id'], 40)
        self.assertEqual(self.recorded(), [42])

    async def test_bounded_passes_and_coexistence_with_command_and_panel_cleanup(self):
        for message in range(20, 40): self.response(message, 86400)
        self.response(50, 0)
        self.cleanup.enqueue(7, 10, 'command'); self.cleanup.enqueue(7, 11, 'panel')
        await self.cleanup.drain(self.bot, 60)
        self.assertEqual(self.bot.delete_message.await_count, 10)
        await self.cleanup.drain(self.bot, 60)
        await self.cleanup.drain(self.bot, 60)
        self.assertEqual(self.recorded(), [50])

    async def test_invalid_metadata_future_time_and_database_failure_are_safe(self):
        for message, when in [(True,NOW),(0,NOW),(2**63,NOW),(40,0),(40,True),(40,NOW+61)]:
            with self.assertRaises(ValueError): self.cleanup.track_response(7, message, when)
        self.db.execute('DROP TABLE admin_response_history')
        await self.cleanup.drain(self.bot, None)
        self.bot.delete_message.assert_not_awaited()

    async def test_pointer_rotation_while_waiting_for_lock_protects_current_message(self):
        self.response(40, 86400); self.response(42, 0)
        self.panel.bind(7, 50)
        await self.cleanup.lock.acquire()
        task = asyncio.create_task(self.cleanup.drain(self.bot, lambda:self.panel.message_id(7)))
        await asyncio.sleep(0)
        self.panel.bind(7, 40)
        self.cleanup.lock.release()
        await task
        self.bot.delete_message.assert_not_awaited()
        self.assertEqual(self.recorded(), [42])


class RoutineReplyTests(unittest.IsolatedAsyncioTestCase):
    setup_panel = fixtures.PanelTests.setup_panel

    def command(self, name='/stato', response_id=80):
        c, u, ctx, message = self.setup_panel()
        message.text = name
        message.from_user = SimpleNamespace(id=99)
        message.message_id = 60
        sent = SimpleNamespace(chat=message.chat, from_user=SimpleNamespace(id=7),
                               message_id=response_id, date=datetime.now(timezone.utc))
        message.reply_text = AsyncMock(return_value=sent)
        return c, u, ctx, message, sent

    def tracked(self, c):
        return c.outcomes.db.execute('SELECT message FROM admin_response_history').fetchall()

    async def test_three_successful_commands_share_one_category_and_keep_actual_delivery_time(self):
        for name, handler in [('/pausa',worker.pause_command),('/stato',worker.status_command),('/riprendi',worker.resume_command)]:
            c,u,ctx,m,sent = self.command(name)
            await worker.admin_command(handler)(u,ctx)
            self.assertEqual(self.tracked(c), [(80,)])
            row = c.outcomes.db.execute('SELECT category,sent_at FROM admin_response_history').fetchone()
            self.assertEqual(row, ('queue',int(sent.date.timestamp())))
            self.assertEqual([call.kwargs['message_id'] for call in c.bot.delete_message.call_args_list], [60])

    async def test_busy_pending_unsaved_pause_and_state_errors_are_not_tracked(self):
        for condition in ('busy_pause','busy_status','busy_resume','pending','unsaved','pause_error','resume_error'):
            name = '/pausa' if 'pause' in condition else '/riprendi' if 'resume' in condition else '/stato'
            c,u,ctx,m,_ = self.command(name)
            if condition.startswith('busy'): c.registration_busy.return_value=True
            if condition=='pending': c.outcomes.pending_count.return_value=2
            if condition=='unsaved': c.pause_persisted=False
            if condition.endswith('error'): c.set_paused.side_effect=worker.RegistrationError('fixture error')
            await {'/pausa':worker.pause_command,'/riprendi':worker.resume_command,'/stato':worker.status_command}[name](u,ctx)
            self.assertEqual(self.tracked(c), [])
            m.reply_text.assert_awaited_once()

    async def test_active_registration_keeps_existing_temporary_status_path(self):
        c,u,ctx,m,_ = self.command()
        c.active=SimpleNamespace(request_id='fixture',status='IN_CREAZIONE')
        c.cleanup_messages=AsyncMock(); c.messages=SimpleNamespace(track=lambda *args:None)
        c.reply_temporary=AsyncMock()
        await worker.status_command(u,ctx)
        self.assertEqual(self.tracked(c), [])
        c.reply_temporary.assert_awaited_once()

    async def test_panel_groups_testers_forwards_unknown_commands_and_foreign_reply_are_excluded(self):
        for condition in ('panel','group','tester','forward','automatic','unknown','wrong_input_chat','wrong_reply_chat','wrong_bot','no_date','naive_date','invalid_id'):
            c,u,ctx,m,sent = self.command()
            if condition=='panel': u.effective_message=worker.PanelReply()
            if condition=='group': u.effective_chat.type='group'
            if condition=='tester': u.effective_user.id=11
            if condition=='forward': m.forward_origin=object()
            if condition=='automatic': m.is_automatic_forward=True
            if condition=='unknown': m.text='/backup'
            if condition=='wrong_input_chat': m.chat=SimpleNamespace(id=11,type='private')
            if condition=='wrong_reply_chat': sent.chat=SimpleNamespace(id=11,type='private')
            if condition=='wrong_bot': sent.from_user.id=8
            if condition=='no_date': sent.date=None
            if condition=='naive_date': sent.date=datetime.now()
            if condition=='invalid_id': sent.message_id=True
            await worker.reply_queue_summary(c,u,'fixture',routine=True)
            self.assertEqual(self.tracked(c), [], condition)

    async def test_send_failure_and_tracking_failure_do_not_repeat_queue_state_change(self):
        c,u,ctx,m,_ = self.command('/riprendi')
        m.reply_text.side_effect=TimedOut()
        with self.assertRaises(TimedOut): await worker.resume_command(u,ctx)
        c.set_paused.assert_called_once_with(False)
        self.assertEqual(self.tracked(c), [])
        c,u,ctx,m,_ = self.command('/riprendi')
        c.outcomes.db.execute("CREATE TRIGGER fail_history BEFORE INSERT ON admin_response_history BEGIN SELECT RAISE(ABORT,'fixture private text'); END")
        await worker.resume_command(u,ctx)
        c.set_paused.assert_called_once_with(False)
        m.reply_text.assert_awaited_once()
        self.assertEqual(self.tracked(c), [])
