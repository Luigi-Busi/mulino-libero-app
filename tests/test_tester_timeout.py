"""Tester deadlines with synthetic identities and no external connections."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import test_regressions as fixtures
from test_regressions import worker


class TesterTimeoutTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.CoordinatorTests.asyncSetUp
    asyncTearDown = fixtures.CoordinatorTests.asyncTearDown
    make_update = fixtures.CoordinatorTests.make_update

    async def assigned(self):
        await self.coordinator.claim_phone(11)
        await self.coordinator.notify_otp_sent(self.request, 11, "+393330000011")
        self.coordinator.send_temporary = AsyncMock()

    async def test_first_sms_starts_five_minutes(self):
        before = asyncio.get_running_loop().time()
        await self.assigned()
        self.assertGreaterEqual(self.coordinator.tester_sms_deadline, before + 300)
        self.assertLess(self.coordinator.tester_sms_deadline, before + 301)

    async def test_pending_code_times_out_and_closes_old_acceptance(self):
        await self.assigned()
        c = self.coordinator
        c.tester_sms_deadline = asyncio.get_running_loop().time() + .02
        resend = AsyncMock()
        with self.assertRaises(worker.TesterChangeRequested):
            await asyncio.wait_for(c.request_otp(self.request, resend=resend), 1)
        self.assertTrue(c.change_tester_event.is_set())
        self.assertEqual(c.tester_change_reason, "timeout")
        self.assertFalse(c.change_tester_allowed)
        self.assertEqual(c.send_temporary.await_count, 1)
        resend.assert_not_awaited()
        await worker.text_handler(self.make_update(11, "private"), self.context)
        self.assertFalse(c.otp_future.done())
        await c.revoke_tester(self.request)
        self.assertIsNone(c.otp_future)
        self.assertIsNone(c.tester_sms_deadline)
        self.assertEqual(self.request.claimed_by, "")
        self.assertIn(11, c.revoked_testers)
        self.assertFalse((await c.claim_phone(11))[0])
        self.assertEqual(c.outcomes.testers.stats(11)["count"], 0)

    async def test_timely_code_survives_wait_starting_after_deadline(self):
        await self.assigned()
        c = self.coordinator
        await worker.text_handler(self.make_update(11, "private"), self.context)
        c.tester_sms_deadline = asyncio.get_running_loop().time() - 1
        self.assertEqual(await c.request_otp(self.request, resend=AsyncMock()), "123456")
        self.assertFalse(c.change_tester_event.is_set())

    async def test_late_code_rejected_before_timeout_loop_runs(self):
        await self.assigned()
        c = self.coordinator
        c.tester_sms_deadline = asyncio.get_running_loop().time() - 1
        await worker.text_handler(self.make_update(11, "private"), self.context)
        self.assertFalse(c.otp_future.done())
        self.assertFalse(c.queue_sms_resend(self.request.request_id, 11,
                                           token=c.assignment_token)[0])
        with self.assertRaises(worker.TesterChangeRequested):
            await c.request_otp(self.request)

    async def test_notice_failure_does_not_cancel_automatic_change(self):
        await self.assigned()
        c = self.coordinator
        c.tester_sms_deadline = asyncio.get_running_loop().time() - 1
        c.send_temporary.side_effect = worker.TelegramError("synthetic failure")
        before = asyncio.all_tasks()
        with self.assertRaises(worker.TesterChangeRequested):
            await c.request_otp(self.request, resend=AsyncMock())
        self.assertTrue(c.change_tester_event.is_set())
        self.assertFalse([t for t in asyncio.all_tasks() - before if not t.done()])

    async def test_cancellation_wins_over_code_and_deadline(self):
        await self.assigned()
        c = self.coordinator
        c.otp_future.set_result("123456")
        c.tester_sms_deadline = asyncio.get_running_loop().time() - 1
        c.cancel_event.set()
        with self.assertRaises(worker.RequestCancelled):
            await c.request_otp(self.request, resend=AsyncMock())
        c.send_temporary.assert_not_awaited()

    async def test_resend_does_not_extend_deadline(self):
        await self.assigned()
        c = self.coordinator
        deadline = asyncio.get_running_loop().time() + .05
        c.tester_sms_deadline = deadline
        c.last_sms_request_at -= 21
        self.assertTrue(c.queue_sms_resend(self.request.request_id, 11,
                                         token=c.assignment_token)[0])
        resend = AsyncMock()
        with self.assertRaises(worker.TesterChangeRequested):
            await asyncio.wait_for(c.request_otp(self.request, resend=resend), 1)
        resend.assert_awaited_once()
        self.assertEqual(c.tester_sms_deadline, deadline)
        self.assertFalse(c.resend_busy)
        self.assertFalse(c.resend_event.is_set())

    async def test_timeout_waits_for_inflight_resend_without_second_click(self):
        await self.assigned()
        c = self.coordinator
        c.tester_sms_deadline = asyncio.get_running_loop().time() + .03
        c.resend_event.set()
        async def slow_resend():
            await asyncio.sleep(.06)
            await worker.text_handler(self.make_update(11, "private"), self.context)
        resend = AsyncMock(side_effect=slow_resend)
        with self.assertRaises(worker.TesterChangeRequested):
            await asyncio.wait_for(c.request_otp(self.request, resend=resend), 1)
        resend.assert_awaited_once()
        self.assertFalse(c.otp_future.done())

    async def test_rejected_code_does_not_restart_timer(self):
        await self.assigned()
        c = self.coordinator
        deadline = c.tester_sms_deadline
        c.otp_future.set_result("wrong")
        await c.retry_otp(self.request, expired=False)
        self.assertEqual(c.tester_sms_deadline, deadline)
        self.assertFalse(c.otp_future.done())

    async def test_replacement_has_fresh_timer_and_stale_buttons_fail(self):
        await self.assigned()
        c = self.coordinator
        old_token = c.assignment_token
        old_deadline = c.tester_sms_deadline
        c.tester_change_reason = "timeout"
        await c.revoke_tester(self.request)
        c.phone_future = asyncio.get_running_loop().create_future()
        self.request.status = "ATTESA_UTENTE"
        self.assertTrue((await c.claim_phone(22))[0])
        await c.notify_otp_sent(self.request, 22, "+393330000022")
        self.assertGreater(c.tester_sms_deadline, old_deadline)
        self.assertFalse(c.queue_tester_change(self.request.request_id, 99, old_token)[0])
        self.assertFalse(c.queue_sms_resend(self.request.request_id, 11, token=old_token)[0])
        await worker.text_handler(self.make_update(11, "private"), self.context)
        self.assertFalse(c.otp_future.done())


class SafeBrowserChangeTests(unittest.IsolatedAsyncioTestCase):
    def browser(self, *, otp=False, initial=False):
        c = SimpleNamespace(revoke_tester=AsyncMock(), cancel_event=asyncio.Event())
        b = worker.RegistrationBrowser(SimpleNamespace(), c)
        b.page = SimpleNamespace(url="about:blank", is_closed=Mock(return_value=False), locator=Mock(return_value=SimpleNamespace(
            is_visible=AsyncMock(return_value=initial))))
        b._find_otp_input = AsyncMock(return_value=object() if otp else None)
        b._find_phone_input = AsyncMock(return_value=SimpleNamespace(click=AsyncMock()))
        return b, c

    async def test_initial_credentials_stop_change_without_phone_click(self):
        b, c = self.browser(initial=True)
        with self.assertRaisesRegex(worker.RegistrationError, "tornato all'inizio"):
            await b._return_to_phone_form(object())
        b._find_phone_input.assert_not_awaited()

    async def test_otp_overlay_prevents_editing_phone_behind_it(self):
        b, c = self.browser(otp=True)
        self.assertFalse(await b._phone_edit_ready())
        b._find_phone_input.assert_not_awaited()
        b.page.locator.assert_not_called()

    async def test_phone_readiness_only_uses_trial_click(self):
        b, c = self.browser()
        self.assertTrue(await b._phone_edit_ready())
        field = b._find_phone_input.return_value
        field.click.assert_awaited_once_with(trial=True, timeout=1_000)

    async def test_no_new_tester_requested_until_phone_form_confirmed(self):
        b, c = self.browser()
        b._return_to_phone_form = AsyncMock(side_effect=worker.RegistrationError("reset"))
        b._choose_phone_and_send = AsyncMock()
        with self.assertRaises(worker.RegistrationError):
            await b._replace_phone_tester(object())
        c.revoke_tester.assert_awaited_once()
        b._choose_phone_and_send.assert_not_awaited()

    async def test_replacement_order_revokes_then_confirms_then_requests(self):
        b, c = self.browser()
        calls = []
        c.revoke_tester = AsyncMock(side_effect=lambda r: calls.append("revoke"))
        b._return_to_phone_form = AsyncMock(side_effect=lambda r: calls.append("confirm"))
        b._choose_phone_and_send = AsyncMock(side_effect=lambda r: calls.append("request"))
        await b._replace_phone_tester(object())
        self.assertEqual(calls, ["revoke", "confirm", "request"])


class BrowserFormTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await worker.async_playwright().start()
        self.chrome = await self.playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        self.page = await self.chrome.new_page()
        self.c = SimpleNamespace(cancel_event=asyncio.Event(),
            wait_for_manual_captcha=AsyncMock(side_effect=worker.RequestCancelled("test stop")))
        self.b = worker.RegistrationBrowser(SimpleNamespace(), self.c)
        self.b.page = self.page

    async def asyncTearDown(self):
        await self.chrome.close()
        await self.playwright.stop()

    async def test_explicit_modify_number_clicks_once_and_never_registers(self):
        await self.page.set_content('''<input id="otp" aria-label="Codice SMS">
            <input type="tel" id="phone" hidden>
            <button onclick="window.registered=true">Registrati</button>
            <button onclick="window.edits=(window.edits||0)+1;
                document.querySelector('#otp').remove();
                document.querySelector('#phone').hidden=false">Modifica numero</button>''')
        await self.b._return_to_phone_form(object())
        self.assertEqual(await self.page.evaluate("window.edits"), 1)
        self.assertIsNone(await self.page.evaluate("window.registered"))
        self.c.wait_for_manual_captcha.assert_not_awaited()

    async def test_unknown_controls_preserve_form_without_registration_click(self):
        await self.page.set_content('''<input id="otp" aria-label="Codice SMS">
            <button onclick="window.clicked=true">Registrati</button>
            <button onclick="window.clicked=true">Indietro</button>''')
        with self.assertRaises(worker.RequestCancelled):
            await self.b._return_to_phone_form(object())
        self.assertIsNone(await self.page.evaluate("window.clicked"))
        self.c.wait_for_manual_captcha.assert_awaited_once()

    async def test_reset_screen_does_not_touch_initial_mobile_field(self):
        await self.page.set_content('''<input id="username"><input id="password" type="password">
            <input id="phone" type="tel"><button onclick="window.clicked=true">Registrati</button>''')
        with self.assertRaisesRegex(worker.RegistrationError, "Sessione scaduta"):
            await self.b._return_to_phone_form(object())
        self.assertEqual(await self.page.locator("#phone").input_value(), "")
        self.assertIsNone(await self.page.evaluate("window.clicked"))

    async def test_hidden_initial_credentials_do_not_block_real_phone_form(self):
        await self.page.set_content('''<input id="username" hidden><input id="password" hidden>
            <input id="phone" type="tel">''')
        self.assertTrue(await self.b._phone_edit_ready())
