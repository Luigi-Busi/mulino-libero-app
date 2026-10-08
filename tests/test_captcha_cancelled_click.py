import unittest
from unittest.mock import AsyncMock
import test_captcha_advance as initial_fixtures
import test_tester_timeout as browser_fixtures
from test_regressions import worker

class CancelledClickTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=browser_fixtures.BrowserFormTests.asyncSetUp
    asyncTearDown=browser_fixtures.BrowserFormTests.asyncTearDown
    initial_form=initial_fixtures.InitialCaptchaTests.initial_form

    async def form(self, *,cancel_clicks=2,cancel_submit=False,action='/check1.php'):
        await self.initial_form(complete=True,navigate=False)
        await self.page.evaluate("""({cancelClicks,cancelSubmit,action})=>{
            const form=document.createElement('form');form.id='userdata';form.method='post';form.action=action;
            while(document.body.firstChild)form.appendChild(document.body.firstChild);
            document.body.appendChild(form);
            const button=document.querySelector('#button_submit');button.removeAttribute('onclick');
            button.addEventListener('click', e=>{window.clicks=(window.clicks||0)+1;if(window.clicks<=cancelClicks)e.preventDefault();});
            if(cancelSubmit)form.addEventListener('submit',e=>e.preventDefault());
        }""",dict(cancelClicks=cancel_clicks,cancelSubmit=cancel_submit,action=action))
        await self.page.route('https://registrazione.libero.it/check1.php',lambda r:r.fulfill(body='<input id=firstname><input id=lastname>',content_type='text/html'))
        async def click(selector):
            await self.page.locator(selector).click();await self.page.wait_for_timeout(20)
        self.b._click_and_wait_for_change=AsyncMock(side_effect=click)

    async def poll(self, ready_check, limit=6):
        for _ in range(limit):
            if await ready_check():return
        raise worker.RequestCancelled('fixture ended')

    async def test_proven_cancel_before_submit_retries_once_then_advances(self):
        await self.form()
        async def wait(request,*,ready_check,**kwargs):await self.poll(ready_check)
        self.c.wait_for_manual_captcha.side_effect=wait
        self.assertTrue(await self.b._open_personal_data_page(object()))
        self.assertEqual(self.b._click_and_wait_for_change.await_count,3)
        self.assertEqual(self.b._initial_posts,1)

    async def test_repeated_client_cancellation_has_strict_three_total_click_cap(self):
        await self.form(cancel_clicks=99)
        async def wait(request,*,ready_check,**kwargs):await self.poll(ready_check)
        self.c.wait_for_manual_captcha.side_effect=wait
        with self.assertRaises(worker.RequestCancelled):await self.b._open_personal_data_page(object())
        self.assertEqual(self.b._click_and_wait_for_change.await_count,3)
        self.assertEqual(self.b._initial_posts,0)

    async def test_cancelled_submit_is_not_proof_of_no_submission(self):
        await self.form(cancel_clicks=1,cancel_submit=True)
        async def wait(request,*,ready_check,**kwargs):await self.poll(ready_check)
        self.c.wait_for_manual_captcha.side_effect=wait
        with self.assertRaises(worker.RequestCancelled):await self.b._open_personal_data_page(object())
        self.assertEqual(self.b._click_and_wait_for_change.await_count,2)

    async def test_untrusted_form_never_gets_retry(self):
        await self.form(cancel_clicks=99,action='/unknown.php')
        async def wait(request,*,ready_check,**kwargs):await self.poll(ready_check)
        self.c.wait_for_manual_captcha.side_effect=wait
        with self.assertRaises(worker.RequestCancelled):await self.b._open_personal_data_page(object())
        self.assertEqual(self.b._click_and_wait_for_change.await_count,2)

    async def test_late_ajax_post_invalidates_proof(self):
        await self.form(cancel_clicks=99)
        await self.page.route('https://registrazione.libero.it/late-check',lambda r:r.fulfill(body='ok'))
        async def wait(request,*,ready_check,**kwargs):
            self.assertFalse(await ready_check());self.assertIsNotNone(self.b._initial_retry_proof)
            await self.page.evaluate("fetch('/late-check',{method:'POST'})")
            self.assertFalse(await ready_check());self.assertIsNone(self.b._initial_retry_proof)
            raise worker.RequestCancelled('fixture ended')
        self.c.wait_for_manual_captcha.side_effect=wait
        with self.assertRaises(worker.RequestCancelled):await self.b._open_personal_data_page(object())
        self.assertEqual(self.b._click_and_wait_for_change.await_count,2)

    async def test_same_url_new_document_invalidates_proof(self):
        await self.form(cancel_clicks=99)
        async def wait(request,*,ready_check,**kwargs):
            self.assertFalse(await ready_check());self.assertIsNotNone(self.b._initial_retry_proof)
            await self.page.reload()
            self.assertFalse(await ready_check());self.assertIsNone(self.b._initial_retry_proof)
            raise worker.RequestCancelled('fixture ended')
        self.c.wait_for_manual_captcha.side_effect=wait
        with self.assertRaises(worker.RequestCancelled):await self.b._open_personal_data_page(object())
        self.assertEqual(self.b._click_and_wait_for_change.await_count,2)

    async def test_new_human_completion_still_required_after_captcha_expires(self):
        await self.form()
        async def wait(request,*,ready_check,**kwargs):
            self.assertFalse(await ready_check());self.assertIsNotNone(self.b._initial_retry_proof)
            await self.page.evaluate("document.querySelector('[name=g-recaptcha-response]').value=''")
            self.assertFalse(await ready_check());self.assertEqual(self.b._click_and_wait_for_change.await_count,2)
            await self.page.evaluate("document.querySelector('[name=g-recaptcha-response]').value='fixture-complete'")
            self.assertTrue(await ready_check())
        self.c.wait_for_manual_captcha.side_effect=wait
        self.assertTrue(await self.b._open_personal_data_page(object()))
        self.assertEqual(self.b._click_and_wait_for_change.await_count,3)

    async def test_cancellation_prohibits_retry_and_removes_observers(self):
        await self.form(cancel_clicks=99)
        async def wait(request,*,ready_check,**kwargs):
            self.assertFalse(await ready_check());self.c.cancel_event.set();await ready_check()
        self.c.wait_for_manual_captcha.side_effect=wait
        with self.assertRaises(worker.RequestCancelled):await self.b._open_personal_data_page(object())
        self.assertEqual(self.b._click_and_wait_for_change.await_count,2)
        self.assertIsNone(self.b._initial_retry_proof)
