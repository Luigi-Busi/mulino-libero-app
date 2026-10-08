import json
import unittest
from unittest.mock import AsyncMock
import test_captcha_advance as initial_fixtures
import test_tester_timeout as browser_fixtures
from test_regressions import worker

class ValidationRaceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=browser_fixtures.BrowserFormTests.asyncSetUp
    asyncTearDown=browser_fixtures.BrowserFormTests.asyncTearDown
    initial_form=initial_fixtures.InitialCaptchaTests.initial_form

    async def ready(self,url='https://registrazione.libero.it/join.phtml'):
        return await self.b._initial_captcha_advance_ready(url,'fixture.user','fixture-password')

    async def test_complete_captcha_does_not_click_during_ajax_validation(self):
        await self.initial_form(complete=True,skip_stability=False)
        await self.page.evaluate('window.jQuery={active:1}')
        for _ in range(2):self.assertFalse(await self.ready())
        self.assertEqual(self.b._captcha_diag_last,'validation_pending')
        self.assertIsNone(await self.page.evaluate('window.clicks'))
        await self.page.evaluate('window.jQuery.active=0')
        self.assertFalse(await self.ready())
        self.b._captcha_ready_since -= 4
        self.assertTrue(await self.ready())

    async def test_late_validation_error_restarts_stability_window(self):
        await self.initial_form(complete=True,skip_stability=False)
        self.assertFalse(await self.ready());self.b._captcha_ready_since -= 4
        await self.page.locator('#username_error').evaluate("el=>{el.hidden=false;el.innerText='Controllo in corso'}")
        self.assertFalse(await self.ready());self.assertEqual(self.b._captcha_diag_last,'field_error')
        await self.page.locator('#username_error').evaluate('el=>el.hidden=true')
        self.assertFalse(await self.ready());self.b._captcha_ready_since -= 4
        self.assertTrue(await self.ready())

    async def test_reset_completion_and_disabled_button_restart_stability(self):
        await self.initial_form(complete=True,skip_stability=False)
        self.assertFalse(await self.ready());self.b._captcha_ready_since -= 4
        await self.page.evaluate("document.querySelector('[name=g-recaptcha-response]').value=''")
        self.assertFalse(await self.ready());self.assertIsNone(self.b._captcha_ready_since)
        await self.page.evaluate("document.querySelector('[name=g-recaptcha-response]').value='fixture-complete'")
        self.assertFalse(await self.ready())
        await self.page.locator('#button_submit').evaluate('el=>el.disabled=true')
        self.assertFalse(await self.ready());self.assertIsNone(self.b._captcha_ready_since)

    async def test_initial_alias_allowed_unknown_or_foreign_path_rejected(self):
        await self.initial_form(complete=True,skip_stability=False)
        self.assertFalse(await self.ready('https://registrazione.libero.it/'))
        self.b._captcha_ready_since -= 4
        self.assertTrue(await self.ready('https://registrazione.libero.it/'))
        self.assertFalse(await self.ready('https://registrazione.libero.it/join2.phtml'))
        self.assertFalse(await self.ready('https://example.test/join.phtml'))

    async def test_actual_client_validation_cancels_click_and_is_diagnosed(self):
        await self.initial_form(complete=True,skip_stability=False)
        await self.page.evaluate("document.querySelector('#button_submit').addEventListener('click', e=>e.preventDefault())")
        async def click(selector):
            await self.page.locator(selector).click();await self.page.wait_for_timeout(20)
        self.b._click_and_wait_for_change=AsyncMock(side_effect=click)
        await self.b._click_initial_captcha_advance()
        self.assertEqual(self.b._captcha_diag_last,'click_cancelled')
        self.b._click_and_wait_for_change.assert_awaited_once()

    async def test_real_submit_observation_without_real_network(self):
        await self.initial_form(skip_stability=False)
        await self.page.evaluate("document.body.innerHTML='<form method=post action=/check1.php><button type=submit id=button_submit>Avanti</button></form>'")
        await self.page.route('https://registrazione.libero.it/check1.php',lambda r:r.fulfill(body='<input id=firstname><input id=lastname>',content_type='text/html'))
        async def click(selector):
            await self.page.locator(selector).click()
        self.b._click_and_wait_for_change=AsyncMock(side_effect=click)
        await self.b._click_initial_captcha_advance()
        self.assertEqual(self.b._captcha_diag_last,'post_started')
        self.b._click_and_wait_for_change.assert_awaited_once()

    async def test_diagnostics_only_allowlisted_codes_no_values_and_bounded(self):
        self.b.diagnostics=worker.BrowserDiagnostics('private@example.test')
        with self.assertLogs('libero-mail-bot',level='INFO') as captured:
            for _ in range(60):
                self.b._initial_captcha_diagnostic('validation_pending')
                self.b._initial_captcha_diagnostic('stabilizing')
                self.b._initial_captcha_diagnostic('PRIVATE password=123456')
        self.assertEqual(len(captured.output),80)
        for line in captured.output:
            self.assertNotIn('PRIVATE',line);self.assertNotIn('private@',line);self.assertNotIn('123456',line)
            v=json.loads(line.split('MULINO_CAPTCHA_STATE ',1)[1])
            self.assertEqual(set(v),{'schema','session','state','seq'})
