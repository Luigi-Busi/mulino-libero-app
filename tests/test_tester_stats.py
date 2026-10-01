import asyncio
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from test_regressions import worker
import test_telegram_panel as fixtures


def request(key='new', tester='11'):
    return worker.QueueRequest(2, key, 'IN_CREAZIONE', 'sheet', 'tab', 4, 3, '', claimed_by=tester)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.outcomes = worker.CreatedOutcomes()
        self.addCleanup(self.outcomes.close)
        self.ledger = self.outcomes.testers

    def save(self, key='new', tester=11):
        self.outcomes.save(request(key, str(tester)), 'fixture', 'fixture@libero.it',
                           sms_proof=(tester, self.ledger.now()))

    def test_success_without_sms_or_manual_recovery_never_credits_assignment(self):
        self.outcomes.save(request(), 'fixture', 'fixture@libero.it')
        self.assertEqual(self.ledger.stats(11)['count'], 0)
        self.save()  # A pre-existing outcome must never be retroactively credited.
        self.assertEqual(self.ledger.stats(11)['count'], 0)

    def test_completion_and_credit_are_once_even_after_sync_and_reset(self):
        self.save()
        self.outcomes.completed('new')
        self.save()
        self.assertEqual(self.ledger.stats(11)['count'], 1)
        self.ledger.reset(11, 99, self.ledger.stats(11)['snapshot'])
        self.save()
        self.assertEqual(self.ledger.stats(11)['count'], 0)
        self.assertEqual(self.ledger.stats(11)['total'], 1)
        self.save('second')
        self.assertEqual(self.ledger.stats(11)['count'], 1)

    def test_reset_only_one_tester_preserves_history_and_other_counts(self):
        self.save('first', 11)
        self.save('second', 22)
        before = self.ledger.stats(11)
        self.ledger.reset(11, 99, before['snapshot'])
        self.assertEqual(self.ledger.stats(11)['count'], 0)
        self.assertEqual(self.ledger.stats(11)['total'], 1)
        self.assertEqual(self.ledger.stats(22)['count'], 1)
        self.assertEqual(self.outcomes.ids(), {'first', 'second'})

    def test_new_completion_invalidates_confirmation_and_reset_replay(self):
        self.save()
        snapshot = self.ledger.stats(11)['snapshot']
        self.save('newer')
        with self.assertRaises(worker.RegistrationError):
            self.ledger.reset(11, 99, snapshot)
        current = self.ledger.stats(11)['snapshot']
        self.ledger.reset(11, 99, current)
        with self.assertRaises(worker.RegistrationError):
            self.ledger.reset(11, 99, current)
        self.assertEqual(self.outcomes.db.execute('SELECT COUNT(*) FROM tester_resets').fetchone()[0], 1)

    def test_credit_failure_rolls_back_outcome_and_retry_commits_both(self):
        self.outcomes.db.execute("CREATE TRIGGER fail_credit BEFORE INSERT ON tester_completions BEGIN SELECT RAISE(ABORT,'TEST-SECRET'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.save()
        self.assertEqual(self.outcomes.ids(), set())
        self.assertEqual(self.ledger.stats(11)['count'], 0)
        self.outcomes.db.execute('DROP TRIGGER fail_credit')
        self.save()
        self.assertEqual(self.ledger.stats(11)['count'], 1)

    def test_invalid_or_mismatching_proof_never_creates_outcome(self):
        for proof in ((True, self.ledger.now()), (22, self.ledger.now()), (11, 'invalid')):
            with self.assertRaises((ValueError, worker.RegistrationError)):
                self.outcomes.save(request(), 'fixture', 'fixture@libero.it', sms_proof=proof)
            self.assertEqual(self.outcomes.ids(), set())

    def test_restart_preserves_count_reset_and_counting_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = worker.CreatedOutcomes(root)
            first.save(request(), 'fixture', 'fixture@libero.it', sms_proof=(11, first.testers.now()))
            start = first.testers.stats(11)['started']
            first.testers.reset(11, 99, first.testers.stats(11)['snapshot'])
            first.close()
            second = worker.CreatedOutcomes(root)
            self.addCleanup(second.close)
            self.assertEqual(second.testers.stats(11)['count'], 0)
            self.assertEqual(second.testers.stats(11)['total'], 1)
            self.assertIn(11, second.testers.known_ids())
            self.assertEqual(second.db.execute("SELECT value FROM runtime_settings WHERE key='tester_counting_started'").fetchone()[0], start)


class AttributionTests(unittest.IsolatedAsyncioTestCase):
    def coordinator(self):
        c = worker.Coordinator(SimpleNamespace(admin_id=99), SimpleNamespace())
        self.addCleanup(c.outcomes.close)
        self.addCleanup(c.messages.close)
        return c

    async def test_current_tester_only_and_credit_does_not_wait_for_sheets(self):
        c = self.coordinator()
        r = request(tester='22')
        c.active = r
        c.assigned_phone = 'synthetic'
        c.revoked_testers.add(11)
        c.mark_sms_verified(r)
        c.record_created(r, 'fixture', 'fixture@libero.it')
        self.assertEqual(c.outcomes.testers.stats(22)['count'], 1)
        self.assertEqual(c.outcomes.testers.stats(11)['count'], 0)
        self.assertEqual(c.outcomes.pending_count(), 1)
        c.record_created(r, 'fixture', 'fixture@libero.it')
        self.assertEqual(c.outcomes.testers.stats(22)['count'], 1)

    async def test_assignment_alone_wrong_active_or_revoked_never_proves_sms(self):
        c = self.coordinator()
        r = request()
        c.active = r
        for active, phone, revoked in ((r, '', set()), (None, 'synthetic', set()), (r, 'synthetic', {11})):
            c.active, c.assigned_phone, c.revoked_testers = active, phone, revoked
            with self.assertRaises(worker.RegistrationError):
                c.mark_sms_verified(r)
        self.assertEqual(c.sms_verified, {})

    async def test_real_otp_loop_counts_only_recognized_success_after_retries(self):
        c = self.coordinator()
        r = request()
        c.active, c.assigned_phone = r, 'synthetic'
        c.request_otp = AsyncMock(return_value='123456')
        c.retry_otp = AsyncMock()
        c.set_queue_fields = AsyncMock()
        b = worker.RegistrationBrowser(SimpleNamespace(), c)
        b.page = SimpleNamespace()
        b._check_cancelled = AsyncMock()
        b._wait_for_otp_input = AsyncMock(return_value=SimpleNamespace(fill=AsyncMock()))
        b._otp_feedback = AsyncMock(return_value=None)
        b._click_first_button = AsyncMock()
        b._wait_for_otp_outcome = AsyncMock(side_effect=['invalid', 'expired', 'success'])
        await b._verify_sms_until_completed(r)
        self.assertEqual(c.retry_otp.await_count, 2)
        self.assertEqual(c.outcomes.testers.stats(11)['count'], 0)
        c.record_created(r, 'fixture', 'fixture@libero.it')
        self.assertEqual(c.outcomes.testers.stats(11)['count'], 1)

    async def test_closed_browser_during_otp_never_credits(self):
        c = self.coordinator()
        r = request()
        c.active, c.assigned_phone = r, 'synthetic'
        c.request_otp = AsyncMock(return_value='123456')
        c.set_queue_fields = AsyncMock()
        b = worker.RegistrationBrowser(SimpleNamespace(), c)
        b.page = SimpleNamespace()
        b._check_cancelled = AsyncMock()
        b._wait_for_otp_input = AsyncMock(return_value=SimpleNamespace(fill=AsyncMock()))
        b._otp_feedback = AsyncMock(return_value=None)
        b._click_first_button = AsyncMock()
        b._wait_for_otp_outcome = AsyncMock(side_effect=worker.PlaywrightError('closed'))
        with self.assertRaises(worker.PlaywrightError):
            await b._verify_sms_until_completed(r)
        self.assertFalse(c.sms_verified)

    async def test_failed_atomic_save_retains_proof_for_recovery(self):
        c = self.coordinator()
        r = request()
        c.active, c.assigned_phone = r, 'synthetic'
        c.mark_sms_verified(r)
        with patch.object(c.outcomes, 'save', side_effect=sqlite3.OperationalError('failure')):
            with self.assertRaises(sqlite3.OperationalError):
                c.record_created(r, 'fixture', 'fixture@libero.it')
        self.assertIn(r.request_id, c.created_in_memory)
        c.record_created(r, 'fixture', 'fixture@libero.it')
        self.assertEqual(c.outcomes.testers.stats(11)['count'], 1)
        self.assertFalse(c.sms_verified)


class TesterPanelTests(unittest.IsolatedAsyncioTestCase):
    setup_panel = fixtures.PanelTests.setup_panel
    callback = fixtures.PanelTests.callback
    opened = fixtures.PanelTests.opened

    async def fixture(self):
        c, u, ctx, m = await self.opened()
        o = worker.CreatedOutcomes()
        self.addCleanup(o.close)
        c.outcomes = o
        c.store.whitelist_map.return_value = {11: 'PRIVATE-PHONE', 22: 'OTHER-PHONE'}
        o.save(request(), 'fixture', 'fixture@libero.it', sms_proof=(11, o.testers.now()))
        return c, u, ctx, m

    async def click(self, u, m, ctx, action):
        q = self.callback(u, m, action)
        await worker.callback_handler(u, ctx)
        return q

    async def test_list_detail_reset_confirmation_and_replay_reuse_one_message(self):
        c,u,ctx,m = await self.fixture()
        await self.click(u,m,ctx,'testers')
        self.assertNotIn('PRIVATE-PHONE', c.bot.edit_message_text.call_args.kwargs['text'])
        await self.click(u,m,ctx,'tester_select_0')
        self.assertIn('Operazioni completate: 1', c.bot.edit_message_text.call_args.kwargs['text'])
        await self.click(u,m,ctx,'tester_reset')
        self.assertEqual(c.outcomes.testers.stats(11)['count'], 1)
        q = await self.click(u,m,ctx,'tester_reset_yes')
        await worker.callback_handler(u,ctx)
        self.assertEqual(c.outcomes.testers.stats(11)['count'], 0)
        self.assertEqual(c.outcomes.db.execute('SELECT COUNT(*) FROM tester_resets').fetchone()[0],1)
        c.bot.send_message.assert_awaited_once()
        m.reply_text.assert_not_awaited()

    async def test_confirmation_does_not_reset_new_completion(self):
        c,u,ctx,m = await self.fixture()
        await self.click(u,m,ctx,'testers')
        await self.click(u,m,ctx,'tester_select_0')
        await self.click(u,m,ctx,'tester_reset')
        c.outcomes.save(request('late'), 'fixture', 'fixture@libero.it', sms_proof=(11,c.outcomes.testers.now()))
        await self.click(u,m,ctx,'tester_reset_yes')
        self.assertEqual(c.outcomes.testers.stats(11)['count'], 2)
        self.assertIn('Conteggio cambiato',c.bot.edit_message_text.call_args.kwargs['text'])

    async def test_cancel_forged_other_user_and_expired_reset_have_no_effect(self):
        for condition in ('cancel', 'forged', 'other', 'expired', 'wrong_chat', 'forwarded', 'restart'):
            c,u,ctx,m = await self.fixture()
            await self.click(u,m,ctx,'testers')
            await self.click(u,m,ctx,'tester_select_0')
            if condition != 'forged':
                await self.click(u,m,ctx,'tester_reset')
            q = self.callback(u,m,'tester_detail' if condition == 'cancel' else 'tester_reset_yes')
            if condition == 'other': q.from_user.id = 11
            if condition == 'expired': next(iter(c.panel_sessions.entries.values()))['expires'] = 0
            if condition == 'wrong_chat': q.message.chat.id = 11
            if condition == 'forwarded': q.message.message_id = 43
            if condition == 'restart': c.panel_sessions = worker.PanelSessions()
            await worker.callback_handler(u,ctx)
            self.assertEqual(c.outcomes.testers.stats(11)['count'],1)

    async def test_commands_only_private_owner_invalid_ids_and_unknown_are_safe(self):
        c,u,ctx,m = await self.fixture()
        for text,args in (('/conteggio',['11']),('/azzera',['11']),('/conteggi',[])):
            m.text, ctx.args = text, args
            await worker.tester_command(u,ctx)
        self.assertEqual(c.outcomes.testers.stats(11)['count'],1)
        for args in ([], ['11','22'], ['0'], ['-11'], ['<SECRET>'], ['9999999999999999999'], ['44']):
            m.text, ctx.args = '/azzera', args
            await worker.tester_command(u,ctx)
        self.assertNotIn('<SECRET>',c.bot.edit_message_text.call_args.kwargs['text'])
        before=c.bot.edit_message_text.await_count
        for user,chat,kind in ((11,11,'private'),(99,-1,'group'),(99,11,'private')):
            u.effective_user.id=user
            m.chat.id,m.chat.type=chat,kind
            await worker.tester_command(u,ctx)
        self.assertEqual(before,c.bot.edit_message_text.await_count)
        c.bot.send_message.assert_awaited_once()

    async def test_pagination_and_missing_whitelist_keep_history(self):
        c,u,ctx,m = await self.fixture()
        c.store.whitelist_map.return_value={i:'PRIVATE-PHONE' for i in range(1,26)}
        await self.click(u,m,ctx,'testers')
        self.assertIn('Pagina 1/3', c.bot.edit_message_text.call_args.kwargs['text'])
        await self.click(u,m,ctx,'tester_next')
        self.assertIn('Pagina 2/3', c.bot.edit_message_text.call_args.kwargs['text'])
        await self.click(u,m,ctx,'tester_prev')
        c.store.whitelist_map.side_effect=RuntimeError('PRIVATE-PHONE')
        await self.click(u,m,ctx,'testers')
        text=c.bot.edit_message_text.call_args.kwargs['text']
        self.assertIn('Whitelist non raggiungibile',text)
        self.assertNotIn('PRIVATE-PHONE',text)
        await self.click(u,m,ctx,'tester_select_0')
        self.assertIn('ID 11',c.bot.edit_message_text.call_args.kwargs['text'])

    async def test_storage_failure_never_reports_successful_reset(self):
        c,u,ctx,m = await self.fixture()
        await self.click(u,m,ctx,'testers')
        await self.click(u,m,ctx,'tester_select_0')
        await self.click(u,m,ctx,'tester_reset')
        with patch.object(c.outcomes.testers,'reset',side_effect=sqlite3.OperationalError('TEST-SECRET')):
            await self.click(u,m,ctx,'tester_reset_yes')
        text=c.bot.edit_message_text.call_args.kwargs['text']
        self.assertIn('non disponibile',text)
        self.assertNotIn('TEST-SECRET',text)
        self.assertEqual(c.outcomes.testers.stats(11)['count'],1)
