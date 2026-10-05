"""Expired registration sessions: synthetic Telegram fixtures and local HTML only."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_regressions as fixtures
from test_regressions import worker
import test_tester_timeout as browser_fixtures


class CoordinatorResetTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.CoordinatorTests.asyncSetUp
    asyncTearDown = fixtures.CoordinatorTests.asyncTearDown

    async def reset(self):
        raise worker.RegistrationSessionReset("Sessione scaduta")

    async def assigned(self):
        await self.coordinator.claim_phone(11)
        await self.coordinator.notify_otp_sent(self.request, 11, "+393330000011")
        self.coordinator.send_temporary = AsyncMock()

    async def test_reset_while_waiting_for_tester_invalidates_claim(self):
        c = self.coordinator
        before = asyncio.all_tasks()
        with self.assertRaises(worker.RegistrationSessionReset):
            await c.request_phone(self.request, ready_check=self.reset)
        self.assertTrue(c.phone_future.cancelled())
        self.assertEqual(c.claim_token, "")
        self.assertFalse((await c.claim_phone(11))[0])
        self.assertFalse([t for t in asyncio.all_tasks() - before if not t.done()])

    async def test_reset_wins_over_simultaneously_received_code_and_resend(self):
        await self.assigned()
        c = self.coordinator
        c.otp_future.set_result("123456")
        c.resend_event.set()
        resend = AsyncMock()
        with self.assertRaises(worker.RegistrationSessionReset):
            await c.request_otp(self.request, resend=resend, ready_check=self.reset)
        resend.assert_not_awaited()
        self.assertEqual(c.assignment_token, "")
        self.assertFalse(c.resend_busy)
        self.assertEqual(c.outcomes.testers.stats(11)["count"], 0)

    async def test_reset_from_resend_is_not_reported_as_uncertain_sms(self):
        await self.assigned()
        c = self.coordinator
        c.resend_event.set()
        with self.assertRaises(worker.RegistrationSessionReset):
            await c.request_otp(self.request, resend=self.reset)
        c.send_temporary.assert_not_awaited()
        self.assertTrue(c.otp_future.cancelled())
        self.assertFalse(c.resend_busy)

    async def test_normal_resend_uncertainty_still_preserves_session(self):
        await self.assigned()
        c = self.coordinator
        c.resend_event.set()
        async def send(*args, **kwargs):
            c.otp_future.set_result("123456")
        c.send_temporary.side_effect = send
        resend = AsyncMock(side_effect=worker.RegistrationError("control absent"))
        self.assertEqual(await c.request_otp(self.request, resend=resend, ready_check=AsyncMock()), "123456")
        self.assertIn("Non posso confermare", c.send_temporary.call_args.kwargs["text"])
        self.assertTrue(c.assignment_token)

    async def test_delayed_claim_does_not_assign_after_session_invalidated(self):
        c = self.coordinator
        entered, resume = asyncio.Event(), asyncio.Event()
        original_send = c.send_temporary
        async def delayed_send(*args, **kwargs):
            entered.set()
            await resume.wait()
            return await original_send(*args, **kwargs)
        c.send_temporary = delayed_send
        task = asyncio.create_task(c.claim_phone(11))
        await entered.wait()
        c.invalidate_phone_session()
        resume.set()
        self.assertFalse((await task)[0])
        self.assertEqual(self.request.claimed_by, "")
        self.assertTrue(c.phone_future.cancelled())

    async def test_cancel_wins_without_calling_browser(self):
        c = self.coordinator
        c.cancel_event.set()
        check = AsyncMock(side_effect=worker.RegistrationSessionReset("reset"))
        with self.assertRaises(worker.RequestCancelled):
            await c._wait_future(c.phone_future, ready_check=check)
        check.assert_not_awaited()

    async def test_polling_without_user_input_detects_reset_before_deadline(self):
        await self.assigned()
        c = self.coordinator
        calls = 0
        async def check():
            nonlocal calls
            calls += 1
            if calls >= 2:
                await self.reset()
        deadline = c.tester_sms_deadline
        with self.assertRaises(worker.RegistrationSessionReset):
            await asyncio.wait_for(c.request_otp(self.request, ready_check=check), 3)
        self.assertGreater(deadline, asyncio.get_running_loop().time())

    async def test_final_confirmation_is_monitored_during_phone_step(self):
        c = self.coordinator
        with self.assertRaises(worker.RegistrationSessionReset):
            await c.request_final_confirmation(self.request, "synthetic", ready_check=self.reset)
        self.assertTrue(c.phone_future.cancelled())

    async def test_process_marks_error_and_notifies_tester_without_credit(self):
        await self.assigned()
        c = self.coordinator
        c.paused = False
        c.request_personal_data = AsyncMock(return_value=object())
        browser = SimpleNamespace(create_account=AsyncMock(side_effect=worker.RegistrationSessionReset("Sessione scaduta")))
        with patch.object(worker, "RegistrationBrowser", return_value=browser):
            await c.process_request(self.request)
        self.assertEqual(self.request.status, "ERRORE")
        notices = [x.kwargs for x in self.bot.send_message.call_args_list]
        self.assertTrue(any(x["chat_id"] == 11 and "non attendere" in x["text"] for x in notices))
        self.assertTrue(any(x["chat_id"] == 99 and "Sessione scaduta" in x["text"] for x in notices))
        self.assertEqual(c.outcomes.testers.stats(11)["count"], 0)
        self.assertIsNone(c.active)


class BrowserResetTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = browser_fixtures.BrowserFormTests.asyncSetUp
    asyncTearDown = browser_fixtures.BrowserFormTests.asyncTearDown

    async def initial_form(self):
        await self.page.set_content('''<input id="username"><input id="password" type="password">
            <input id="phone" type="tel"><button onclick="window.clicked=true">Invia di nuovo</button>
            <button onclick="window.clicked=true">Registrati</button>''')

    async def test_tester_assignment_after_reset_does_not_fill_initial_phone(self):
        await self.page.set_content('<input id="phone" type="tel">')
        async def assign(*args, **kwargs):
            await self.initial_form()
            return "+393330000011", 11
        self.c.request_phone = AsyncMock(side_effect=assign)
        self.c.change_tester_event = asyncio.Event()
        self.c.notify_otp_sent = AsyncMock()
        with self.assertRaises(worker.RegistrationSessionReset):
            await self.b._choose_phone_and_send(object())
        self.assertEqual(await self.page.locator("#phone").input_value(), "")
        self.assertIsNone(await self.page.evaluate("window.clicked"))
        self.c.notify_otp_sent.assert_not_awaited()

    async def test_resend_on_reset_never_clicks_even_when_label_present(self):
        await self.initial_form()
        with self.assertRaises(worker.RegistrationSessionReset):
            await self.b._resend_sms()
        self.assertIsNone(await self.page.evaluate("window.clicked"))

    async def test_wait_for_otp_stops_on_reset_without_manual_wait(self):
        await self.initial_form()
        with self.assertRaises(worker.RegistrationSessionReset):
            await self.b._wait_for_otp_input(object())
        self.c.wait_for_manual_captcha.assert_not_awaited()

    async def test_otp_overlay_prevents_false_reset_and_allows_single_resend(self):
        await self.initial_form()
        await self.page.set_content('''<input id="username"><input id="password">
            <input id="otp" aria-label="Codice SMS">
            <button onclick="window.clicks=(window.clicks||0)+1">Invia di nuovo</button>''')
        await self.b._resend_sms()
        self.assertEqual(await self.page.evaluate("window.clicks"), 1)

    async def test_hidden_credentials_or_unknown_page_are_not_declared_expired(self):
        for html in ('<input id="username" hidden><input id="password" hidden><input type="tel">',
                     '<h1>Caricamento</h1>', '<input id="username"><input id="password" hidden>'):
            await self.page.set_content(html)
            await self.b._assert_phone_session()

    async def test_visible_disabled_otp_is_not_a_reset(self):
        await self.page.set_content('''<input id="username"><input id="password">
            <input id="otp" aria-label="Codice SMS" disabled>''')
        await self.b._assert_phone_session()
        self.assertIsNone(await self.b._find_otp_input())

    async def test_real_page_reset_during_unclaimed_wait_rejects_late_tester(self):
        await self.page.set_content('<input id="phone" type="tel">')
        c = worker.Coordinator(SimpleNamespace(admin_id=99, group_chat_id=-100987),
            SimpleNamespace(whitelist_map=Mock(return_value={11: "+393330000011"}), update=Mock()))
        r = worker.QueueRequest(2, "synthetic-reset", "ATTESA_UTENTE", "sheet", "tab", 4, 3, "Test Persona")
        c.active = r
        c.set_queue_fields = AsyncMock()
        c.send_temporary = AsyncMock(return_value=SimpleNamespace(message_id=1))
        c.cleanup_messages = AsyncMock()
        self.b.coordinator = c
        task = asyncio.create_task(c.request_phone(r, ready_check=self.b._assert_phone_session))
        try:
            await asyncio.sleep(.1)
            await self.initial_form()
            with self.assertRaises(worker.RegistrationSessionReset):
                await asyncio.wait_for(task, 3)
            self.assertFalse((await c.claim_phone(11))[0])
            self.assertEqual(await self.page.locator("#phone").input_value(), "")
            self.assertIsNone(await self.page.evaluate("window.clicked"))
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            c.messages.close()
            c.outcomes.close()
