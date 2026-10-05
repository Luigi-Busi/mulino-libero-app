import asyncio
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from telegram.error import TimedOut
from telegram_panel import AdminChatCleanup
from test_regressions import worker

NOW = 1800000000
BATCH = 'a' * 16


class RecoveryCleanupAgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = sqlite3.connect(':memory:', isolation_level=None)
        self.c = AdminChatCleanup(self.db, 99)
        self.bot = SimpleNamespace(id=7, delete_message=AsyncMock(return_value=True))
        self.clock = patch('telegram_panel.time.time', return_value=NOW)
        self.clock.start()

    async def asyncTearDown(self):
        self.clock.stop()
        self.db.close()

    async def test_usage_removed_at_thirty_minutes_without_command(self):
        self.c.track_recovery(7, 40, BATCH, 'usage')
        with patch('telegram_panel.time.time', return_value=NOW + 1799):
            await self.c.drain(self.bot, None)
        self.bot.delete_message.assert_not_awaited()
        with patch('telegram_panel.time.time', return_value=NOW + 1800):
            await self.c.drain(self.bot, None)
        self.assertEqual(self.bot.delete_message.call_args.kwargs['message_id'], 40)

    async def test_batch_cleanup_only_deletes_its_list_and_confirmation(self):
        for message, batch, kind in ((40,BATCH,'list'),(41,BATCH,'confirm'),
                                      (42,'b'*16,'list'),(43,'c'*16,'usage')):
            self.c.track_recovery(7, message, batch, kind)
        self.c.finish_recovery(7, BATCH)
        await self.c.drain(self.bot, None)
        self.assertEqual([c.kwargs['message_id'] for c in self.bot.delete_message.call_args_list], [40,41])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM admin_recovery_messages').fetchone()[0], 2)

    async def test_one_ignored_card_does_not_delete_other_cards(self):
        self.c.track_recovery(7, 40, BATCH, 'list')
        self.c.track_recovery(7, 41, BATCH, 'list')
        self.c.finish_recovery(7, BATCH, message=40)
        await self.c.drain(self.bot, None)
        self.bot.delete_message.assert_awaited_once()
        self.assertEqual(self.bot.delete_message.call_args.kwargs['message_id'],40)

    async def test_ownership_current_panel_and_48_hour_limit_are_protected(self):
        self.c.track_recovery(7,40,BATCH,'usage')
        self.c.track_recovery(8,41,BATCH,'usage')
        AdminChatCleanup(self.db,11).track_recovery(7,42,BATCH,'usage')
        self.c.finish_recovery(7,BATCH)
        await self.c.drain(self.bot,40)
        self.bot.delete_message.assert_not_awaited()
        with patch('telegram_panel.time.time',return_value=NOW-172800):
            self.c.track_recovery(7,43,BATCH,'usage')
        await self.c.drain(self.bot,None)
        self.bot.delete_message.assert_not_awaited()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM admin_recovery_messages').fetchone()[0],2)

    async def test_deferred_deletion_survives_restart_and_retries_without_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.sqlite3'
            db=sqlite3.connect(path,isolation_level=None)
            c=AdminChatCleanup(db,99)
            c.track_recovery(7,40,BATCH,'usage')
            db.close()
            db=sqlite3.connect(path,isolation_level=None)
            try:
                c=AdminChatCleanup(db,99)
                self.bot.delete_message.side_effect=TimedOut()
                with patch('telegram_panel.time.time',return_value=NOW+1800):
                    await c.drain(self.bot,None)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM admin_recovery_messages').fetchone()[0],1)
                    self.bot.delete_message.side_effect=None
                    c.retry_at=0
                    await c.drain(self.bot,None)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM admin_recovery_messages').fetchone()[0],0)
            finally:
                db.close()


class RecoveryFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests=[worker.QueueRequest(i+2,f'fixture-{i}','ANNULLATA','sheet','Synthetic',i+3,3,'Fixture')
                       for i in range(3)]
        self.sent=[]
        self.store=SimpleNamespace(_read_requests=Mock(side_effect=lambda:list(self.requests)),
            find_request=Mock(side_effect=lambda rid:next((r for r in self.requests if r.request_id==rid),None)),
            retry=Mock(return_value=True),
            existing_created_details=Mock(side_effect=lambda rid:(self.store.find_request(rid),'fixture','fixture@libero.it')))
        self.c=worker.Coordinator(SimpleNamespace(admin_id=99,group_chat_id=-100),self.store)
        self.bot=SimpleNamespace(id=7,delete_message=AsyncMock(return_value=True))
        self.c.application=SimpleNamespace(bot=self.bot)
        self.c.sync_outcome=AsyncMock(return_value=True)
        self.source=self.message(1)
        self.u=SimpleNamespace(effective_user=SimpleNamespace(id=99),
            effective_chat=SimpleNamespace(id=99,type='private'),effective_message=self.source)
        self.context=SimpleNamespace(args=[],application=SimpleNamespace(bot_data={'coordinator':self.c}))

    def message(self,mid):
        return SimpleNamespace(message_id=mid,chat=SimpleNamespace(id=99,type='private'),
            reply_text=AsyncMock(side_effect=self.reply))

    async def reply(self,text,**kwargs):
        msg=self.message(len(self.sent)+100)
        msg.text,msg.markup=text,kwargs.get('reply_markup')
        self.sent.append(msg)
        return msg

    async def asyncTearDown(self):
        self.c.messages.close()
        self.c.outcomes.close()

    async def listing(self,args=None):
        self.context.args=args or []
        await worker.recovery_command(self.u,self.context)
        return list(self.sent)

    def button(self,action,*,rid=None):
        for msg in reversed(self.sent):
            if msg.markup:
                for row in msg.markup.inline_keyboard:
                    for b in row:
                        if b.callback_data.startswith(f'rec:{action}:'):
                            token=b.callback_data.split(':')[2]
                            item=self.c.recovery_buttons.get(token)
                            if item and (rid is None or item['request_id']==rid):
                                return msg,b.callback_data
        self.fail(f'button absent: {action}')

    async def click(self,action,*,rid=None,user=99):
        msg,data=self.button(action,rid=rid)
        query=SimpleNamespace(message=msg,data=data,from_user=SimpleNamespace(id=user),
                              answer=AsyncMock(),edit_message_reply_markup=AsyncMock())
        await worker.recovery_callback(SimpleNamespace(callback_query=query),self.context)
        return query

    def deleted(self):
        return [c.kwargs['message_id'] for c in self.bot.delete_message.call_args_list]

    async def test_retry_requires_confirmation_then_closes_only_its_batch(self):
        first=await self.listing()
        first_ids={m.message_id for m in first}
        await self.click('retry',rid='fixture-0')
        confirmation=self.sent[-1].message_id
        self.assertFalse(self.deleted())
        self.store.retry.assert_not_called()
        second_start=len(self.sent)
        await self.listing()
        second_ids={m.message_id for m in self.sent[second_start:]}
        await self.click('retry_yes',rid='fixture-0')
        self.store.retry.assert_called_once_with('fixture-0')
        self.assertEqual(set(self.deleted()),first_ids|{confirmation})
        self.assertTrue(second_ids.isdisjoint(self.deleted()))

    async def test_created_confirmation_keeps_list_and_never_retries(self):
        first=await self.listing()
        await self.click('created',rid='fixture-0')
        await self.click('created_yes',rid='fixture-0')
        self.assertFalse(self.deleted())
        self.store.retry.assert_not_called()
        self.assertIn('fixture-0',self.c.outcomes.ids())
        self.assertEqual(self.c.outcomes.testers.stats(11)['count'],0)

    async def test_failed_or_uncertain_retry_keeps_list_confirmation_and_warning(self):
        for failure in (False,TimeoutError('synthetic failure')):
            self.sent.clear()
            self.c.recovery_buttons.clear()
            await self.listing()
            await self.click('retry',rid='fixture-0')
            self.store.retry.side_effect=failure if isinstance(failure,Exception) else None
            self.store.retry.return_value=False
            await self.click('retry_yes',rid='fixture-0')
            self.assertFalse(self.deleted())
            self.assertIn('rileggere' if isinstance(failure,Exception) else 'non riavviata',self.sent[-1].text)

    async def test_ignore_hides_one_card_preserves_other_cards_and_restores_without_retry(self):
        await self.listing()
        ignored_msg,_=self.button('ignore',rid='fixture-0')
        await self.click('ignore',rid='fixture-0')
        self.assertEqual(self.deleted(),[ignored_msg.message_id])
        self.assertTrue(worker.recovery_ignored(self.c,self.requests[0]))
        self.store.retry.assert_not_called()
        self.assertEqual(self.requests[0].status,'ANNULLATA')
        start=len(self.sent)
        await self.listing()
        self.assertFalse(any('ID: fixture-0' in m.text for m in self.sent[start:]))
        await self.listing(['ignorate'])
        await self.click('restore',rid='fixture-0')
        self.assertFalse(worker.recovery_ignored(self.c,self.requests[0]))
        self.store.retry.assert_not_called()

    async def test_changed_request_does_not_keep_old_ignore_flag(self):
        await self.listing()
        await self.click('ignore',rid='fixture-0')
        self.requests[0].destination_row+=1
        self.assertFalse(worker.recovery_ignored(self.c,self.requests[0]))

    async def test_old_ignore_button_cannot_hide_a_newly_recorded_outcome(self):
        await self.listing()
        self.c.record_created(self.requests[0],'fixture','fixture@libero.it')
        await self.click('ignore',rid='fixture-0')
        self.assertFalse(worker.recovery_ignored(self.c,self.requests[0]))
        self.assertFalse(self.deleted())
        self.store.retry.assert_not_called()
        self.c.sync_outcome.assert_awaited_once_with('fixture-0')

    async def test_ignore_persists_across_coordinator_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=SimpleNamespace(admin_id=99,group_chat_id=-100,data_dir=Path(directory))
            c=worker.Coordinator(settings,self.store)
            signature=worker.hashlib.sha256(worker.json.dumps(worker.recovery_signature(self.requests[0])).encode()).hexdigest()
            c.outcomes.db.execute('INSERT INTO recovery_ignored VALUES (?,?)',('fixture-0',signature))
            c.messages.close();c.outcomes.close()
            c=worker.Coordinator(settings,self.store)
            try:
                self.assertTrue(worker.recovery_ignored(c,self.requests[0]))
            finally:
                c.messages.close();c.outcomes.close()

    async def test_usage_error_gets_timed_metadata(self):
        await self.listing(['oops'])
        row=self.c.outcomes.db.execute('SELECT kind,delete_at-sent_at FROM admin_recovery_messages').fetchone()
        self.assertEqual(row,('usage',1800))

    async def test_active_request_has_no_ignore_or_retry_and_pending_save_is_protected(self):
        self.c.active=self.requests[0]
        self.c.record_created(self.requests[1],'fixture','fixture@libero.it')
        await self.listing()
        actions=[v['action'] for v in self.c.recovery_buttons.values() if v['request_id']=='fixture-0']
        self.assertEqual(actions,[])
        actions=[v['action'] for v in self.c.recovery_buttons.values() if v['request_id']=='fixture-1']
        self.assertEqual(actions,['sync'])

    async def test_changed_request_or_foreign_admin_cannot_retry_or_delete(self):
        await self.listing()
        await self.click('retry',rid='fixture-0',user=11)
        self.store.retry.assert_not_called()
        self.assertFalse(self.deleted())
        await self.click('retry',rid='fixture-0')
        self.requests[0].destination_row+=1
        await self.click('retry_yes',rid='fixture-0')
        self.store.retry.assert_not_called()
        self.assertFalse(self.deleted())

    async def test_duplicate_confirmation_only_queues_once(self):
        await self.listing()
        await self.click('retry',rid='fixture-0')
        msg,data=self.button('retry_yes',rid='fixture-0')
        query=SimpleNamespace(message=msg,data=data,from_user=SimpleNamespace(id=99),
                              answer=AsyncMock(),edit_message_reply_markup=AsyncMock())
        update=SimpleNamespace(callback_query=query)
        await asyncio.gather(worker.recovery_callback(update,self.context),worker.recovery_callback(update,self.context))
        self.store.retry.assert_called_once_with('fixture-0')

    async def test_expired_button_keeps_every_message_and_does_not_mutate(self):
        await self.listing()
        with patch('mulino_test_worker.time.monotonic',return_value=worker.time.monotonic()+601):
            await self.click('retry',rid='fixture-0')
        self.store.retry.assert_not_called()
        self.assertFalse(self.deleted())
