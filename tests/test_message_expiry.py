import sqlite3
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from telegram import User
from telegram.ext import Application, ExtBot
from telegram.error import TimedOut
from telegram_panel import AdminChatCleanup
from admin_message_observer import CleanupBot, observe_message, observe_incoming, NOTICE_PREFIXES

NOW = 1800000000


class ExpiryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:', isolation_level=None)
        self.addCleanup(self.db.close)
        self.c = AdminChatCleanup(self.db, 99)
        self.bot = NS(id=7, delete_message=AsyncMock(return_value=True))
        self.clock = patch('telegram_panel.time.time', return_value=NOW)
        self.clock.start(); self.addCleanup(self.clock.stop)

    def msg(self, mid, sender=99, chat=99, text='', kind='private'):
        return NS(message_id=mid, chat=NS(id=chat,type=kind), from_user=NS(id=sender),
                  date=datetime.fromtimestamp(NOW,timezone.utc),text=text)

    def header(self, mid=40):
        self.c.track_recovery(7,mid,'a'*16,'list')
        self.c.track_recovery_header(7,mid)

    async def test_exact_five_mixed_messages_with_gaps_duplicates_and_restart(self):
        self.header()
        for mid, sender in [(51,99),(100,7),(143,99),(180,7)]:
            m=self.msg(mid,sender)
            observe_message(self.c,7,m,outgoing=sender==7)
            observe_message(self.c,7,m,outgoing=sender==7)
        self.c=AdminChatCleanup(self.db,99)
        await self.c.drain(self.bot,None)
        self.bot.delete_message.assert_not_awaited()
        observe_message(self.c,7,self.msg(200,7),outgoing=True)
        await self.c.drain(self.bot,None)
        self.assertEqual([x.kwargs['message_id'] for x in self.bot.delete_message.call_args_list],[40])

    async def test_no_other_chat_sender_callback_or_edits_count(self):
        self.header()
        for mid in range(41,46):
            observe_message(self.c,7,self.msg(mid,chat=98))
            observe_message(self.c,7,self.msg(mid,sender=98))
            observe_message(self.c,7,self.msg(mid,kind='group'))
        await self.c.drain(self.bot,None)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM admin_chat_observed').fetchone()[0],0)
        self.bot.delete_message.assert_not_awaited()

    async def test_cards_confirmation_and_legacy_lists_expire_at_button_deadline(self):
        self.header()
        self.c.track_recovery(7,41,'a'*16,'list')
        self.c.track_recovery(7,42,'a'*16,'confirm')
        self.db.execute('UPDATE admin_recovery_messages SET delete_at=0 WHERE message=41')
        with patch('telegram_panel.time.time',return_value=NOW+599):
            await self.c.drain(self.bot,None)
        self.bot.delete_message.assert_not_awaited()
        with patch('telegram_panel.time.time',return_value=NOW+600):
            await self.c.drain(self.bot,None)
        self.assertEqual([x.kwargs['message_id'] for x in self.bot.delete_message.call_args_list],[40,41,42])

    async def test_header_count_does_not_delete_cards_other_headers_or_current_panel(self):
        self.header(); self.header(100)
        self.c.track_recovery(7,42,'a'*16,'list')
        for mid in range(51,56):self.c.observe_message(7,mid,NOW)
        await self.c.drain(self.bot,None)
        self.assertEqual([x.kwargs['message_id'] for x in self.bot.delete_message.call_args_list],[40])
        self.assertEqual(self.db.execute('SELECT message FROM admin_recovery_messages ORDER BY message').fetchall(),[(42,),(100,)])

    async def test_all_six_notice_types_expire_at_12h_including_last(self):
        for i,prefix in enumerate(NOTICE_PREFIXES):
            observe_message(self.c,7,self.msg(40+i,7,text=prefix+' fixture'),outgoing=True)
        observe_message(self.c,7,self.msg(55,7,text='✅ Libero Mail creata: fixture'),outgoing=True)
        with patch('telegram_panel.time.time',return_value=NOW+43199):await self.c.drain(self.bot,None)
        self.bot.delete_message.assert_not_awaited()
        with patch('telegram_panel.time.time',return_value=NOW+43200):await self.c.drain(self.bot,None)
        self.assertEqual([x.kwargs['message_id'] for x in self.bot.delete_message.call_args_list],list(range(40,46)))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM admin_registration_notice_history').fetchone()[0],0)

    async def test_deletion_failure_persists_without_resend(self):
        self.header()
        for mid in range(41,46):self.c.observe_message(7,mid,NOW)
        self.bot.delete_message.side_effect=TimedOut()
        await self.c.drain(self.bot,None)
        self.assertEqual(self.db.execute('SELECT message FROM admin_recovery_messages').fetchall(),[(40,)])
        self.bot.delete_message.side_effect=None;self.c.retry_at=0
        await self.c.drain(self.bot,None)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM admin_recovery_messages').fetchone()[0],0)

    async def test_outgoing_real_bot_wrapper_and_storage_failure_do_not_resend(self):
        b=CleanupBot('123:fixture');b._bot_user=User(7,'fixture',True)
        b.attach_cleanup(self.c)
        sent=self.msg(40,7,text=NOTICE_PREFIXES[0])
        with patch.object(ExtBot,'send_message',new=AsyncMock(return_value=sent)) as send:
            self.assertIs(await b.send_message(chat_id=99,text=sent.text),sent)
            self.db.execute('DROP TABLE admin_chat_observed')
            self.assertIs(await b.send_message(chat_id=99,text=sent.text),sent)
            self.assertEqual(send.await_count,2)
        # Same bot instance is used by handlers, polling and coordinator.
        app=Application.builder().bot(b).build()
        self.assertIs(app.bot,b)

    async def test_incoming_handler_counts_media_only_new_messages(self):
        ctx=NS(application=NS(bot_data={'coordinator':NS(bot=self.bot,panel=NS(cleanup=self.c,message_id=lambda _:None))}))
        await observe_incoming(NS(message=self.msg(40)),ctx)
        await observe_incoming(NS(message=None),ctx)
        self.assertEqual(self.db.execute('SELECT message FROM admin_chat_observed').fetchall(),[(40,)])
        self.bot.delete_message.assert_not_awaited()

    async def test_old_uneditable_panel_is_retired_after_replacement(self):
        import test_telegram_panel as panels
        from test_regressions import worker
        from telegram.error import BadRequest
        c,u,ctx,m=panels.PanelTests.setup_panel(self)
        c.panel.bind(7,40)
        c.bot.edit_message_text.side_effect=BadRequest("Message can't be edited")
        await worker.render_admin_panel(c,None)
        await c.panel.cleanup.drain(c.bot,lambda:c.panel.message_id(7))
        self.assertEqual(c.panel.message_id(7),42)
        self.assertEqual(c.bot.delete_message.call_args.kwargs['message_id'],40)


if __name__ == '__main__':unittest.main()
