"""Explicit expiration: synthetic HTML, identities, Telegram and Sheets only."""
import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace

import test_regressions as fixtures
import test_tester_timeout as browser_fixtures
from test_regressions import worker

BANNER = 'Tempo di registrazione scaduto. Inizia una nuova registrazione.'


class ExpiredBrowserTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = browser_fixtures.BrowserFormTests.asyncSetUp
    asyncTearDown = browser_fixtures.BrowserFormTests.asyncTearDown

    async def screen(self, banner=BANNER, hidden=False, otp=False, host='registrazione.libero.it'):
        html = ('<div ' + ('hidden' if hidden else '') + '>' + banner + '</div>'
                '<input id="username"><input id="password" type="password">'
                '<button onclick="window.clicked=true">Avanti</button>')
        if otp:
            html += '<label>Codice SMS<input id="otp"></label>'
        await self.page.route('**/*', lambda route: route.fulfill(body=html, content_type='text/html'))
        await self.page.goto('https://' + host + '/')

    async def test_explicit_banner_and_initial_fields_raise_without_click(self):
        await self.screen()
        with self.assertRaises(worker.RegistrationExpired):
            await self.b._check_cancelled()
        self.assertIsNone(await self.page.evaluate('window.clicked'))

    async def test_hidden_banner_does_not_authorize_restart(self):
        await self.screen(hidden=True)
        await self.b._check_cancelled()

    async def test_banner_on_another_host_does_not_authorize_restart(self):
        await self.screen(host='example.test')
        await self.b._check_cancelled()

    async def test_visible_otp_prevents_restart_from_underlying_form(self):
        await self.screen(otp=True)
        await self.b._check_cancelled()

    async def test_generic_reset_still_requires_review(self):
        await self.screen(banner='Sessione terminata')
        with self.assertRaises(worker.RegistrationSessionReset) as caught:
            await self.b._assert_phone_session()
        self.assertNotIsInstance(caught.exception, worker.RegistrationExpired)

    async def test_captcha_wait_detects_expiration_even_with_unchanged_url(self):
        await self.screen()
        with self.assertRaises(worker.RegistrationExpired):
            await self.b._captcha_resume_ready(self.page.url)


class ExpiredCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.CoordinatorTests.asyncSetUp
    asyncTearDown = fixtures.CoordinatorTests.asyncTearDown

    def prepare(self):
        c = self.coordinator
        c.paused = False
        c.request_personal_data = AsyncMock(return_value=object())
        c.record_created = Mock()
        c.sync_outcome = AsyncMock(return_value=True)
        return c

    async def test_restarts_same_person_in_new_browser_without_new_personal_prompt(self):
        c = self.prepare()
        first = SimpleNamespace(create_account=AsyncMock(side_effect=worker.RegistrationExpired(BANNER)))
        second = SimpleNamespace(create_account=AsyncMock(return_value=('synthetic', 'synthetic@example.test')))
        with patch.object(worker, 'RegistrationBrowser', side_effect=[first, second]) as factory:
            await c.process_request(self.request)
        self.assertEqual(factory.call_count, 2)
        c.request_personal_data.assert_awaited_once()
        self.assertEqual(first.create_account.call_args, second.create_account.call_args)
        c.record_created.assert_called_once()
        self.assertTrue(any('ripartenza automatica 1/2' in f.get('NOTE', '') for f in self.writes))

    async def test_two_restarts_maximum_then_manual_review_without_credit(self):
        c = self.prepare()
        browser = SimpleNamespace(create_account=AsyncMock(side_effect=worker.RegistrationExpired(BANNER)))
        with patch.object(worker, 'RegistrationBrowser', return_value=browser) as factory:
            await c.process_request(self.request)
        self.assertEqual(factory.call_count, 3)
        self.assertEqual(self.request.status, 'ERRORE')
        c.record_created.assert_not_called()
        self.assertEqual(c.outcomes.testers.stats(11)['count'], 0)
        self.assertIsNone(c.active)

    async def test_generic_reset_does_not_restart(self):
        c = self.prepare()
        browser = SimpleNamespace(create_account=AsyncMock(side_effect=worker.RegistrationSessionReset('reset')))
        with patch.object(worker, 'RegistrationBrowser', return_value=browser) as factory:
            await c.process_request(self.request)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(self.request.status, 'ERRORE')

    async def test_cancellation_during_restart_wins(self):
        c = self.prepare()
        original = c.restart_expired_registration
        async def restart(*args):
            await original(*args)
            c.cancel_event.set()
        c.restart_expired_registration = restart
        browser = SimpleNamespace(create_account=AsyncMock(side_effect=worker.RegistrationExpired(BANNER)))
        with patch.object(worker, 'RegistrationBrowser', return_value=browser) as factory:
            await c.process_request(self.request)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(self.request.status, 'ANNULLATA')

    async def test_restart_invalidates_old_claim_and_sms_state(self):
        c = self.prepare()
        await c.claim_phone(11)
        await c.notify_otp_sent(self.request, 11, '+393330000011')
        old_token = c.assignment_token
        old_future = c.otp_future
        c.resend_event.set()
        await c.restart_expired_registration(self.request, 1)
        self.assertEqual(self.request.claimed_by, '')
        self.assertEqual(c.assignment_token, '')
        self.assertEqual(c.claim_token, '')
        self.assertFalse(c.resend_event.is_set())
        self.assertTrue(old_future.cancelled())
        self.assertFalse(c.queue_sms_resend(self.request.request_id, 11, token=old_token)[0])

    async def test_verified_sms_prevents_automatic_restart(self):
        c = self.prepare()
        async def expired(*args):
            c.sms_verified[self.request.request_id] = 11
            raise worker.RegistrationExpired(BANNER)
        with patch.object(worker, 'RegistrationBrowser', return_value=SimpleNamespace(create_account=expired)) as factory:
            await c.process_request(self.request)
        self.assertEqual(factory.call_count, 1)
        c.record_created.assert_not_called()

    async def test_pause_arriving_during_restart_prevents_new_browser(self):
        c = self.prepare()
        original = c.restart_expired_registration
        async def restart(*args):
            await original(*args)
            c.paused = True
        c.restart_expired_registration = restart
        browser = SimpleNamespace(create_account=AsyncMock(side_effect=worker.RegistrationExpired(BANNER)))
        with patch.object(worker, 'RegistrationBrowser', return_value=browser) as factory:
            await c.process_request(self.request)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(self.request.status, 'ERRORE')

    async def test_stable_destination_is_revalidated_before_restart(self):
        c = self.prepare()
        self.request.account_id = 'synthetic-id'
        self.store.validate_start = Mock(side_effect=[None, worker.RegistrationError('Destinazione modificata')])
        browser = SimpleNamespace(create_account=AsyncMock(side_effect=worker.RegistrationExpired(BANNER)))
        with patch.object(worker, 'RegistrationBrowser', return_value=browser) as factory:
            await c.process_request(self.request)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(self.store.validate_start.call_count, 2)
        self.assertEqual(self.request.status, 'ERRORE')
