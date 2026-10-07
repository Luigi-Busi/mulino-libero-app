import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_regressions as fixtures
from test_regressions import worker
import test_tester_timeout as browser_fixtures


class CooldownTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.CoordinatorTests.asyncSetUp
    asyncTearDown = fixtures.CoordinatorTests.asyncTearDown

    async def block(self, safe=True):
        c = self.coordinator
        c.store.find_request = Mock(return_value=self.request)
        c.store.validate_start = Mock()
        c.store.next_request = Mock(return_value=self.request)
        await c.handle_provider_cooldown(self.request, worker.RegistrationProviderCooldown(safe))

    async def test_rejection_requeues_same_request_and_preserves_operator_pause(self):
        c = self.coordinator
        c.set_paused(True)
        await self.block()
        self.assertTrue(c.paused)
        self.assertTrue(c.outcomes.queue_paused())
        self.assertEqual(self.request.status, 'DA_COMPLETARE_ANAGRAFICA')
        self.assertTrue(c.provider_waiting())
        self.assertIsNone(await c.next_request_unless_paused())
        c.set_paused(False)
        self.assertIsNone(await c.next_request_unless_paused())
        self.assertIn('Attesa Libero:', c.queue_status_text())
        c.provider_deadline = 0
        await c.reconcile_provider_cooldown()
        self.assertIs(await c.next_request_unless_paused(), self.request)
        self.assertIsNone(c.outcomes.provider_cooldown())
        self.assertFalse(c.outcomes.queue_paused())

    async def test_no_credit_and_old_phone_assignment_invalidated(self):
        c = self.coordinator
        await c.claim_phone(11)
        self.assertTrue(c.assignment_token)
        await self.block()
        self.assertEqual(c.claim_token, '')
        self.assertEqual(c.assignment_token, '')
        self.assertTrue(c.phone_future.done())
        self.assertEqual(self.request.claimed_by, '')
        self.assertEqual(c.outcomes.testers.stats(11)['count'], 0)

    async def test_uncertain_outcome_is_not_requeued(self):
        await self.block(False)
        self.assertEqual(self.request.status, 'ERRORE')
        self.assertTrue(self.coordinator.provider_waiting())

    async def test_destination_non_writable_blocks_retry(self):
        c = self.coordinator
        c.store.find_request = Mock(return_value=self.request)
        c.store.validate_start = Mock(side_effect=worker.RegistrationError('destination occupied'))
        await c.handle_provider_cooldown(self.request, worker.RegistrationProviderCooldown(True))
        self.assertEqual(self.request.status, 'ERRORE')
        self.assertFalse(c.provider_cooldown['retry'])

    async def test_recorded_outcome_never_reopens_request(self):
        c = self.coordinator
        c.outcomes.save(self.request, 'fixture', 'fixture@libero.it')
        await self.block()
        self.assertFalse(c.provider_cooldown['retry'])
        self.assertFalse(any(w.get('STATO') == 'DA_COMPLETARE_ANAGRAFICA' for w in self.writes))

    async def test_failed_google_write_stays_blocked_until_reconciled(self):
        c = self.coordinator
        c.store.find_request = Mock(return_value=self.request)
        c.store.validate_start = Mock()
        c.store.next_request = Mock(return_value=self.request)
        c.store.update = Mock(side_effect=RuntimeError('network'))
        with self.assertRaises(RuntimeError):
            await c.handle_provider_cooldown(self.request, worker.RegistrationProviderCooldown(True))
        self.assertFalse(c.outcomes.provider_cooldown()['reconciled'])
        c.provider_deadline = 0
        self.assertIsNone(await c.next_request_unless_paused())

    async def test_maximum_three_automatic_retries_then_manual_review(self):
        for i in range(4):
            await self.block()
            self.assertEqual(self.coordinator.provider_cooldown['retry'], i < 3)
        self.assertEqual(self.request.status, 'ERRORE')

    async def test_cancelled_request_is_not_resurrected(self):
        self.request.status = 'ANNULLATA'
        await self.block()
        self.assertEqual(self.request.status, 'ANNULLATA')

    async def test_save_failure_pauses_before_other_requests(self):
        c = self.coordinator
        with patch.object(c.outcomes, 'start_provider_cooldown', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                await c.handle_provider_cooldown(self.request, worker.RegistrationProviderCooldown(True))
        self.assertTrue(c.paused)
        self.assertTrue(c.outcomes.queue_paused())

    async def test_restart_preserves_timer_and_retry_without_changing_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = worker.CreatedOutcomes(Path(tmp))
            ledger.set_queue_paused(True)
            state = ledger.start_provider_cooldown('fixture', True)
            ledger.db.close()
            c = worker.Coordinator(SimpleNamespace(admin_id=99, group_chat_id=-100987, data_dir=Path(tmp)), self.store)
            try:
                self.assertTrue(c.paused)
                self.assertTrue(c.provider_waiting())
                self.assertEqual(c.provider_cooldown, state)
            finally:
                c.messages.db.close()
                c.outcomes.db.close()

    async def test_process_handles_block_without_generic_unknown_outcome(self):
        c = self.coordinator
        c.paused = False
        c.store.find_request = Mock(return_value=self.request)
        c.store.validate_start = Mock()
        c.request_personal_data = AsyncMock(return_value=object())
        b = SimpleNamespace(create_account=AsyncMock(side_effect=worker.RegistrationProviderCooldown(True)))
        with patch.object(worker, 'RegistrationBrowser', return_value=b):
            await c.process_request(self.request)
        self.assertEqual(self.request.status, 'DA_COMPLETARE_ANAGRAFICA')
        self.assertIsNone(c.active)
        self.assertTrue(c.provider_waiting())
        self.assertFalse(any('Esito della registrazione Libero da verificare' in x.kwargs.get('text','')
                             for x in self.bot.send_message.call_args_list))


class BrowserCooldownTests(browser_fixtures.BrowserFormTests):
    async def page_html(self, html):
        await self.page.route('https://registrazione.libero.it/**', lambda route: route.fulfill(body=html,content_type='text/html; charset=utf-8'))
        await self.page.goto('https://registrazione.libero.it/join3.phtml')

    async def test_visible_explicit_rejection_before_otp_is_retryable(self):
        await self.page_html("<h2>Protezione Account</h2><div>E’ stata rilevata un’attività anomala. Riprova ad eseguire l’operazione tra alcuni minuti.</div>")
        with self.assertRaises(worker.RegistrationProviderCooldown) as cm:
            await self.b._is_success_page()
        self.assertTrue(cm.exception.safe_to_retry)

    async def test_hidden_rejection_and_generic_error_do_not_trigger_cooldown(self):
        for html in ("<div hidden>attività anomala. Riprova ad eseguire l'operazione tra alcuni minuti.</div>",
                     "<div>Errore! Riprova più tardi</div>"):
            await self.page_html(html)
            await self.b._raise_if_provider_blocked()

    async def test_otp_or_success_signals_require_manual_review(self):
        for extra in ('<input id="otp" aria-label="Codice SMS">', '<p>Account creato</p>'):
            await self.page_html("<h2>Protezione Account</h2><div>attività anomala. Riprova ad eseguire l'operazione tra alcuni minuti.</div>" + extra)
            with self.assertRaises(worker.RegistrationProviderCooldown) as cm:
                await self.b._raise_if_provider_blocked()
            self.assertFalse(cm.exception.safe_to_retry)

    async def test_untrusted_page_is_never_classified_as_provider_block(self):
        await self.page.set_content("<div>attività anomala. Riprova ad eseguire l'operazione tra alcuni minuti.</div>")
        await self.b._raise_if_provider_blocked()

    async def test_phone_flow_already_started_requires_manual_review(self):
        self.b.phone_verification_started = True
        await self.page_html("<h2>Protezione Account</h2><div>attività anomala. Riprova ad eseguire l'operazione tra alcuni minuti.</div>")
        with self.assertRaises(worker.RegistrationProviderCooldown) as cm:
            await self.b._raise_if_provider_blocked()
        self.assertFalse(cm.exception.safe_to_retry)
