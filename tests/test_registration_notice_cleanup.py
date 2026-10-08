import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from telegram.error import TimedOut, BadRequest
from telegram_panel import AdminChatCleanup
import test_regressions as fixtures
from test_regressions import worker

NOW = 1800000000

class NoticeCleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:',isolation_level=None)
        self.addCleanup(self.db.close)
        self.c=AdminChatCleanup(self.db,99)
        self.bot=SimpleNamespace(id=7,delete_message=AsyncMock(return_value=True))
        self.clock=patch('telegram_panel.time.time',return_value=NOW)
        self.clock.start();self.addCleanup(self.clock.stop)

    def add(self,message,age):
        self.c.track_registration_notice(7,message,NOW-age)

    def ids(self):
        return [r[0] for r in self.db.execute('SELECT message FROM admin_registration_notice_history ORDER BY message')]

    async def test_boundary_and_independent_latest_in_both_categories(self):
        self.add(40,43200);self.add(41,43199);self.add(42,0)
        self.c.track_response(7,50,NOW-86400);self.c.track_response(7,51,NOW)
        await self.c.drain(self.bot,None)
        self.assertEqual(self.ids(),[41,42])
        self.assertEqual([x.kwargs['message_id'] for x in self.bot.delete_message.call_args_list],[50,40])
        with patch('telegram_panel.time.time',return_value=NOW+43200):
            await self.c.drain(self.bot,None)
        self.assertEqual(self.ids(),[42])
        self.assertEqual([r[0] for r in self.db.execute('SELECT message FROM admin_response_history')],[51])

    async def test_last_notice_survives_weeks_and_old_metadata_is_not_deleted_on_telegram(self):
        self.add(40,172800);self.add(41,172799);self.add(42,0)
        await self.c.drain(self.bot,None)
        self.assertEqual([x.kwargs['message_id'] for x in self.bot.delete_message.call_args_list],[41])
        with patch('telegram_panel.time.time',return_value=NOW+20*86400):
            await self.c.drain(self.bot,None)
        self.assertEqual(self.ids(),[42])
        self.assertEqual(self.bot.delete_message.await_count,1)

    async def test_out_of_order_duplicates_and_current_panel_owner_bot_protection(self):
        self.add(42,0);self.add(40,86400);self.add(40,0)
        AdminChatCleanup(self.db,11).track_registration_notice(7,38,NOW-86400)
        AdminChatCleanup(self.db,11).track_registration_notice(7,43,NOW)
        self.c.track_registration_notice(8,39,NOW-86400)
        self.c.track_registration_notice(8,44,NOW)
        await self.c.drain(self.bot,lambda:40)
        self.bot.delete_message.assert_not_awaited()
        self.assertEqual(self.ids(),[38,39,42,43,44])

    async def test_restart_and_rollback_old_reader_ignore_additive_table(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'db.sqlite3'
            db=sqlite3.connect(p,isolation_level=None)
            c=AdminChatCleanup(db,99);c.track_registration_notice(7,40,NOW-86400);c.track_registration_notice(7,42,NOW)
            # Existing queue history retains its exact schema for older versions.
            self.assertEqual([x[1] for x in db.execute('PRAGMA table_info(admin_response_history)')],
                             ['owner','bot','message','category','sent_at'])
            db.close();db=sqlite3.connect(p,isolation_level=None)
            try:
                c=AdminChatCleanup(db,99);await c.drain(self.bot,None)
                self.assertEqual(db.execute('SELECT message FROM admin_registration_notice_history').fetchall(),[(42,)])
            finally:db.close()

    async def test_failed_delete_is_durable_and_permanent_failure_never_removes_latest(self):
        self.add(40,86400);self.add(42,0)
        self.bot.delete_message.side_effect=TimedOut()
        await self.c.drain(self.bot,None)
        self.assertEqual(self.ids(),[40,42])
        self.c.retry_at=0;self.bot.delete_message.side_effect=BadRequest("Message can't be deleted")
        await self.c.drain(self.bot,None)
        self.assertEqual(self.ids(),[42])

class NoticeDeliveryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.CoordinatorTests.asyncSetUp
    asyncTearDown=fixtures.CoordinatorTests.asyncTearDown

    def sent(self,**changes):
        vals=dict(message_id=80,chat=SimpleNamespace(id=99,type='private'),from_user=SimpleNamespace(id=7),
                  date=datetime.now(timezone.utc))
        vals.update(changes);return SimpleNamespace(**vals)

    async def fail_request(self):
        c=self.coordinator;c.paused=False;self.bot.id=7
        c.request_personal_data=AsyncMock(return_value=object())
        browser=SimpleNamespace(create_account=AsyncMock(side_effect=worker.RegistrationError('Synthetic uncertainty')))
        self.bot.send_message.side_effect=None;self.bot.send_message.return_value=self.sent()
        with patch.object(worker,'RegistrationBrowser',return_value=browser):await c.process_request(self.request)
        return browser

    async def test_only_delivered_error_notice_tracked_and_queue_still_recoverable(self):
        browser=await self.fail_request()
        self.assertEqual(self.request.status,'ERRORE')
        self.assertIsNone(self.coordinator.active)
        self.bot.send_message.assert_awaited_once()
        self.assertIn('Esito della registrazione Libero da verificare',self.bot.send_message.call_args.kwargs['text'])
        self.assertEqual(self.coordinator.outcomes.db.execute('SELECT message FROM admin_registration_notice_history').fetchall(),[(80,)])
        self.assertEqual(self.coordinator.outcomes.ids(),set())
        browser.create_account.assert_awaited_once()

    async def test_metadata_failure_never_resends_notice_or_restarts_registration(self):
        self.coordinator.outcomes.db.execute('DROP TABLE admin_registration_notice_history')
        browser=await self.fail_request()
        self.bot.send_message.assert_awaited_once();browser.create_account.assert_awaited_once()
        self.assertEqual(self.request.status,'ERRORE')
        self.assertIsNone(self.coordinator.active)

    async def test_invalid_sender_chat_date_and_message_never_tracked(self):
        self.bot.id=7
        for m in [self.sent(chat=SimpleNamespace(id=98,type='private')),
                  self.sent(chat=SimpleNamespace(id=99,type='group')),
                  self.sent(from_user=SimpleNamespace(id=8)),self.sent(date=datetime.now()),
                  self.sent(message_id=True),self.sent(message_id=0)]:
            self.coordinator.track_registration_notice(m)
        self.assertEqual(self.coordinator.outcomes.db.execute('SELECT message FROM admin_registration_notice_history').fetchall(),[])
