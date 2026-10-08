import asyncio
import unittest
from unittest.mock import AsyncMock

from test_regressions import worker
import test_tester_timeout as browser_fixtures


class InitialCaptchaTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = browser_fixtures.BrowserFormTests.asyncSetUp
    asyncTearDown = browser_fixtures.BrowserFormTests.asyncTearDown

    async def initial_form(self, *, navigate=True, complete=False, label='Avanti'):
        html = """<input id="username" value="fixture.user"><input id="password" type="password" value="fixture-password">
          <textarea name="g-recaptcha-response" style="display:none">TOKEN</textarea>
          <div class="g-recaptcha" style="height:50px">Verifica manuale</div>
          <div id="username_error" hidden>Username non disponibile</div>
          <button id="button_submit" onclick="window.clicks=(window.clicks||0)+1;
          if (NAVIGATE && window.clicks>1) document.body.innerHTML='<input id=firstname><input id=lastname>'">LABEL</button>"""
        html = html.replace('TOKEN', 'fixture-complete' if complete else '').replace('NAVIGATE', 'true' if navigate else 'false').replace('LABEL',label)
        await self.page.route('https://registrazione.libero.it/**',lambda r:r.fulfill(body=html,content_type='text/html; charset=utf-8'))
        await self.page.goto('https://registrazione.libero.it/join.phtml')
        self.b._dismiss_cookie_banner = AsyncMock()
        async def click(selector):
            await self.page.locator(selector).click()
        self.b._click_and_wait_for_change = AsyncMock(side_effect=click)
        async def personal_ready():
            return await self.page.locator('#firstname').is_visible() and await self.page.locator('#lastname').is_visible()
        self.b._personal_data_page_ready = personal_ready
        self.c.set_queue_fields = AsyncMock()

    async def complete_human_fixture(self):
        await self.page.evaluate("document.querySelector('[name=g-recaptcha-response]').value='fixture-complete'")

    async def test_valid_username_advances_once_after_human_completion(self):
        await self.initial_form()
        async def waiting(request, *, ready_check, **kwargs):
            self.assertFalse(await ready_check())
            self.assertEqual(await self.page.evaluate('window.clicks'),1)
            await self.complete_human_fixture()
            self.assertTrue(await ready_check())
            self.assertTrue(await ready_check())
        self.c.wait_for_manual_captcha.side_effect = waiting
        self.assertTrue(await self.b._open_personal_data_page(object()))
        self.assertEqual(await self.page.evaluate('window.clicks'),2)
        self.assertEqual(self.b._click_and_wait_for_change.await_count,2)

    async def test_username_unavailable_returns_to_normal_candidate_selection_without_click(self):
        await self.initial_form()
        async def waiting(request, *, ready_check, **kwargs):
            await self.complete_human_fixture()
            await self.page.locator('#username_error').evaluate('(node)=>node.hidden=false')
            self.assertTrue(await ready_check())
        self.c.wait_for_manual_captcha.side_effect = waiting
        self.assertFalse(await self.b._open_personal_data_page(object()))
        self.assertEqual(await self.page.evaluate('window.clicks'),1)

    async def test_user_already_advanced_does_not_click_again(self):
        await self.initial_form()
        async def waiting(request, *, ready_check, **kwargs):
            await self.page.evaluate("document.body.innerHTML='<input id=firstname><input id=lastname>'")
            self.assertTrue(await ready_check())
        self.c.wait_for_manual_captcha.side_effect = waiting
        self.assertTrue(await self.b._open_personal_data_page(object()))
        self.assertEqual(await self.page.evaluate('window.clicks'),1)

    async def test_uncertain_click_never_repeats_on_later_polls(self):
        await self.initial_form(navigate=False)
        async def waiting(request, *, ready_check, **kwargs):
            await self.complete_human_fixture()
            for _ in range(3):
                self.assertFalse(await ready_check())
            raise worker.RequestCancelled('end fixture')
        self.c.wait_for_manual_captcha.side_effect = waiting
        with self.assertRaises(worker.RequestCancelled):
            await self.b._open_personal_data_page(object())
        self.assertEqual(await self.page.evaluate('window.clicks'),2)

    async def test_hidden_widget_without_completion_never_auto_advances(self):
        await self.initial_form()
        async def waiting(request, *, ready_check, **kwargs):
            await self.page.locator('.g-recaptcha').evaluate('(node)=>node.remove()')
            self.assertFalse(await ready_check())
            raise worker.RequestCancelled('end fixture')
        self.c.wait_for_manual_captcha.side_effect = waiting
        with self.assertRaises(worker.RequestCancelled):
            await self.b._open_personal_data_page(object())
        self.assertEqual(await self.page.evaluate('window.clicks'),1)

    async def test_changed_username_or_password_prevents_auto_submit(self):
        for field in ('#username','#password'):
            await self.initial_form()
            async def waiting(request, *, ready_check, **kwargs):
                await self.complete_human_fixture()
                await self.page.locator(field).fill('changed-fixture')
                self.assertFalse(await ready_check())
                raise worker.RequestCancelled('end fixture')
            self.c.wait_for_manual_captcha.side_effect = waiting
            with self.assertRaises(worker.RequestCancelled):
                await self.b._open_personal_data_page(object())
            self.assertEqual(await self.page.evaluate('window.clicks'),1)

    async def test_captcha_completed_before_first_click_still_advances_when_initial_form_remains(self):
        await self.initial_form(complete=True)
        async def waiting(request, *, ready_check, **kwargs):
            self.assertTrue(await ready_check())
            self.assertTrue(await ready_check())
        self.c.wait_for_manual_captcha.side_effect = waiting
        self.assertTrue(await self.b._open_personal_data_page(object()))
        self.assertEqual(await self.page.evaluate('window.clicks'),2)

    async def test_already_completed_captcha_and_uncertain_advance_never_clicks_repeatedly(self):
        await self.initial_form(complete=True,navigate=False)
        async def waiting(request, *, ready_check, **kwargs):
            for _ in range(4):
                self.assertFalse(await ready_check())
            raise worker.RequestCancelled('end fixture')
        self.c.wait_for_manual_captcha.side_effect = waiting
        with self.assertRaises(worker.RequestCancelled):
            await self.b._open_personal_data_page(object())
        self.assertEqual(await self.page.evaluate('window.clicks'),2)

    async def test_disabled_button_waits_until_enabled_and_clicks_once(self):
        await self.initial_form()
        async def waiting(request, *, ready_check, **kwargs):
            await self.complete_human_fixture()
            await self.page.locator('#button_submit').evaluate('(node)=>node.disabled=true')
            self.assertFalse(await ready_check())
            await self.page.locator('#button_submit').evaluate('(node)=>node.disabled=false')
            self.assertTrue(await ready_check())
        self.c.wait_for_manual_captcha.side_effect = waiting
        self.assertTrue(await self.b._open_personal_data_page(object()))
        self.assertEqual(await self.page.evaluate('window.clicks'),2)

    async def test_cancellation_prevents_automatic_click(self):
        await self.initial_form()
        async def waiting(request, *, ready_check, **kwargs):
            await self.complete_human_fixture()
            self.c.cancel_event.set()
            await ready_check()
        self.c.wait_for_manual_captcha.side_effect = waiting
        with self.assertRaises(worker.RequestCancelled):
            await self.b._open_personal_data_page(object())
        self.assertEqual(await self.page.evaluate('window.clicks'),1)

    async def test_final_registration_button_is_not_auto_submitted(self):
        await self.initial_form(label='Registrati')
        async def waiting(request, *, ready_check, **kwargs):
            await self.complete_human_fixture()
            self.assertFalse(await ready_check())
            raise worker.RequestCancelled('end fixture')
        self.c.wait_for_manual_captcha.side_effect = waiting
        with self.assertRaises(worker.RequestCancelled):
            await self.b._open_personal_data_page(object())
        self.assertEqual(await self.page.evaluate('window.clicks'),1)
