"""Unknown registration screens must preserve the session and never imply success."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from test_regressions import worker


class OutcomeCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.request = worker.QueueRequest(2, "request", "IN_CREAZIONE", "sheet", "tab", 4, 3, "Test Persona")
        self.writes = []

        def update(request, **fields):
            self.writes.append(fields)
            request.status = fields.get("STATO", request.status)

        self.coordinator = worker.Coordinator(
            SimpleNamespace(admin_id=99, group_chat_id=-100, remote_browser_url="http://127.0.0.1:6080/vnc.html"),
            SimpleNamespace(update=update),
        )
        self.coordinator.active = self.request
        self.prompt_sent = asyncio.Event()
        self.messages = []

        async def send(request, phase, **kwargs):
            self.messages.append(kwargs)
            self.prompt_sent.set()

        self.coordinator.send_temporary = AsyncMock(side_effect=send)
        self.coordinator.cleanup_messages = AsyncMock()
        self.ready = AsyncMock(return_value=None)
        self.tasks = []

    async def asyncTearDown(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.coordinator.messages.close()
        self.coordinator.outcomes.close()

    async def begin(self, allowed=True):
        task = asyncio.create_task(self.coordinator.wait_for_registration_outcome(
            self.request, "test.persona", ready_check=self.ready, allow_confirmation=allowed,
        ))
        self.tasks.append(task)
        await asyncio.wait_for(self.prompt_sent.wait(), 1)
        return task

    def query(self, data, *, user=99, chat=99, kind="private"):
        return SimpleNamespace(data=data, from_user=SimpleNamespace(id=user),
                               message=SimpleNamespace(chat=SimpleNamespace(id=chat, type=kind)),
                               answer=AsyncMock())

    async def callback(self, query):
        context = SimpleNamespace(application=SimpleNamespace(bot_data={"coordinator": self.coordinator}))
        await worker.callback_handler(SimpleNamespace(callback_query=query), context)


class OutcomeConfirmationTests(OutcomeCase):
    async def test_unknown_stays_pending_without_writing_a_created_outcome(self):
        task = await self.begin()
        self.assertFalse(task.done())
        self.assertEqual(self.request.status, "ATTESA_CONFERMA")
        self.assertEqual(self.coordinator.outcomes.ids(), set())
        self.assertEqual(len(self.messages), 1)
        self.assertIn("browser resta aperto", self.messages[0]["text"])

    async def test_manual_confirmation_requires_two_distinct_buttons(self):
        task = await self.begin()
        review = self.coordinator.outcome_review
        await self.callback(self.query(f"outcome_yes:{review['token']}"))
        self.assertFalse(task.done())
        await self.callback(self.query(f"outcome:{review['token']}"))
        self.assertFalse(review["future"].done())
        self.assertIn("test.persona@libero.it", self.messages[-1]["text"])
        self.assertNotEqual(review["token"], review["confirmation_token"])
        await self.callback(self.query(f"outcome_yes:{review['confirmation_token']}"))
        self.assertEqual(await asyncio.wait_for(task, 1), "created")
        saved = self.coordinator.outcomes.get(self.request.request_id)
        self.assertEqual(saved[1:3], ("test.persona", "test.persona@libero.it"))
        self.assertIsNone(self.coordinator.outcome_review)
        self.coordinator.cleanup_messages.assert_awaited_once_with(self.request, "outcome")

    async def test_other_user_group_wrong_chat_and_expired_buttons_cannot_confirm(self):
        task = await self.begin()
        review = self.coordinator.outcome_review
        for kwargs in ({"user": 22}, {"kind": "supergroup"}, {"chat": 22}):
            await self.callback(self.query(f"outcome:{review['token']}", **kwargs))
            self.assertEqual(review["confirmation_token"], "")
        await self.callback(self.query("outcome:expired"))
        self.assertEqual(len(self.messages), 1)
        await self.callback(self.query(f"outcome:{review['token']}"))
        confirm = f"outcome_yes:{review['confirmation_token']}"
        for kwargs in ({"user": 22}, {"kind": "supergroup"}, {"chat": 22}):
            await self.callback(self.query(confirm, **kwargs))
            self.assertFalse(review["future"].done())
        self.coordinator.active = worker.QueueRequest(3, "different", "IN_CREAZIONE", "s", "t", 1, 2, "Other")
        await self.callback(self.query(confirm))
        self.assertFalse(task.done())

    async def test_repeated_first_click_does_not_duplicate_confirmation(self):
        await self.begin()
        data = f"outcome:{self.coordinator.outcome_review['token']}"
        await self.callback(self.query(data))
        await self.callback(self.query(data))
        self.assertEqual(len(self.messages), 2)

    async def test_cancellation_wins_over_confirmation_and_cleans_pending_review(self):
        task = await self.begin()
        review = self.coordinator.outcome_review
        await self.callback(self.query(f"outcome:{review['token']}"))
        self.coordinator.cancel_event.set()
        await self.callback(self.query(f"outcome_yes:{review['confirmation_token']}"))
        with self.assertRaises(worker.RequestCancelled):
            await asyncio.wait_for(task, 1)
        self.assertIsNone(self.coordinator.outcome_review)
        self.assertTrue(review["future"].cancelled())
        self.assertEqual(self.coordinator.outcomes.ids(), set())

    async def test_shutdown_cleans_pending_review(self):
        task = await self.begin()
        review = self.coordinator.outcome_review
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(self.coordinator.outcome_review)
        self.assertTrue(review["future"].cancelled())

    async def test_known_success_and_late_phone_resume_automatically(self):
        for result in ("created", "next"):
            with self.subTest(result=result):
                self.ready.return_value = result
                task = await self.begin()
                self.assertEqual(await asyncio.wait_for(task, 1), result)
                self.assertIsNone(self.coordinator.outcome_review)

    async def test_explicit_site_error_is_not_converted_to_success(self):
        self.ready.side_effect = worker.RegistrationError("Registrazione fallita")
        task = await self.begin()
        with self.assertRaisesRegex(worker.RegistrationError, "fallita"):
            await task
        self.assertEqual(self.coordinator.outcomes.ids(), set())
        self.assertIsNone(self.coordinator.outcome_review)

    async def test_confirmed_outcome_survives_cleanup_failure(self):
        self.ready.return_value = "created"
        self.coordinator.cleanup_messages.side_effect = RuntimeError("cleanup unavailable")
        task = await self.begin()
        with self.assertRaisesRegex(RuntimeError, "cleanup unavailable"):
            await task
        self.assertEqual(self.coordinator.outcomes.get(self.request.request_id)[2], "test.persona@libero.it")

    async def test_no_manual_created_button_before_final_submission(self):
        task = await self.begin(allowed=False)
        self.assertIsNone(self.messages[0]["reply_markup"])
        await self.callback(self.query(f"outcome:{self.coordinator.outcome_review['token']}"))
        self.assertEqual(len(self.messages), 1)
        self.assertFalse(task.done())

    async def test_success_before_final_submission_does_not_bypass_caller_authorization(self):
        self.ready.return_value = "created"
        task = await self.begin(allowed=False)
        self.assertEqual(await task, "created")
        self.assertEqual(self.coordinator.outcomes.ids(), set())

    async def test_old_confirmation_cannot_confirm_new_wait_for_same_request(self):
        first = await self.begin()
        review = self.coordinator.outcome_review
        await self.callback(self.query(f"outcome:{review['token']}"))
        stale = f"outcome_yes:{review['confirmation_token']}"
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.prompt_sent.clear()
        second = await self.begin()
        await self.callback(self.query(stale))
        self.assertFalse(second.done())
        self.assertFalse(self.coordinator.outcome_review["future"].done())


class RegistrationFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.request = worker.QueueRequest(2, "request", "IN_CREAZIONE", "sheet", "tab", 4, 3, "Test Persona")
        self.personal = worker.PersonalData("Test", "Persona", "01/01/1990", "M", "Roma")
        self.coordinator = SimpleNamespace(
            cancel_event=asyncio.Event(), request_final_confirmation=AsyncMock(),
            wait_for_registration_outcome=AsyncMock(return_value="created"),
        )
        self.browser = worker.RegistrationBrowser(SimpleNamespace(), self.coordinator)
        self.browser.page = SimpleNamespace(wait_for_timeout=AsyncMock(), is_closed=Mock(return_value=False))
        for name in ("_handle_captcha_if_needed", "_fill_account_protection", "_check_required_boxes", "_choose_phone_and_send", "_verify_sms_until_completed", "_click_and_wait_for_change"):
            setattr(self.browser, name, AsyncMock())
        self.browser._is_success_page = AsyncMock(return_value=False)
        self.browser._is_account_protection_page = AsyncMock(return_value=False)
        self.browser._find_phone_input = AsyncMock(return_value=None)
        self.browser._find_final_button = AsyncMock(return_value=None)
        self.browser._find_button = AsyncMock(return_value=None)

    async def complete(self):
        await asyncio.wait_for(self.browser._complete_remaining_steps(self.request, "test.persona", self.personal), 1)

    async def test_no_sms_after_protection_is_successful(self):
        self.browser._is_success_page.side_effect = [False, True]
        self.browser._is_account_protection_page.return_value = True
        self.browser._find_final_button.return_value = AsyncMock()
        await self.complete()
        self.coordinator.request_final_confirmation.assert_awaited_once()
        self.browser._choose_phone_and_send.assert_not_awaited()
        self.browser._verify_sms_until_completed.assert_not_awaited()

    async def test_unknown_after_submit_waits_and_never_clicks_register_again(self):
        button = SimpleNamespace(click=AsyncMock())
        self.browser._find_final_button.return_value = button
        await self.complete()
        button.click.assert_awaited_once()
        self.coordinator.wait_for_registration_outcome.assert_awaited_once()
        self.assertTrue(self.coordinator.wait_for_registration_outcome.call_args.kwargs["allow_confirmation"])
        self.browser._choose_phone_and_send.assert_not_awaited()

    async def test_stale_protection_title_after_submit_waits_instead_of_failing(self):
        self.browser._is_account_protection_page.return_value = True
        self.browser._find_final_button.return_value = AsyncMock()
        await self.complete()
        self.browser._fill_account_protection.assert_awaited_once()
        self.browser._click_and_wait_for_change.assert_awaited_once()
        self.coordinator.wait_for_registration_outcome.assert_awaited_once()

    async def test_delayed_success_during_grace_does_not_prompt_operator(self):
        self.browser._is_success_page.side_effect = [False, False, True]
        result = await self.browser._wait_for_registration_step(self.request, "test.persona", final_submitted=True)
        self.assertEqual(result, "created")
        self.coordinator.wait_for_registration_outcome.assert_not_awaited()

    async def test_navigation_replacing_page_body_does_not_close_registration(self):
        self.browser._is_success_page.side_effect = [worker.PlaywrightError("Execution context was destroyed"), True]
        result = await self.browser._wait_for_registration_step(self.request, "test.persona", final_submitted=True)
        self.assertEqual(result, "created")
        self.coordinator.wait_for_registration_outcome.assert_not_awaited()

    async def test_delayed_phone_resumes_existing_sms_flow(self):
        button = SimpleNamespace(click=AsyncMock())
        self.browser._find_final_button.return_value = button
        self.browser._find_phone_input.side_effect = [None, None, object(), object(), None]
        await self.complete()
        button.click.assert_awaited_once()
        self.browser._choose_phone_and_send.assert_awaited_once()
        self.browser._verify_sms_until_completed.assert_awaited_once()

    async def test_unknown_before_submission_waits_without_manual_success_option(self):
        async def resolve(*args, **kwargs):
            self.browser._find_final_button.return_value = SimpleNamespace(click=AsyncMock())
            self.browser._is_success_page.side_effect = [False, True]
            return "next"
        self.coordinator.wait_for_registration_outcome.side_effect = resolve
        await self.complete()
        self.assertFalse(self.coordinator.wait_for_registration_outcome.call_args.kwargs["allow_confirmation"])

    async def test_success_before_authorization_is_not_silently_accepted(self):
        self.browser._is_success_page.return_value = True
        with self.assertRaisesRegex(worker.RegistrationError, "prima della conferma"):
            await self.complete()


class BrowserFixtureTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_browser_no_sms_and_unknown_screen_remains_open(self):
        # All requests are served from synthetic HTML in this process; no live site.
        async with worker.async_playwright() as playwright:
            chromium = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await chromium.new_context()
            page = await context.new_page()
            prompt = asyncio.Event()
            release = asyncio.Event()
            closed = []
            page.on("close", lambda: closed.append(True))

            async def wait_outcome(*args, **kwargs):
                prompt.set()
                await release.wait()
                return "created"

            coordinator = SimpleNamespace(cancel_event=asyncio.Event(),
                request_final_confirmation=AsyncMock(), wait_for_registration_outcome=AsyncMock(side_effect=wait_outcome))
            browser = worker.RegistrationBrowser(SimpleNamespace(), coordinator)
            browser.page = page
            request = worker.QueueRequest(2, "fixture", "IN_CREAZIONE", "s", "t", 1, 2, "Test")
            personal = worker.PersonalData("Test", "Persona", "01/01/1990", "M", "Roma")

            async def load_fixture(content):
                await page.unroute("**/*")
                await page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=content))
                await page.goto("https://registrazione.libero.it/fixture")

            try:
                await load_fixture('<button onclick="document.body.innerHTML=\'Registrazione completata\'">Registrati</button>')
                await asyncio.wait_for(browser._complete_remaining_steps(request, "test.persona", personal), 15)
                coordinator.wait_for_registration_outcome.assert_not_awaited()
                await load_fixture('<button onclick="document.body.innerHTML=\'Schermata finale sconosciuta\'">Registrati</button>')
                task = asyncio.create_task(browser._complete_remaining_steps(request, "test.persona", personal))
                try:
                    await asyncio.wait_for(prompt.wait(), 25)
                    self.assertFalse(task.done())
                    self.assertFalse(page.is_closed())
                    self.assertEqual(closed, [])
                    self.assertIn("sconosciuta", await page.locator("body").inner_text())
                    release.set()
                    await asyncio.wait_for(task, 2)
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            finally:
                await context.close()
                await chromium.close()


if __name__ == "__main__":
    unittest.main()
